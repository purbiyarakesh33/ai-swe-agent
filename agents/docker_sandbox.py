"""Docker sandbox mechanics -- copies a repo into an isolated container so
Agent 3 can read/patch/test a working copy without ever touching the real
repo on disk. The real repo is modified only by the human-approved Git
promotion service -- never automatically or by an LLM agent."""
import os
import subprocess
import uuid

SANDBOX_IMAGE = "python:3.11-slim"
SANDBOX_WORKDIR = "/workspace"


def _safe_relative_path(relative_path: str) -> str:
    """Return a normalized repo-relative path or reject unsafe paths."""
    normalized = os.path.normpath(relative_path).replace("\\", "/")
    if (
        not normalized
        or os.path.isabs(relative_path)
        or normalized == ".."
        or normalized.startswith("../")
    ):
        raise ValueError(f"Path must stay inside the repository: {relative_path!r}")
    return normalized


class Sandbox:
    """One running container wrapping a writable copy of repo_path.
    The original repo_path is mounted read-only and copied from -- nothing
    in start(), run(), or read_file() can write back to it. Only promote()
    touches the real repo, one file at a time, only when explicitly called.
    """

    def __init__(self, repo_path: str):
        self.repo_path = os.path.abspath(repo_path)
        self.container_name = f"bugfix-agent-{uuid.uuid4().hex[:8]}"
        self._started = False
        self.patched_files = []  # populated by apply_patch on real success -- ground truth

    @classmethod
    def attach(cls, repo_path: str, container_name: str):
        """Reconnect to a running sandbox after a persisted graph resume."""
        sandbox = cls(repo_path)
        sandbox.container_name = container_name
        sandbox._started = True
        return sandbox

    def start(self):
        """Start the container with repo_path mounted read-only at /repo_ro,
        then copy it into a writable working directory inside the container."""
        result = subprocess.run(
            ["docker", "run", "-d", "--name", self.container_name,
             "-v", f"{self.repo_path}:/repo_ro:ro",
             SANDBOX_IMAGE, "sleep", "infinity"],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Docker failed to start the sandbox container:\n{result.stderr.strip()}")
        self._started = True
        self._exec(["mkdir", "-p", SANDBOX_WORKDIR])
        copy_result = self._exec(["sh", "-c", f"cp -r /repo_ro/. {SANDBOX_WORKDIR}/"])
        if copy_result.returncode != 0:
            self.stop()
            raise RuntimeError(f"Failed to copy repo into sandbox: {copy_result.stderr}")

        self._exec(["pip", "install", "--quiet", "pytest"], cwd=SANDBOX_WORKDIR, timeout=300)
        req_check = self._exec(["test", "-f", "requirements.txt"], cwd=SANDBOX_WORKDIR)
        if req_check.returncode == 0:
            dep_result = self._exec(["pip", "install", "--quiet", "-r", "requirements.txt"],
                                     cwd=SANDBOX_WORKDIR, timeout=300)
            if dep_result.returncode != 0:
                print(f"[sandbox] WARNING: dependency install had errors: {dep_result.stderr[:300]}")
        else:
            # Modern Python projects declare runtime/dev dependencies in
            # pyproject.toml instead of requirements.txt. Install the project
            # itself plus its dev extras so pytest can import src-layout code
            # and API tests have FastAPI/httpx available.
            project_check = self._exec(["test", "-f", "pyproject.toml"], cwd=SANDBOX_WORKDIR)
            if project_check.returncode == 0:
                dep_result = self._exec(["pip", "install", "--quiet", "-e", ".[dev]"],
                                         cwd=SANDBOX_WORKDIR, timeout=300)
                if dep_result.returncode != 0:
                    print(f"[sandbox] WARNING: pyproject dependency install had errors: {dep_result.stderr[:300]}")

    def _exec(self, cmd: list, cwd: str = None, timeout: int = 60) -> subprocess.CompletedProcess:
        full_cmd = ["docker", "exec"]
        if cwd:
            full_cmd += ["-w", cwd]
        full_cmd += [self.container_name] + cmd
        return subprocess.run(full_cmd, capture_output=True, text=True, timeout=timeout)

    def run(self, cmd: list) -> str:
        """Run a command inside the sandbox's writable copy. Returns combined
        stdout+stderr. This never touches the real repo -- it only ever
        operates on the container's internal copy at SANDBOX_WORKDIR."""
        if not self._started:
            raise RuntimeError("Sandbox not started -- call start() first.")
        result = self._exec(cmd, cwd=SANDBOX_WORKDIR)
        return result.stdout + result.stderr

    def run_with_status(self, cmd: list) -> tuple:
        """Like run(), but also returns the real process exit code -- used
        wherever pass/fail needs to be determined reliably instead of by
        guessing from output text (e.g. checking if tests actually passed)."""
        if not self._started:
            raise RuntimeError("Sandbox not started -- call start() first.")
        result = self._exec(cmd, cwd=SANDBOX_WORKDIR)
        return result.stdout + result.stderr, result.returncode

    def read_file(self, relative_path: str) -> str:
        """Read a file from the sandbox's writable copy (not the real repo)."""
        try:
            relative_path = _safe_relative_path(relative_path)
        except ValueError as error:
            return f"Error reading file: {error}"
        result = self._exec(["cat", relative_path], cwd=SANDBOX_WORKDIR)
        if result.returncode != 0:
            return f"Error reading '{relative_path}': {result.stderr.strip()}"
        return result.stdout

    def copy_to_repo(self, relative_path: str) -> str:
        """Copy one reviewed file from the sandbox to the real Git worktree.

        This is intentionally a low-level operation: branch creation, Git
        staging, and committing are owned by ``promotion.py`` after a human
        approval.  Agents never call this method.
        """
        if not self._started:
            raise RuntimeError("Sandbox not started -- call start() first.")
        relative_path = _safe_relative_path(relative_path)
        src = f"{self.container_name}:{SANDBOX_WORKDIR}/{relative_path}"
        dst = os.path.join(self.repo_path, relative_path)
        result = subprocess.run(["docker", "cp", src, dst],
                                 capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return f"Error promoting '{relative_path}': {result.stderr.strip()}"
        return f"Copied '{relative_path}' to the real repo at {dst}"

    def changed_files(self, fallback_paths: list[str] | None = None) -> list[str]:
        """Return all tracked/untracked sandbox changes.

        A copied Git repository gives the most reliable answer, including
        untracked files.  The fallback preserves local non-Git demo support.
        """
        output, status = self.run_with_status(
            ["sh", "-c", "git diff --name-only && git ls-files --others --exclude-standard"]
        )
        if status == 0:
            transient_dirs = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
            paths = {line.strip() for line in output.splitlines() if line.strip()}
            return sorted(
                path for path in paths
                if not any(part in transient_dirs for part in path.replace("\\", "/").split("/"))
                and not path.endswith((".pyc", ".pyo"))
            )

        candidate_paths = fallback_paths or []
        changed = []
        for path in dict.fromkeys(candidate_paths):
            path = _safe_relative_path(path)
            result = self._exec(
                ["sh", "-c", f"cmp -s /repo_ro/{path} {SANDBOX_WORKDIR}/{path}"],
            )
            if result.returncode == 1:
                changed.append(path)
            elif result.returncode > 1:
                raise RuntimeError(f"Could not compare sandbox file: {path}")
        return changed

    def diff_files(self, candidate_paths: list[str]) -> str:
        """Return unified diffs for candidate patched files in the sandbox."""
        diffs = []
        for path in self.changed_files(candidate_paths):
            result = self._exec(
                ["diff", "-u", f"/repo_ro/{path}", f"{SANDBOX_WORKDIR}/{path}"],
            )
            if result.returncode not in (0, 1):
                raise RuntimeError(f"Could not create sandbox diff for {path}: {result.stderr.strip()}")
            diffs.append(result.stdout)
        return "\n".join(diffs) or "No sandbox changes detected."

    def stop(self):
        """Tear down the container. The real repo is untouched regardless of
        whether promote() was ever called."""
        if self._started:
            subprocess.run(["docker", "rm", "-f", self.container_name],
                            capture_output=True, text=True, timeout=30)
            self._started = False

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
