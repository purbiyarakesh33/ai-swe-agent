"""Explicitly approved GitHub draft-PR creation via the GitHub CLI."""
from __future__ import annotations

import subprocess
import shutil
from pathlib import Path


def _gh_executable() -> str:
    """Find GitHub CLI even when its installer did not refresh PATH."""
    found = shutil.which("gh")
    if found:
        return found
    for candidate in (
        Path(r"C:\Program Files\GitHub CLI\gh.exe"),
        Path(r"C:\Program Files (x86)\GitHub CLI\gh.exe"),
    ):
        if candidate.is_file():
            return str(candidate)
    raise RuntimeError("GitHub CLI (gh.exe) was not found. Install GitHub CLI or add it to PATH.")


def create_draft_pr(repo_path: str, branch: str, issue: str, validation: dict) -> str:
    """Push the approved branch and open a draft PR using authenticated ``gh``."""
    push = subprocess.run(
        ["git", "-C", repo_path, "push", "-u", "origin", branch],
        capture_output=True, text=True, timeout=120,
    )
    if push.returncode != 0:
        raise RuntimeError(f"Git push failed: {push.stderr.strip()}")
    body = (
        f"## Issue\n{issue}\n\n"
        "## Validation\n"
        f"{validation.get('diff', 'No diff recorded')}\n\n"
        "Automated tests and sandbox validation passed."
    )
    pr = subprocess.run(
        [_gh_executable(), "pr", "create", "--draft", "--title", f"Fix: {issue}", "--body", body],
        cwd=repo_path, capture_output=True, text=True, timeout=120,
    )
    if pr.returncode != 0:
        raise RuntimeError(f"Draft PR creation failed: {pr.stderr.strip()}")
    return pr.stdout.strip()
