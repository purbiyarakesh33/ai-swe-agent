"""Human-approved promotion of validated sandbox changes into Git.

No LLM agent imports this module.  It is called only by the CLI after the
human accepts the final validation report.
"""
from __future__ import annotations

import re
import subprocess
from datetime import datetime


def default_branch_name(issue: str) -> str:
    """Create a safe, collision-resistant branch name from the issue text."""
    slug = re.sub(r"[^a-z0-9]+", "-", issue.lower()).strip("-")[:48] or "issue"
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"agent/fix-{slug}-{timestamp}"


def _git(repo_path: str, args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", repo_path, *args], capture_output=True, text=True, timeout=60
    )


def _require_clean_git_repository(repo_path: str) -> None:
    root = _git(repo_path, ["rev-parse", "--show-toplevel"])
    if root.returncode != 0:
        raise RuntimeError("Promotion requires repo_path to be a Git repository.")
    if root.stdout.strip().replace("\\", "/").lower() != repo_path.replace("\\", "/").lower():
        raise RuntimeError("For safe promotion, repo_path must be the Git repository root.")
    status = _git(repo_path, ["status", "--porcelain"])
    if status.returncode != 0:
        raise RuntimeError(f"Could not inspect Git status: {status.stderr.strip()}")
    meaningful_changes = [
        line for line in status.stdout.splitlines() if not _is_transient_untracked_file(line)
    ]
    if meaningful_changes:
        raise RuntimeError("Promotion requires a clean working tree; commit or stash existing changes first.")


def _is_transient_untracked_file(status_line: str) -> bool:
    """Ignore harmless test artifacts, but never hide tracked source changes."""
    if not status_line.startswith("?? "):
        return False
    path = status_line[3:].replace("\\", "/")
    transient_dirs = ("__pycache__/", ".pytest_cache/", ".mypy_cache/", ".ruff_cache/")
    return (
        path.startswith(transient_dirs)
        or "/__pycache__/" in path
        or path.endswith((".pyc", ".pyo"))
        or path.endswith(".egg-info/")
    )


def promote_validated_changes(sandbox, repo_path: str, files: list[str], branch_name: str, commit_message: str) -> str:
    """Create a branch, copy validated files from the sandbox, and commit them.

    A failure after branch creation is reported without an automatic reset, so
    no user work is silently lost and the resulting state remains inspectable.
    """
    _require_clean_git_repository(repo_path)
    unique_files = list(dict.fromkeys(files))
    if not unique_files:
        raise RuntimeError("No validated files are available for promotion.")

    exists = _git(repo_path, ["show-ref", "--verify", "--quiet", f"refs/heads/{branch_name}"])
    if exists.returncode == 0:
        raise RuntimeError(f"Branch already exists: {branch_name}")

    created = _git(repo_path, ["switch", "-c", branch_name])
    if created.returncode != 0:
        raise RuntimeError(f"Could not create branch: {created.stderr.strip()}")

    for path in unique_files:
        result = sandbox.copy_to_repo(path)
        if result.startswith("Error"):
            raise RuntimeError(result)

    diff_check = _git(repo_path, ["diff", "--check"])
    if diff_check.returncode != 0:
        raise RuntimeError(f"Whitespace validation failed:\n{diff_check.stdout}{diff_check.stderr}")
    staged = _git(repo_path, ["add", "--", *unique_files])
    if staged.returncode != 0:
        raise RuntimeError(f"Could not stage validated files: {staged.stderr.strip()}")
    committed = _git(repo_path, ["commit", "-m", commit_message])
    if committed.returncode != 0:
        raise RuntimeError(
            "Could not create commit. The new branch and staged files were left in place for review:\n"
            f"{committed.stderr.strip()}"
        )
    return f"Created branch '{branch_name}' and committed validated changes.\n{committed.stdout.strip()}"
