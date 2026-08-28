"""Acquire repositories for local and deployed workflow runs."""
from __future__ import annotations

import subprocess
import uuid
from pathlib import Path
from urllib.parse import urlparse


def clone_github_repository(
    repository_url: str,
    *,
    branch: str = "",
    workspace_root: str | Path | None = None,
) -> str:
    """Clone a public GitHub repository into an isolated per-run directory."""
    url = repository_url.strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() != "github.com":
        raise ValueError("Enter an HTTPS GitHub repository URL, for example https://github.com/org/repo")
    if not parsed.path.strip("/") or parsed.query or parsed.fragment:
        raise ValueError("The GitHub repository URL is invalid.")

    root = Path(workspace_root or Path(__file__).resolve().parent.parent / ".workflow_repos")
    run_dir = root / str(uuid.uuid4())
    run_dir.parent.mkdir(parents=True, exist_ok=True)

    command = ["git", "clone", "--depth", "1"]
    if branch.strip():
        command.extend(["--branch", branch.strip()])
    command.extend([url, str(run_dir)])

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("Git is not installed on the workflow server.") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Cloning the repository timed out.") from exc

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(f"Could not clone the repository: {detail[-1000:]}")
    return str(run_dir)
