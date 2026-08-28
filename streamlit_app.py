"""Small UI for the checkpointed LangGraph SWE workflow.

Run from the ``swe agent`` directory with:
    streamlit run streamlit_app.py
"""
from __future__ import annotations

import os
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import streamlit as st

from agents.repository_source import clone_github_repository


st.set_page_config(page_title="SWE Agent", page_icon="🛠️", layout="wide")

# Keep the interface light and readable when the app is shared publicly.  The
# default Streamlit theme follows the viewer's system preference, which made
# the previous UI appear almost black on many machines.
st.markdown(
    """
    <style>
    .stApp,
    [data-testid="stAppViewContainer"],
    [data-testid="stHeader"] {
        background: #ffffff;
    }

    .block-container {
        max-width: 1100px;
        padding-top: 2.5rem;
        padding-bottom: 3rem;
    }

    h1, h2, h3, h4, p, label,
    [data-testid="stCaptionContainer"] {
        color: #172033 !important;
    }

    [data-testid="stForm"] {
        background: #f8fafc;
        border: 1px solid #dbe3ef;
        border-radius: 12px;
        padding: 1.25rem;
    }

    .stTextInput input,
    .stTextArea textarea {
        background: #ffffff !important;
        color: #172033 !important;
        border: 1px solid #b8c5d6 !important;
        border-radius: 8px;
    }

    .stTextInput input:focus,
    .stTextArea textarea:focus {
        border-color: #2563eb !important;
        box-shadow: 0 0 0 1px #2563eb !important;
    }

    .stTextInput input::placeholder,
    .stTextArea textarea::placeholder {
        color: #64748b !important;
        opacity: 1 !important;
    }

    div.stButton > button {
        border: 1px solid #b8c5d6;
        border-radius: 8px;
        color: #172033;
        background: #ffffff;
    }

    div.stButton > button:hover {
        border-color: #2563eb;
        color: #1d4ed8;
    }

    div.stButton > button[kind="primary"],
    div.stButton > button[kind="primaryFormSubmit"] {
        border-color: #2563eb;
        color: #ffffff !important;
        background: #2563eb !important;
    }

    div.stButton > button[kind="primary"]:hover,
    div.stButton > button[kind="primaryFormSubmit"]:hover {
        border-color: #1d4ed8;
        background: #1d4ed8 !important;
    }

    [data-testid="stCode"] {
        border: 1px solid #dbe3ef;
        border-radius: 8px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)
st.title("AI Software Engineering Agent")
st.caption("Investigate → plan → sandbox fix → validate → approve → commit → draft PR")


MODEL_PROFILES = {
    "Local Ollama (requires local runner)": {
        "url_env": "OLLAMA_LOCAL_BASE_URL",
        "token_env": "OLLAMA_LOCAL_TOKEN",
        "model_env": "OLLAMA_LOCAL_MODEL",
        "default_url": "http://localhost:11434",
        "default_model": "qwen2.5-coder:7b",
        "requires_token": False,
    },
    "Kaggle GPU (owner-hosted 24B demo)": {
        "url_env": "OLLAMA_BASE_URL",
        "token_env": "OLLAMA_TOKEN",
        "model_env": "OLLAMA_MODEL",
        "default_url": "",
        "default_model": "devstral-small-2:24b-instruct-2512-q4_K_M",
        "requires_token": True,
    },
}

model_profile = st.selectbox(
    "Model backend",
    list(MODEL_PROFILES),
    help="Choose the model profile configured by the app owner. Visitors do not need to enter URLs, tokens, or model names.",
)
profile = MODEL_PROFILES[model_profile]
model_url = os.environ.get(profile["url_env"], profile["default_url"]).rstrip("/")
model_token = os.environ.get(profile["token_env"], "")
model_name = os.environ.get(profile["model_env"], profile["default_model"])
st.caption(f"Selected profile: {model_profile}")


@st.cache_data(ttl=15, show_spinner=False)
def check_llm_backend(base_url: str, token: str, requires_token: bool) -> tuple[str, str]:
    """Check the configured Ollama endpoint without exposing its URL or token."""
    if not base_url:
        return "Offline", "the selected Ollama URL is not configured"

    headers = {}
    if requires_token and not token:
        return "Offline", "the selected Ollama token is not configured"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(f"{base_url}/api/tags", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            if 200 <= response.status < 300:
                return "Online", "Ollama responded successfully"
            return "Offline", f"Ollama returned HTTP {response.status}"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return "Offline", f"The temporary model tunnel is unavailable ({type(exc).__name__})"


backend_status, backend_detail = check_llm_backend(model_url, model_token, profile["requires_token"])
if backend_status == "Online":
    st.success("LLM backend: Online")
else:
    st.warning(f"LLM backend: Offline — {backend_detail}")

st.info(
    "This demo runs the workflow against a repository visible to the machine running "
    "Streamlit. A Windows path on your computer will not work in a separately hosted app. "
    "For hosted runs, choose GitHub URL so the server can clone the repository. "
    "Local Ollama mode requires the SWE-agent runner to be installed on that computer."
)

if "thread_id" not in st.session_state:
    st.session_state.thread_id = None
if "result" not in st.session_state:
    st.session_state.result = None
if "demo_started" not in st.session_state:
    st.session_state.demo_started = False
if "workflow_error" not in st.session_state:
    st.session_state.workflow_error = None


def get_workflow():
    """Create the workflow only when Live mode actually needs it."""
    if "workflow" in st.session_state:
        return st.session_state.workflow
    try:
        from agents.workflow_graph import GuardedWorkflow

        st.session_state.workflow = GuardedWorkflow(github_enabled=True)
    except Exception as exc:
        st.session_state.workflow = None
        st.session_state.workflow_error = str(exc)
    return st.session_state.workflow


def configure_selected_model() -> None:
    from agents.llm import configure_llm

    if not model_name.strip():
        raise ValueError("Enter an Ollama model name.")
    if not model_url:
        raise RuntimeError("The selected Ollama URL is not configured.")
    configure_llm(base_url=model_url, token=model_token, model_name=model_name.strip())


def show_result(result: dict) -> None:
    st.session_state.result = result
    if "__interrupt__" in result:
        request = result["__interrupt__"][0].value
        st.session_state.pending_request = request
    else:
        st.session_state.pending_request = None


def show_approval() -> None:
    request = st.session_state.get("pending_request")
    if not request:
        return
    st.subheader("Approval required")
    st.info(request["prompt"])
    if request["kind"] == "plan_approval":
        st.code(request.get("plan", "No plan returned"), language="text")
    elif request["kind"] == "promotion_approval":
        st.code(request.get("diff", "No diff returned"), language="diff")
    elif request["kind"] == "github_pr_approval":
        st.write(f"Branch: `{request.get('branch', '')}`")

    left, right = st.columns(2)
    with left:
        if st.button("Approve", type="primary", use_container_width=True):
            try:
                configure_selected_model()
                workflow = get_workflow()
                if workflow is None:
                    raise RuntimeError("The workflow backend could not be initialized.")
                with st.spinner("Resuming workflow…"):
                    show_result(workflow.resume(st.session_state.thread_id, True))
                st.rerun()
            except Exception as exc:
                st.error(f"Could not resume this workflow: {exc}")
    with right:
        if st.button("Reject", use_container_width=True):
            try:
                workflow = get_workflow()
                if workflow is None:
                    raise RuntimeError("The workflow backend could not be initialized.")
                show_result(workflow.resume(st.session_state.thread_id, False))
                st.rerun()
            except Exception as exc:
                st.error(f"Could not resume this workflow: {exc}")


with st.expander("Resume an existing workflow"):
    st.caption("Use the thread ID shown after a workflow pauses or after the browser is refreshed.")
    resume_id = st.text_input("Workflow thread ID", key="resume_id")
    resume_decision = st.radio("Decision", ["Approve", "Reject"], horizontal=True, key="resume_decision")
    if st.button("Resume workflow", key="resume_workflow"):
        if not resume_id.strip():
            st.error("Enter a workflow thread ID.")
        else:
            try:
                if resume_decision == "Approve":
                    configure_selected_model()
                workflow = get_workflow()
                if workflow is None:
                    raise RuntimeError("The workflow backend could not be initialized.")
                with st.spinner("Resuming workflow…"):
                    resumed = workflow.resume(resume_id.strip(), resume_decision == "Approve")
                st.session_state.thread_id = resume_id.strip()
                show_result(resumed)
                st.rerun()
            except Exception as exc:
                st.error(f"Could not resume workflow {resume_id.strip()}: {exc}")


mode = st.radio(
    "Execution mode",
    ["Live workflow", "Demo preview"],
    horizontal=True,
    help="Demo preview shows the interface without invoking the model or changing a repository.",
)


repo_source = st.radio(
    "Repository source",
    ["Local path", "GitHub URL"],
    horizontal=True,
    help="Use Local path for your desktop demo, or GitHub URL when the app is hosted remotely.",
)

with st.form("start_workflow"):
    if repo_source == "Local path":
        repo_path = st.text_input(
            "Repository path",
            value=st.session_state.get("repo_path", ""),
            placeholder=r"C:\path\to\your\cloned\repository",
        )
    else:
        repo_url = st.text_input(
            "GitHub repository URL",
            value=st.session_state.get("repo_url", ""),
            placeholder="https://github.com/owner/repository",
        )
        repo_branch = st.text_input(
            "Branch (optional)",
            value=st.session_state.get("repo_branch", ""),
            placeholder="main",
        )
    issue = st.text_area(
        "Issue description",
        value=st.session_state.get("issue", ""),
        height=150,
        placeholder="Describe the bug and expected behavior…",
    )
    start = st.form_submit_button("Start workflow", type="primary")

if start:
    if mode == "Demo preview":
        st.session_state.demo_started = True
        st.session_state.thread_id = None
        st.session_state.pending_request = None
        st.rerun()
    else:
        if not issue.strip():
            st.error("Enter an issue description.")
        else:
            try:
                if repo_source == "Local path":
                    resolved = str(Path(repo_path).expanduser())
                    if not os.path.isdir(resolved):
                        raise ValueError(f"Repository path does not exist: {resolved}")
                    st.session_state.repo_path = resolved
                else:
                    if not repo_url.strip():
                        raise ValueError("Enter a GitHub repository URL.")
                    with st.spinner("Cloning repository…"):
                        resolved = clone_github_repository(repo_url, branch=repo_branch)
                    st.session_state.repo_url = repo_url.strip()
                    st.session_state.repo_branch = repo_branch.strip()

                st.session_state.demo_started = False
                st.session_state.issue = issue
                configure_selected_model()
                workflow = get_workflow()
                if workflow is None:
                    raise RuntimeError("The workflow backend could not be initialized.")
                thread_id = str(uuid.uuid4())
                with st.spinner("Starting investigation…"):
                    thread_id, result = workflow.start(resolved, issue, thread_id=thread_id)
                st.session_state.thread_id = thread_id
                show_result(result)
                st.rerun()
            except Exception as exc:
                st.error(f"Could not start the workflow: {exc}")


if st.session_state.get("demo_started"):
    st.subheader("Demo preview")
    st.success("The interface is ready. Live execution requires the Kaggle/Ollama backend to be online.")
    st.progress(1.0, text="Investigate → plan → sandbox fix → validate → approve → pull request")
    st.caption("Demo preview does not clone repositories, call the model, or change files.")

if st.session_state.get("thread_id"):
    st.caption(f"Workflow thread: `{st.session_state.thread_id}`")
    show_approval()

result = st.session_state.get("result") or {}
if result and "__interrupt__" not in result:
    status = result.get("status", "finished")
    if status in {"committed", "pr_created"}:
        st.success(f"Workflow complete: {status}")
    elif status == "rejected":
        st.warning("Workflow rejected; no further changes were made.")
    else:
        st.warning(f"Workflow ended with status: {status}")
    if result.get("branch_name"):
        st.write(f"Branch: `{result['branch_name']}`")
