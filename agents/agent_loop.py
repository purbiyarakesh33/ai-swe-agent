"""Manual tool-calling loop -- the model outputs its chosen action as JSON
text; we parse and execute it ourselves, since native tool_calls parsing
is a confirmed broken path for qwen2.5-coder via Ollama."""
import json
import os
import re
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from .llm import get_llm


MAX_TURNS_FAILURE = "Max turns reached without a final answer."


def run_agent_loop(system_prompt: str, user_prompt: str, tools: list, max_turns: int = 8,
                    require_grounded_file: bool = False, require_test_evidence: bool = False) -> str:
    tool_map = {t.name: t for t in tools}
    tools_desc = "\n".join(f"- {t.name}{t.args}: {t.description}" for t in tools)

    full_system = (
        f"{system_prompt}\n\nAvailable tools (with exact argument names):\n{tools_desc}\n\n"
        'To use a tool, respond with ONLY this JSON: {"tool": "<name>", "args": {...}} '
        "using the EXACT argument names shown above.\n"
        'When you have your final answer, respond with ONLY: {"final_answer": "<answer>"}'
    )

    llm = get_llm()
    messages = [SystemMessage(content=full_system), HumanMessage(content=user_prompt)]
    recent_calls = []
    WINDOW = 4
    read_files = set()   # basenames actually opened via a real read_file call
    rag_files = set()    # basenames merely surfaced by rag_tool search
    TEST_TOOLS = {"run_tests", "write_and_run_repro"}
    ran_tests = False  # whether a real test/repro tool call was made
    conclusive_evidence = False  # a repro explicitly confirmed the reported bug
    MIN_ANSWER_WORDS = 15  # a real file+function+line+fix can't be shorter than this

    for turn in range(max_turns):
        response = llm.invoke(messages)
        text = re.sub(r"^```(?:json)?\n?|```$", "", response.content.strip(), flags=re.MULTILINE).strip()

        parsed = _extract_json(text)
        if parsed is None:
            print(f"[turn {turn+1}] BAD JSON: {text}")
            messages.append(AIMessage(content=response.content))
            messages.append(HumanMessage(content="Respond with valid JSON only."))
            continue

        if "final_answer" in parsed:
            answer = parsed["final_answer"]

            if isinstance(answer, dict):
                answer = "\n".join(f"{key}: {value}" for key, value in answer.items())
            elif not isinstance(answer, str):
                answer = str(answer)

            if require_grounded_file and not _mentions_grounded_file(answer, read_files):
                # print(f"[turn {turn+1}] UNGROUNDED FINAL ANSWER -- rejecting")
                print(
                    f"[turn {turn+1}] UNGROUNDED FINAL ANSWER -- rejecting\n"
                    f"Answer received: {answer}\n"
                    f"Files read: {sorted(read_files)}"
                )
                messages.append(AIMessage(content=response.content))
                messages.append(HumanMessage(content=(
                    "Your final_answer doesn't reference a file you actually opened with "
                    f"read_file. rag_tool search results (seen so far: {sorted(rag_files) or 'none'}) "
                    "are not enough for an exact line-level fix -- they're only snippets. "
                    f"Files actually read in full: {sorted(read_files) or 'none'}. "
                    "Call read_file on the specific file before naming an exact line, "
                    "and name that exact file in your final_answer."
                )))
                continue

            # if require_grounded_file and len(answer.split()) < MIN_ANSWER_WORDS:
            #     print(f"[turn {turn+1}] ANSWER TOO THIN -- rejecting")
            #     messages.append(AIMessage(content=response.content))
            #     messages.append(HumanMessage(content=(
            #         "Your final_answer is too short to be a real fix. Do NOT call "
            #         "read_file again -- use the file content already shown to you "
            #         "earlier in this conversation, scroll back and reread it. Fill in "
            #         "this exact template with real specifics from that content:\n"
            #         "\"In <exact file path>, in function <exact function name>, the "
            #         "line '<exact wrong line copied from the code>' should become "
            #         "'<exact corrected line>'.\""
            #     )))
            #     continue

            if require_test_evidence and not ran_tests:
                print(f"[turn {turn+1}] NO TEST EVIDENCE -- rejecting")
                messages.append(AIMessage(content=response.content))
                messages.append(HumanMessage(content=(
                    "You haven't called run_tests or write_and_run_repro yet. "
                    "Reading code alone isn't enough evidence -- run the tests (or "
                    "write a repro if none exist) and quote the actual error/failure "
                    "output in your final_answer before concluding."
                )))
                continue

            print(f"[turn {turn+1}] FINAL ANSWER")
            return answer

        if "tool" in parsed:
            tool_name = parsed["tool"]
            args = parsed.get("args", {})

            if conclusive_evidence:
                # A deterministic repro has already confirmed the issue. Do
                # not let the model burn remaining turns exploring or mutate
                # anything else; it must now summarize grounded evidence.
                messages.append(AIMessage(content=response.content))
                messages.append(HumanMessage(content=(
                    "The repro output already contains conclusive evidence. Do not call "
                    "another tool. Respond now with the required final_answer, naming "
                    "the file and root cause using the evidence already collected."
                )))
                continue
            call_signature = (tool_name, json.dumps(args, sort_keys=True))
            print(f"[turn {turn+1}] TOOL: {tool_name}({args})")

            occurrences = recent_calls.count(call_signature)
            recent_calls.append(call_signature)
            recent_calls = recent_calls[-WINDOW:]

            if occurrences >= 1:
                print(f"[turn {turn+1}] REPEATED CALL -- forcing final answer")
                messages.append(AIMessage(content=response.content))
                messages.append(HumanMessage(content=(
                    "You already made this exact call earlier in this conversation -- "
                    "scroll back, the result is still there and hasn't changed. Do not "
                    "call it again. Use what you already have to give your best "
                    "final_answer now."
                )))
                continue

            if tool_name not in tool_map:
                result = f"Unknown tool: {tool_name}. Available: {list(tool_map.keys())}"
            else:
                try:
                    result = tool_map[tool_name].invoke(args)
                    if tool_name == "read_file" and "path" in args and not str(result).startswith("Error"):
                        read_files.add(os.path.basename(args["path"]))
                    elif tool_name == "rag_tool":
                        rag_files.update(_extract_files_from_rag_result(str(result)))
                    if tool_name in TEST_TOOLS:
                        ran_tests = True
                        if "BUG CONFIRMED" in str(result).upper():
                            conclusive_evidence = True
                except Exception as e:
                    result = f"Error calling {tool_name} with args {args}: {e}. Check argument names and try again."
            print(f"[turn {turn+1}] RESULT: {str(result)[:300]}")
            messages.append(AIMessage(content=response.content))
            messages.append(HumanMessage(content=f"Tool result:\n{result}"))
            continue

        print(f"[turn {turn+1}] UNEXPECTED FORMAT, treating as final: {text[:150]}")
        return text

    return MAX_TURNS_FAILURE


def _extract_json(text: str):
    """Find and parse the first balanced {...} object in the text that matches
    one of our expected schemas ('tool' or 'final_answer' key). Skips incidental
    braces -- e.g. from an embedded code snippet, a format string like
    '{}'.format(...), or braces sitting inside the JSON's own string values --
    and tolerates leading/trailing reasoning prose the model adds despite being
    told not to."""
    search_from = 0
    while True:
        start = text.find("{", search_from)
        if start == -1:
            break
        end = _find_matching_brace(text, start)
        if end is None:
            break
        try:
            parsed = json.loads(text[start:end + 1])
            if isinstance(parsed, dict) and ("tool" in parsed or "final_answer" in parsed):
                return parsed
        except json.JSONDecodeError:
            pass
        search_from = start + 1  # this brace group didn't match -- keep looking

    # Strict parsing found nothing. Lenient fallback for final_answer ONLY --
    # models often fail to escape inner double-quotes when the answer quotes
    # code that itself uses double quotes (e.g. a Python format string), which
    # produces genuinely invalid JSON no amount of brace-matching can parse.
    # Never applied to tool calls -- a bad tool call could act on wrong args,
    # but a recovered final_answer is just text handed back to the user.
    structured_plan = _extract_loose_structured_plan(text)
    if structured_plan is not None:
        return {"final_answer": structured_plan}

    match = re.search(r'"final_answer"\s*:\s*"(.*)"\s*\}', text, re.DOTALL)
    if match:
        return {"final_answer": match.group(1)}
    return None


def _find_matching_brace(text: str, start: int):
    """Find the index of the '}' matching the '{' at start, ignoring any
    brace characters that appear inside a JSON string value -- e.g. a quoted
    code snippet like '{}'.format(...) shouldn't count toward depth."""
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
    return None


def _mentions_grounded_file(answer: str, read_files: set) -> bool:
    """True if the final answer names at least one file actually opened via read_file."""
    if not read_files:
        return False
    return any(fname in answer for fname in read_files)


def _extract_loose_structured_plan(text: str) -> dict | None:
    """Recover Agent 2's predictable plan shape when a local model emits
    literal newlines or code quotes inside JSON strings. This is intentionally
    limited to a final plan; tool calls remain strict JSON to keep them safe."""
    pattern = (
        r'"final_answer"\s*:\s*\{\s*'
        r'"file"\s*:\s*"(?P<file>.*?)"\s*,\s*'
        r'"function"\s*:\s*"(?P<function>.*?)"\s*,\s*'
        r'"old_code"\s*:\s*"(?P<old_code>.*?)"\s*,\s*'
        r'"new_code"\s*:\s*"(?P<new_code>.*?)"\s*,\s*'
        r'"reason"\s*:\s*"(?P<reason>.*?)"\s*\}\s*\}'
    )
    match = re.search(pattern, text, re.DOTALL)
    if not match:
        return None
    return {
        key: value.replace(r"\n", "\n").replace(r"\t", "\t").replace(r'\"', '"')
        for key, value in match.groupdict().items()
    }


def _extract_files_from_rag_result(result: str) -> set:
    """rag_tool formats results as '--- <file> (line N) ---', so pull the paths back out."""
    return {os.path.basename(m) for m in re.findall(r"--- (.+?) \(line \d+\) ---", result)}
