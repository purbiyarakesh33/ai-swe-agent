"""Agent 1: Understanding & Verification Agent -- investigates a reported
issue using tools it chooses itself, decides if it's real and reproducible."""
from .agent_loop import run_agent_loop
from .docker_sandbox import Sandbox
from .tools import make_investigation_tools

SYSTEM_PROMPT = (
    "You are the Understanding & Verification Agent for a bug-fixing pipeline. "
    "Given a reported issue, investigate the codebase to determine if it's real "
    "and reproducible. Use rag_tool to find relevant files, read_file to examine "
    "them, list_files to browse structure if needed, and run_tests to check the "
    "existing test suite. For rag_tool, pass a plain string only: the args must "
    "be exactly {\"query\": \"your search text\"}, never a nested object. "
    "Prefer existing tests: call write_and_run_repro only "
    "if no existing test covers the issue, and pass it an actual source file path "
    "that was returned by rag_tool or opened with read_file. Never invent a test "
    "filename such as test_filtering_bug.py. "
    "You MUST call run_tests before concluding, and your final_answer must quote "
    "the exact error message from the traceback, not a paraphrase or guess. "
    "As soon as a test failure gives you a clear, specific error (exception type "
    "and the exact undefined name, wrong value, or line involved), STOP investigating "
    "and give your final_answer immediately -- do not keep exploring once you have "
    "conclusive evidence. Your final_answer MUST start with either 'REAL:' followed "
    "by a one-sentence summary of the confirmed problem, or 'UNCLEAR:' followed by "
    "what additional information is needed."
)

def investigate(repo_path: str, issue_description: str) -> dict:
    # Agent 1 may run tests or LLM-written repro code.  Keep both in a fresh
    # disposable copy so the eventual Git promotion starts from a clean clone.
    with Sandbox(repo_path) as sandbox:
        tools = make_investigation_tools(repo_path, sandbox=sandbox)
        verdict = run_agent_loop(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=f"Issue: {issue_description}",
            tools=tools,
        max_turns=14,
            require_test_evidence=True,
        )
    issue_real = verdict.strip().upper().startswith("REAL")
    return {
        "issue_real": issue_real,
        "clarification_notes": "" if issue_real else verdict,
        "investigation_notes": verdict,
    }
