"""Agent 2: Planning Agent -- takes the confirmed issue and investigation
notes, digs into the specific code, and produces a precise fix plan."""
from .agent_loop import run_agent_loop
from .tools import make_investigation_tools

SYSTEM_PROMPT = (
    "You are the Planning Agent for a bug-fixing pipeline. You are given a "
    "confirmed real issue and prior investigation notes. Your job is to produce "
    "a precise fix plan. Use read_file and rag_tool to examine the exact code "
    "involved -- do not guess without looking at the real source.\n\n"
    "RULES:\n"
    "1. Propose the SMALLEST possible change that fixes the ROOT CAUSE identified "
    "in the investigation notes and evidence. Do not rewrite, refactor, or "
    "redesign the function beyond what the evidence justifies. Before finalizing, "
    "verify your proposed fix would actually resolve the specific failure "
    "described in the evidence -- not just a plausible-sounding nearby change.\n"
    "2. NEVER modify test files (test_*.py or files in a tests/ folder). Tests "
    "define correct behavior -- if a test fails, the bug is in the implementation.\n"
    "3. If the evidence describes a NameError or undefined reference, do NOT assume "
    "a brand new function or variable needs to be written. An undefined name is "
    "very often a mistaken substitution for something that already exists -- check "
    "the rest of the file first (other methods in the same class, nearby lines, "
    "Python builtins). If something already there serves the same purpose (e.g. "
    "len(self) is already used elsewhere in the file for a similar check), that is "
    "almost certainly what was intended, not a new function to create.\n\n"
    "Your final_answer must state: the exact file, the exact function, the exact "
    "line or code snippet that's wrong, and what it should become."
)

def create_plan(repo_path: str, issue_description: str, investigation_notes: str) -> str:
    all_tools = make_investigation_tools(repo_path)
    tools = [t for t in all_tools if t.name in ("rag_tool", "read_file")]
    user_prompt = (
        f"Issue: {issue_description}\n\n"
        f"Investigation findings: {investigation_notes}\n\n"
        "Investigate the specific code and produce a fix plan."
    )
    return run_agent_loop(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        tools=tools,
        max_turns=8,
        require_grounded_file=True,
    )
