"""Agent 4: analyzes a failed sandbox attempt and supplies evidence for a retry."""
from .agent_loop import run_agent_loop
from .tools import make_investigation_tools


SYSTEM_PROMPT = (
    "You are the Failure Analysis Agent in a bug-fixing workflow. A proposed "
    "fix was applied only in an isolated sandbox, and its test suite failed. "
    "Analyze the failure using the test output, the previous plan, and the real "
    "repository source. Do not edit files and do not propose a new patch.\n\n"
    "State the specific reason the previous plan failed, identify the relevant "
    "file and function, and list the evidence a Planning Agent needs to create "
    "a revised minimal plan. Never rely on a previous plan when the test output "
    "contradicts it."
)


def analyze_failure(
    repo_path: str,
    issue_description: str,
    previous_plan: str,
    test_output: str,
) -> str:
    """Return evidence for the next planning attempt; does not modify the repo."""
    all_tools = make_investigation_tools(repo_path)
    tools = [tool for tool in all_tools if tool.name in ("rag_tool", "read_file")]
    user_prompt = (
        f"Original issue:\n{issue_description}\n\n"
        f"Previous sandbox plan:\n{previous_plan}\n\n"
        f"Sandbox test failure:\n{test_output[-12000:]}\n\n"
        "Analyze why this attempt failed and provide evidence for a revised plan."
    )
    return run_agent_loop(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        tools=tools,
        max_turns=6,
    )
