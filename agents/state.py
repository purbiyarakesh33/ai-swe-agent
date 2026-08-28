"""Shared state passed between every node in the graph."""
from typing import TypedDict, Optional


class AttemptRecord(TypedDict):
    """One retry attempt's plan + outcome, kept so the planner has context."""
    attempt_number: int
    plan: str
    diff_applied: str
    test_output: str
    passed: bool


class AgentState(TypedDict):
    # inputs
    repo_path: str
    issue_description: str

    # understand / clarify
    issue_real: bool
    clarification_notes: str
    investigation_notes: str

    # plan / approve
    plan: str
    plan_approved: Optional[bool]

    # execute / validate
    diff: str
    test_output: str
    tests_passed: bool
    validation_report: str
    validation_passed: bool

    # retry / failure
    failure_analysis: str
    attempt_number: int
    max_attempts: int
    history: list[AttemptRecord]

    # commit
    commit_approved: Optional[bool]
    branch_name: str
    status: str  # "running" | "committed" | "escalated" | "rejected"
