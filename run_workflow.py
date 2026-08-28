"""Run the full guarded bug-fix workflow.

Usage:
    python run_workflow.py ./records "the records library isn't behaving correctly"

The source repo stays unchanged until the final explicit promotion approval.
"""
from __future__ import annotations

import argparse
import os
import sys

from agents.workflow_graph import GuardedWorkflow


def ask_yes_no(prompt: str) -> bool:
    while True:
        answer = input(f"{prompt} [y/n]: ").strip().lower()
        if answer in {"y", "yes"}:
            return True
        if answer in {"n", "no"}:
            return False
        print("Please enter y or n.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the LangGraph guarded bug-fix workflow.")
    parser.add_argument("repo_path", nargs="?", help="Path to the repository to investigate")
    parser.add_argument("issue", nargs="?", help="Description of the reported problem")
    parser.add_argument("--branch", help="Git branch to create after final approval")
    parser.add_argument("--commit-message", help="Commit message for approved changes")
    parser.add_argument("--resume", metavar="THREAD_ID", help="Resume a paused workflow")
    parser.add_argument("--approve", choices=("y", "n"), help="Approval answer when resuming")
    parser.add_argument("--github", action="store_true", help="Offer an additional approval to push and create a draft GitHub PR")
    parser.add_argument("--history", metavar="RUN_ID", help="Show saved audit events for a workflow run")
    args = parser.parse_args()

    if args.history:
        from agents.history import RunHistory
        import json
        for event in RunHistory().list_events(args.history):
            print(json.dumps(event, indent=2))
        return 0
    if not args.resume and (not args.repo_path or not args.issue):
        parser.error("repo_path and issue are required unless --resume is used")
    repo_path = os.path.abspath(args.repo_path) if args.repo_path else ""
    if repo_path and not os.path.isdir(repo_path):
        print(f"Repository not found: {repo_path}", file=sys.stderr)
        return 2

    try:
        workflow = GuardedWorkflow(branch=args.branch, commit_message=args.commit_message, github_enabled=args.github)
        if args.resume:
            if not args.approve:
                parser.error("--resume requires --approve y or --approve n")
            result = workflow.resume(args.resume, args.approve == "y")
            thread_id = args.resume
        else:
            thread_id, result = workflow.start(repo_path, args.issue)
    except Exception as error:
        print(f"\nWorkflow failed: {error}", file=sys.stderr)
        return 1
    if "__interrupt__" in result:
        request = result["__interrupt__"][0].value
        print(f"\nWorkflow paused for {request['kind']}.")
        print(f"Thread ID: {thread_id}")
        print(request["prompt"])
        print(f"Resume with: python run_workflow.py --resume {thread_id} --approve y")
        return 0
    return 0 if result.get("status") in {"committed", "rejected"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
