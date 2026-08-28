"""Tools for Agent 3 (Execution) -- all operate on a Sandbox's writable copy,
never the real repo. Mirrors tools.py's investigation tools but routed
through Docker exec instead of direct filesystem access, plus the new
apply_patch tool for making the actual fix."""
import base64
from langchain_core.tools import tool
from .docker_sandbox import _safe_relative_path


def make_sandbox_tools(sandbox):
    @tool
    def read_file(path: str) -> str:
        """Read a file's contents from the sandbox's working copy."""
        return sandbox.read_file(path)

    @tool
    def list_files(directory: str = ".") -> str:
        """List files in a directory of the sandbox's working copy."""
        return sandbox.run(["ls", "-a", directory])

    @tool
    def run_tests() -> str:
        """Run the test suite inside the sandbox's working copy (isolated
        from the real repo -- safe to run against a patched file)."""
        output, code = sandbox.run_with_status(["python3", "-m", "pytest", "-q"])
        status = "TESTS_PASSED" if code == 0 else "TESTS_FAILED"
        return f"{status}\n{output}"

    @tool
    def apply_patch(path: str, old_str: str, new_str: str) -> str:
        """Replace old_str with new_str in a file inside the sandbox. Fails
        and makes NO change if old_str isn't found in the file exactly once --
        refuses to guess which occurrence you meant. Only ever touches the
        sandbox's copy, never the real repo."""
        try:
            path = _safe_relative_path(path)
        except ValueError as error:
            return f"PATCH_ERROR: {error}"

        def b64(s: str) -> str:
            return base64.b64encode(s.encode()).decode()

        script = (
            "import base64, sys\n"
            f"path = base64.b64decode('{b64(path)}').decode()\n"
            f"old = base64.b64decode('{b64(old_str)}').decode()\n"
            f"new = base64.b64decode('{b64(new_str)}').decode()\n"
            # newline='' preserves the file's existing CRLF/LF bytes. Without
            # it, Python normalizes CRLF to LF and a one-line patch appears as
            # an unrelated whole-file diff on Windows repositories.
            "content = open(path, 'r', encoding='utf-8', newline='').read()\n"
            "count = content.count(old)\n"
            "if count == 0:\n"
            "    # Models commonly emit LF snippets even when the checkout uses\n"
            "    # CRLF. Normalize only for matching, then restore the file's\n"
            "    # original newline style so the diff stays minimal.\n"
            "    def normalize_newlines(value):\n"
            "        return value.replace('\\r\\n', '\\n').replace('\\r', '\\n')\n"
            "    normalized_content = normalize_newlines(content)\n"
            "    normalized_old = normalize_newlines(old)\n"
            "    normalized_new = normalize_newlines(new)\n"
            "    normalized_count = normalized_content.count(normalized_old)\n"
            "    if normalized_count == 1:\n"
            "        replaced = normalized_content.replace(normalized_old, normalized_new)\n"
            "        if '\\r\\n' in content:\n"
            "            replaced = replaced.replace('\\n', '\\r\\n')\n"
            "        open(path, 'w', encoding='utf-8', newline='').write(replaced)\n"
            "        print('PATCH_OK: replaced 1 occurrence in ' + path + ' (normalized line endings)')\n"
            "        sys.exit(0)\n"
            "    print('PATCH_ERROR: old_str not found in file'); sys.exit(1)\n"
            "elif count > 1:\n"
            "    print(f'PATCH_ERROR: old_str found {count} times -- not unique, refusing'); sys.exit(1)\n"
            "else:\n"
            "    open(path, 'w', encoding='utf-8', newline='').write(content.replace(old, new))\n"
            "    print('PATCH_OK: replaced 1 occurrence in ' + path)\n"
        )
        output, code = sandbox.run_with_status(["python3", "-c", script])
        if code == 0:
            sandbox.patched_files.append(path)
        return output

    return [read_file, list_files, run_tests, apply_patch]
