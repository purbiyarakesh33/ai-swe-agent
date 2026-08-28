"""Fast tests for LangGraph routing and approval safety.

These tests mock the expensive model, Docker, and Git operations. They verify
the graph's control flow without touching the real ``records`` clone.
"""
from __future__ import annotations

from agents import workflow_graph as graph_module


class FakeSandbox:
    container_name = "fake-container"

    def stop(self):
        pass


def make_workflow(tmp_path, monkeypatch, *, issue_real=True, validation_passed=True):
    monkeypatch.setattr(
        graph_module,
        "investigate",
        lambda repo, issue: {
            "issue_real": issue_real,
            "investigation_notes": "REAL: confirmed in records.py",
            "clarification_notes": "",
        },
    )
    monkeypatch.setattr(graph_module, "create_plan", lambda repo, issue, evidence: "Change records.py")
    fake = FakeSandbox()
    monkeypatch.setattr(graph_module, "execute_plan", lambda repo, plan: (fake, {
        "agent_report": "patched records.py",
        "verified_test_output": "1 passed",
        "tests_passed": True,
        "patched_files": ["records.py"],
    }))
    monkeypatch.setattr(graph_module.Sandbox, "attach", lambda repo, name: fake)
    monkeypatch.setattr(graph_module, "validate_sandbox", lambda sandbox, files: {
        "passed": validation_passed,
        "checks": [],
        "diff": "- old\n+ new",
        "changed_files": files,
        "unexpected_files": [],
        "missing_patches": [],
    })
    monkeypatch.setattr(graph_module, "analyze_failure", lambda *args: "retry with corrected plan")
    return graph_module.GuardedWorkflow(
        checkpoint_db=str(tmp_path / "checkpoints.sqlite"),
        history_db=str(tmp_path / "history.sqlite"),
    )


def test_plan_rejection_stops_before_execution(tmp_path, monkeypatch):
    workflow = make_workflow(tmp_path, monkeypatch)
    thread_id, paused = workflow.start(str(tmp_path), "test issue")
    assert paused["__interrupt__"][0].value["kind"] == "plan_approval"

    result = workflow.resume(thread_id, False)
    assert result["status"] == "rejected"


def test_success_requires_two_approvals_and_commits(tmp_path, monkeypatch):
    workflow = make_workflow(tmp_path, monkeypatch)
    promoted = []
    monkeypatch.setattr(
        graph_module,
        "promote_validated_changes",
        lambda sandbox, repo, files, branch, message: promoted.append((files, branch)) or "committed",
    )

    thread_id, paused = workflow.start(str(tmp_path), "test issue")
    assert paused["__interrupt__"][0].value["kind"] == "plan_approval"

    paused = workflow.resume(thread_id, True)
    assert paused["__interrupt__"][0].value["kind"] == "promotion_approval"
    assert promoted == []

    result = workflow.resume(thread_id, True)
    assert result["status"] == "committed"
    assert promoted and promoted[0][0] == ["records.py"]


def test_validation_failure_routes_to_retry(tmp_path, monkeypatch):
    workflow = make_workflow(tmp_path, monkeypatch, validation_passed=False)
    thread_id, paused = workflow.start(str(tmp_path), "test issue")
    paused = workflow.resume(thread_id, True)
    # Failure analysis leads to a new planning approval interrupt.
    assert paused["__interrupt__"][0].value["kind"] == "plan_approval"


def test_unclear_issue_ends_without_approval(tmp_path, monkeypatch):
    workflow = make_workflow(tmp_path, monkeypatch, issue_real=False)
    _, result = workflow.start(str(tmp_path), "unclear issue")
    assert result["status"] == "unclear"
