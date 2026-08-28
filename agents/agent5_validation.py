"""Agent 5: deterministic validation of an execution sandbox.

This is deliberately not LLM-driven.  Validation is a guardrail, so pass/fail
comes from command exit codes and the actual sandbox diff, not a model claim.
"""
from __future__ import annotations

from typing import Any


def _optional_check(sandbox, executable: str, command: list[str]) -> dict[str, Any]:
    """Run a check only when its executable is installed in the sandbox."""
    _, available = sandbox.run_with_status(["sh", "-c", f"command -v {executable}"])
    if available != 0:
        return {"name": executable, "status": "skipped", "output": f"{executable} is not installed."}

    output, status = sandbox.run_with_status(command)
    return {
        "name": executable,
        "status": "passed" if status == 0 else "failed",
        "output": output,
    }


def validate_sandbox(sandbox, patched_files: list[str]) -> dict[str, Any]:
    """Validate the exact sandbox files proposed for promotion.

    The caller must keep the sandbox alive until it either promotes or discards
    the result.  ``patched_files`` comes from the patch tool's ground-truth
    record, not the execution agent's prose report.
    """
    unique_files = list(dict.fromkeys(patched_files))
    test_output, test_status = sandbox.run_with_status(["python3", "-m", "pytest", "-q"])
    checks = [
        {
            "name": "pytest",
            "status": "passed" if test_status == 0 else "failed",
            "output": test_output,
        },
        _optional_check(sandbox, "ruff", ["ruff", "check", "."]),
        _optional_check(sandbox, "mypy", ["mypy", "."]),
    ]
    diff = sandbox.diff_files(unique_files)
    changed_files = sandbox.changed_files(unique_files)
    unexpected_files = sorted(set(changed_files) - set(unique_files))
    missing_patches = sorted(set(unique_files) - set(changed_files))

    passed = (
        bool(unique_files)
        and test_status == 0
        and not unexpected_files
        and not missing_patches
        and all(check["status"] != "failed" for check in checks)
    )
    return {
        "passed": passed,
        "checks": checks,
        "diff": diff,
        "changed_files": changed_files,
        "unexpected_files": unexpected_files,
        "missing_patches": missing_patches,
    }
