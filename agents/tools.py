"""Tools available to the agents. Used via our manual agent_loop -- not native
tool_calls, which is a confirmed broken path for qwen2.5-coder via Ollama."""
import os
import re
import base64

from langchain_core.tools import tool

from .retrieval import get_relevant_chunks
from .llm import get_llm


def make_investigation_tools(repo_path: str, sandbox=None):
    """Create read-only investigation tools.

    When ``sandbox`` is supplied, every command or generated repro runs in its
    disposable copy.  The real repository is therefore never dirtied by pytest
    caches, bytecode, package metadata, or LLM-generated repro code.
    """
    @tool
    def rag_tool(query: str) -> str:
        """Semantic search over the codebase for code relevant to a query. Returns file paths and code snippets."""
        chunks = get_relevant_chunks(repo_path, query, file_top_k=5, chunk_top_k=5)
        if not chunks:
            return "No relevant code found."
        return "\n\n".join(
            f"--- {c['file']} (line {c['start_line']}) ---\n{c['text']}"
            for c in chunks
        )

    @tool
    def read_file(path: str) -> str:
        """Read the full contents of a specific file, given its path."""
        for candidate in [path, os.path.join(repo_path, path)]:
            try:
                with open(candidate, "r", encoding="utf-8", errors="ignore") as f:
                    return f.read()
            except OSError:
                continue

        return (
            f"Error reading file: could not find '{path}'. "
            "Use the exact path shown by rag_tool or list_files."
        )

    @tool
    def list_files(directory: str = ".") -> str:
        """List files and folders in a directory of the repo, to browse structure when a search query isn't enough."""
        target = os.path.join(repo_path, directory)

        try:
            entries = os.listdir(target)
        except OSError as e:
            try:
                root_entries = sorted(os.listdir(repo_path))
            except OSError:
                root_entries = []

            return (
                f"Error listing '{directory}': {e}. Use '.' for the repo root. "
                f"Repo root actually contains: {root_entries}"
            )

        entries = [
            e
            for e in entries
            if e not in (
                ".git",
                "__pycache__",
                "venv",
                ".venv",
                "node_modules",
            )
        ]

        return "\n".join(sorted(entries)) if entries else "(empty)"

    @tool
    def run_tests() -> str:
        """Run the repo's test suite inside the disposable sandbox copy."""
        if sandbox is None:
            return "TEST_ERROR: an investigation sandbox is required to run tests safely."
        output, status = sandbox.run_with_status(["python3", "-m", "pytest", "-q"])
        label = "TESTS_PASSED" if status == 0 else "TESTS_FAILED"
        return f"{label}\n{output}"

    @tool
    def write_and_run_repro(file_path: str, issue_description: str) -> str:
        """When no existing test covers the issue, write and run a small script
        to check if the described problem actually occurs in the given file."""
        if sandbox is None:
            return "REPRO_ERROR: an investigation sandbox is required to run repro code safely."

        try:
            candidate_path = file_path if os.path.isabs(file_path) else os.path.join(repo_path, file_path)
            relative_path = os.path.relpath(os.path.abspath(candidate_path), repo_path)
            if relative_path == ".." or relative_path.startswith(f"..{os.sep}"):
                return "REPRO_ERROR: file path must stay inside the repository."
            with open(os.path.join(repo_path, relative_path), "r", encoding="utf-8", errors="ignore") as f:
                source = f.read()
        except OSError as error:
            return f"Error reading file: {error}"

        module_name = os.path.splitext(os.path.basename(file_path))[0]

        prompt = (
            f"Issue reported: {issue_description}\n\n"
            f"File: {file_path}\n{source}\n\n"
            "Write a short standalone Python script that reproduces the issue. "
            "The script will run from the repository root with PYTHONPATH set to "
            "'.:src:tests'. If the supplied file is under tests/, do not import it "
            "as a top-level module; import the real application package under src "
            "instead (for example, 'from task_manager.service import TaskService'). "
            "If the supplied file is under src/, use its full package import path "
            "rather than a top-level import. "
            "Call the relevant function(s) with sample input to check if the reported "
            "problem occurs. Print the result clearly. Output only the code."
        )

        repro_script = get_llm().invoke(prompt).content
        repro_script = re.sub(
            r"^```(?:python)?\n?|```$",
            "",
            repro_script.strip(),
            flags=re.MULTILINE,
        )

        encoded = base64.b64encode(repro_script.encode("utf-8")).decode("ascii")
        write_script = (
            "import base64; "
            f"open('/tmp/_agent_repro.py', 'wb').write(base64.b64decode('{encoded}'))"
        )
        write_output, write_status = sandbox.run_with_status(["python3", "-c", write_script])
        if write_status != 0:
            return f"REPRO_ERROR: could not stage repro script in sandbox.\n{write_output}"
        output, status = sandbox.run_with_status(
            ["sh", "-c", "PYTHONPATH=.:src:tests python3 /tmp/_agent_repro.py"]
        )
        label = "REPRO_PASSED" if status == 0 else "REPRO_FAILED"
        return f"{label}\n{output}"

    return [
        rag_tool,
        read_file,
        list_files,
        run_tests,
        write_and_run_repro,
    ]
