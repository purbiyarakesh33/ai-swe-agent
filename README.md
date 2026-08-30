# AI Software Engineering Agent

An agentic software-engineering workflow that investigates GitHub issues, creates an implementation plan, tests fixes in an isolated sandbox, validates the result, and creates a draft pull request.

## Workflow

```text
Issue
  ↓
Understanding & Reproduction
  ↓
Planning
  ↓
Human Approval
  ↓
Sandbox Execution
  ↓
Independent Validation
  ├── Failure → Failure Analysis → Planning
  └── Success
          ↓
   Human Approval
          ↓
   Branch + Commit
          ↓
   Human Approval
          ↓
   Draft GitHub Pull Request
```

## Agents

1. **Understanding Agent** — explores the repository and reproduces the issue.
2. **Planning Agent** — identifies the root cause and creates a step-by-step plan.
3. **Execution Agent** — applies the plan inside an isolated Docker sandbox.
4. **Failure Analysis Agent** — analyzes failed tests and sends the workflow back to planning.
5. **Validation Agent** — independently reruns tests and checks the proposed diff.

## Features

- LangGraph-based orchestration
- Human approval gates
- Docker sandbox execution
- GitHub URL repository cloning
- Local repository support
- Test-driven verification
- Checkpoint persistence and workflow resume
- Git branch and commit creation
- Draft pull request creation through GitHub CLI
- Optional LangSmith tracing
- Mermaid workflow graph generation

## Requirements

- Python 3.11+
- Git
- Docker Desktop with the Docker daemon running
- GitHub CLI (`gh`) for pull requests
- Ollama-compatible model endpoint
- Optional: LangSmith API key for tracing

## Installation

```powershell
cd "C:\Users\Admin\OneDrive\Desktop\swe agent"

python -m venv .venv
.\.venv\Scripts\Activate.ps1

pip install -r requirements-ui.txt
```

Verify Docker and GitHub CLI:

```powershell
docker version
gh --version
```

Authenticate GitHub CLI:

```powershell
gh auth login
```

## Run the Streamlit UI

Set the Ollama endpoint and model:

```powershell
$env:OLLAMA_BASE_URL="YOUR_OLLAMA_URL"
$env:OLLAMA_TOKEN="YOUR_OPTIONAL_TOKEN"
$env:OLLAMA_MODEL="devstral-small-2:24b-instruct-2512-q4_K_M"
```

Optional LangSmith tracing:

```powershell
$env:LANGSMITH_TRACING="true"
$env:LANGSMITH_API_KEY="YOUR_LANGSMITH_KEY"
$env:LANGSMITH_PROJECT="ai-swe-agent-demo"
```

Start Streamlit:

```powershell
streamlit run .\streamlit_app.py --server.address 0.0.0.0 --server.port 8501
```

Open `http://localhost:8501`.

## Using the UI

For a local repository, choose **Local path** and enter a repository visible to the computer running Streamlit.

For a GitHub repository, choose **GitHub URL** and enter a URL such as:

```text
https://github.com/owner/repository.git
```

For hosted or remotely accessed runs, use GitHub URL instead of a Windows path.

The workflow asks for approval before sandbox execution, promotion into a branch and commit, and pushing the branch to create a draft pull request.

## Command-line usage

```powershell
python .\run_workflow.py `
  "C:\path\to\repository" `
  "Describe the bug and expected behavior."
```

Enable GitHub pull-request creation with `--github`:

```powershell
python .\run_workflow.py `
  "C:\path\to\repository" `
  "Describe the bug and expected behavior." `
  --github
```

## Generate the workflow graph

```powershell
python -m agents.workflow_graph
```

This prints the Mermaid graph and saves `workflow_graph.png`.

## Tests

```powershell
python -m pytest -q .\test_workflow_graph.py
```

The target repository's tests are run inside the Docker sandbox during the workflow.

## LangSmith tracing

LangSmith is optional and shows agent steps, tool calls, latency, token usage, errors, and retries. Never commit LangSmith or Ollama API keys. Traces may contain prompts, issue descriptions, source snippets, and tool output, so use a safe demonstration repository when recording.

## Kaggle GPU demonstration

For the demonstration, a large Ollama model can run on a Kaggle GPU and be exposed through an authenticated Cloudflare tunnel.

The public demo is temporary. It works only while the Kaggle runtime, Ollama proxy, Streamlit process, and Cloudflare tunnel remain active. Restarting the session creates a new endpoint and token.

A production deployment would use a persistent GPU server or a managed LLM API.

## Security notes

- Do not commit tokens or API keys.
- Do not expose secrets in screen recordings.
- Use neutral issue descriptions that do not reveal the expected fix.
- Review the proposed diff before promotion.
- Do not run arbitrary public workflows without authentication and access controls.

## Project structure

```text
agents/
  agent1_understanding.py
  agent2_planning.py
  agent3_execution.py
  agent4_failure_analysis.py
  agent5_validation.py
  agent_loop.py
  docker_sandbox.py
  github_pr.py
  history.py
  llm.py
  promotion.py
  repository_source.py
  sandbox_tools.py
  state.py
  tools.py
  workflow_graph.py

streamlit_app.py
run_workflow.py
requirements-ui.txt
LOCAL_SETUP.md
```
