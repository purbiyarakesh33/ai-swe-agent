"""Agent 3: Execution Agent -- given a fix plan that a human has already
approved (the approve-plan HITL gate), applies it inside an isolated Docker
sandbox and checks it with tests. Trusts Agent 2's diagnosis completely --
that verification already happened at the human approval step before this
agent ever runs. Never touches the real repo itself; only sandbox.promote()
does that, called separately, only after you say yes."""
from .agent_loop import run_agent_loop
from .docker_sandbox import Sandbox
from .sandbox_tools import make_sandbox_tools

SYSTEM_PROMPT = (
    "You are the Execution Agent for a bug-fixing pipeline. You are given a "
    "fix plan that a human has already reviewed and approved. Your job is only "
    "to carry it out inside an isolated Docker sandbox.\n\n"
    "IMPORTANT SANDBOX RULES:\n"
    "1. All tool paths are relative to the sandbox repository root. For example, "
    "use 'records.py' or 'src/module.py'. NEVER use absolute Windows paths "
    "(such as C:\\\\Users\\\\...) or absolute Linux paths.\n"
    "2. The sandbox contains a writable copy of the repository at its root. "
    "Changes made with apply_patch never modify the real repository directly.\n"
    "3. Use read_file and list_files first to confirm the target file and exact "
    "existing code before editing.\n"
    "4. Use apply_patch to make EXACTLY the approved change. Make the smallest "
    "possible edit. Do not refactor, redesign, or modify test files.\n"
    "5. If apply_patch reports that old text was not found, reread the target "
    "file and retry once using a snippet copied exactly from that fresh output. "
    "Do not guess or make a different change.\n"
    "6. Always call run_tests after a successful patch.\n\n"
    "Your final_answer must state:\n"
    "- the repo-relative file changed\n"
    "- the exact edit made\n"
    "- the test result, including whether tests passed or failed\n"
    "- whether the change is ready for human approval to promote"
)


def execute_plan(repo_path: str, fix_plan: str):
    """Runs Agent 3 inside a fresh sandbox. Returns (sandbox, result).

    result contains the agent's own report PLUS an independent, deterministic
    re-check that does not trust the agent's claim: we run the tests
    ourselves, one more time, using the sandbox's real exit code.

    The sandbox is left RUNNING on success so you can inspect it or call
    sandbox.promote(path) yourself if you approve. YOU must call
    sandbox.stop() when done, whether you promote or not -- this function
    does not auto-close it. On any exception the sandbox is stopped
    automatically before the error propagates, so nothing leaks on failure.
    """
    sb = Sandbox(repo_path)
    try:
        # Keep startup inside the cleanup guard as well: dependency installs
        # can time out after the container has started.
        sb.start()
        tools = make_sandbox_tools(sb)

        report = run_agent_loop(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=f"Approved fix plan:\n{fix_plan}",
            tools=tools,
            max_turns=8,
            require_test_evidence=True,
        )

        # Ground truth, not the agent's word: run tests ourselves again and
        # read the real exit code.
        verify_output, verify_code = sb.run_with_status(["python3", "-m", "pytest", "-q"])
        tests_passed = (verify_code == 0)

        result = {
            "agent_report": report,
            "verified_test_output": verify_output,
            "tests_passed": tests_passed,
            "patched_files": list(sb.patched_files),
        }
        return sb, result
    except Exception:
        sb.stop()
        raise
