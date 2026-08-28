"""LangGraph orchestration for the guarded bug-fix workflow."""
from __future__ import annotations

import sqlite3
import uuid
from typing import TypedDict
from langgraph.graph import END, START, StateGraph
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command, interrupt

from .agent1_understanding import investigate
from .agent2_planning import create_plan
from .agent3_execution import execute_plan
from .agent4_failure_analysis import analyze_failure
from .agent5_validation import validate_sandbox
from .agent_loop import MAX_TURNS_FAILURE
from .promotion import default_branch_name, promote_validated_changes
from .docker_sandbox import Sandbox
from .history import RunHistory
from .github_pr import create_draft_pr


class WorkflowState(TypedDict, total=False):
    repo_path: str
    issue: str
    evidence: str
    plan: str
    attempt: int
    max_attempts: int
    sandbox_container: str
    execution: dict
    validation: dict
    status: str
    branch_name: str
    run_id: str
    github_enabled: bool


class GuardedWorkflow:
    """StateGraph with explicit routes and two human approval gates."""

    def __init__(self, checkpoint_db: str = "workflow_checkpoints.sqlite", history_db: str = "workflow_history.sqlite", branch: str | None = None, commit_message: str | None = None, github_enabled: bool = False):
        self.branch, self.commit_message = branch, commit_message
        self.github_enabled = github_enabled
        self.history = RunHistory(history_db)
        self.connection = sqlite3.connect(checkpoint_db, check_same_thread=False)
        self.checkpointer = SqliteSaver(self.connection)
        self.checkpointer.setup()
        graph = StateGraph(WorkflowState)
        graph.add_node("understand", self.understand)
        graph.add_node("plan", self.plan)
        graph.add_node("approve_plan", self.approve_plan)
        graph.add_node("execute", self.execute)
        graph.add_node("validate", self.validate)
        graph.add_node("failure", self.failure)
        graph.add_node("promote", self.promote)
        graph.add_node("github", self.github)
        graph.add_edge(START, "understand")
        graph.add_conditional_edges("understand", self.after_understand, {"plan": "plan", "end": END})
        graph.add_conditional_edges("plan", self.after_plan, {"approve": "approve_plan", "end": END})
        graph.add_conditional_edges("approve_plan", lambda s: "execute" if s["status"] == "running" else "end", {"execute": "execute", "end": END})
        graph.add_edge("execute", "validate")
        graph.add_conditional_edges("validate", self.after_validate, {"promote": "promote", "failure": "failure", "end": END})
        graph.add_edge("failure", "plan")
        graph.add_conditional_edges("promote", lambda s: "github" if s.get("github_enabled") and s.get("status") == "committed" else "end", {"github": "github", "end": END})
        graph.add_edge("github", END)
        self.graph = graph.compile(checkpointer=self.checkpointer)

    def understand(self, s):
        self.log(s, "understanding_started")
        print("\n=== 1. Understanding & verification (sandbox) ===")
        result = investigate(s["repo_path"], s["issue"])
        print(result["investigation_notes"])
        self.log(s, "understanding_completed", {"issue_real": result["issue_real"]})
        return {"evidence": result["investigation_notes"], "status": "running" if result["issue_real"] else "unclear"}

    def after_understand(self, s):
        return "plan" if s["status"] == "running" else "end"

    def plan(self, s):
        print(f"\n=== 2. Plan (attempt {s['attempt']}/{s['max_attempts']}) ===")
        plan = create_plan(s["repo_path"], s["issue"], s["evidence"])
        print(plan)
        self.log(s, "plan_created", {"attempt": s["attempt"], "plan": plan})
        return {"plan": plan, "status": "running" if plan != MAX_TURNS_FAILURE else "failed"}

    def after_plan(self, s):
        return "approve" if s["status"] == "running" else "end"

    def approve_plan(self, s):
        approved = interrupt({"kind": "plan_approval", "prompt": "Approve this plan for isolated sandbox execution?", "plan": s["plan"]})
        if approved:
            self.log(s, "plan_approved")
            return {"status": "running"}
        print("Plan rejected. The repository was not modified.")
        self.log(s, "plan_rejected")
        return {"status": "rejected"}

    def execute(self, s):
        print("\n=== 3. Execute (sandbox only) ===")
        sandbox, result = execute_plan(s["repo_path"], s["plan"])
        print(result["agent_report"])
        print("\n=== Independent test verification ===")
        print(result["verified_test_output"])
        return {"sandbox_container": sandbox.container_name, "execution": result}

    def validate(self, s):
        result = s["execution"]
        if not result["tests_passed"] or not result["patched_files"]:
            return {"validation": {"passed": False, "evidence": result["verified_test_output"]}}
        print("\n=== 5. Independent validation (sandbox only) ===")
        report = validate_sandbox(self.sandbox(s), result["patched_files"])
        for check in report["checks"]:
            print(f"{check['name']}: {check['status']}")
        print("\n=== Proposed diff ===")
        print(report["diff"])
        self.log(s, "validation_completed", {"passed": report["passed"], "changed_files": report["changed_files"]})
        return {"validation": report}

    def after_validate(self, s):
        if s["validation"]["passed"]:
            return "promote"
        self.stop(s)
        return "failure" if s["attempt"] < s["max_attempts"] else "end"

    def failure(self, s):
        print("\n=== 4. Failure analysis ===")
        analysis = analyze_failure(s["repo_path"], s["issue"], s["plan"], str(s["validation"]))
        print(analysis)
        self.log(s, "failure_analyzed", {"analysis": analysis})
        return {"attempt": s["attempt"] + 1, "evidence": f"Previous plan:\n{s['plan']}\n\nFailure analysis:\n{analysis}", "sandbox_container": ""}

    def promote(self, s):
        sandbox = self.sandbox(s)
        branch = self.branch or default_branch_name(s["issue"])
        # Do not put sandbox.stop() in a finally block here.  ``interrupt``
        # raises a graph pause exception on the first visit; finally would
        # destroy the container before a later process can resume and promote.
        approved = interrupt({"kind": "promotion_approval", "prompt": f"Create Git branch '{branch}', copy these validated changes, and commit them?", "branch": branch, "diff": s["validation"]["diff"]})
        if not approved:
            print("Changes rejected. The repository was not modified.")
            self.log(s, "promotion_rejected")
            sandbox.stop()
            return {"status": "rejected"}
        message = self.commit_message or f"Fix: {s['issue']}"
        print(promote_validated_changes(sandbox, s["repo_path"], s["validation"]["changed_files"], branch, message))
        print("\nWorkflow complete.")
        self.log(s, "commit_created", {"branch": branch})
        sandbox.stop()
        return {"status": "committed", "branch_name": branch}

    def github(self, s):
        branch = s.get("branch_name") or self.branch
        approved = interrupt({"kind": "github_pr_approval", "prompt": f"Push branch '{branch}' and create a draft GitHub PR?", "branch": branch})
        if not approved:
            self.log(s, "github_pr_rejected")
            print("GitHub PR rejected. The local commit remains available.")
            return {"status": "committed"}
        result = create_draft_pr(s["repo_path"], branch, s["issue"], s["validation"])
        self.log(s, "github_pr_created", {"result": result})
        print(result)
        return {"status": "pr_created"}

    def log(self, s, event, details=None):
        if s.get("run_id"):
            self.history.record(s["run_id"], event, details)

    @staticmethod
    def sandbox(s):
        return Sandbox.attach(s["repo_path"], s["sandbox_container"])

    def stop(self, s):
        if s.get("sandbox_container"):
            self.sandbox(s).stop()

    def start(self, repo_path: str, issue: str, thread_id: str | None = None):
        thread_id = thread_id or str(uuid.uuid4())
        result = self.graph.invoke({"repo_path": repo_path, "issue": issue, "evidence": "", "plan": "", "attempt": 1, "max_attempts": 3, "status": "running", "run_id": thread_id, "github_enabled": self.github_enabled}, {"configurable": {"thread_id": thread_id}})
        return thread_id, result

    def resume(self, thread_id: str, approved: bool):
        return self.graph.invoke(Command(resume=approved), {"configurable": {"thread_id": thread_id}})


    
if __name__ == "__main__":
    workflow = GuardedWorkflow()

    # Mermaid text
    print(workflow.graph.get_graph().draw_mermaid())

    # PNG diagram
    png = workflow.graph.get_graph().draw_mermaid_png()
    with open("workflow_graph.png", "wb") as file:
        file.write(png)

    print("Saved workflow_graph.png")
