# Local Ollama mode

Local mode runs the complete SWE agent on the user's own computer. This keeps
the repository, Docker sandbox, and model local; no Kaggle tunnel is needed.

## Setup

1. Install [Ollama](https://ollama.com/download).
2. Open PowerShell in this `swe agent` folder.
3. Run:

```powershell
.\run_local.ps1
```

The script downloads the default small coding model and starts Streamlit.
To use another installed model:

```powershell
.\run_local.ps1 -Model "your-ollama-model-tag"
```

In the UI, choose **Local Ollama (requires local runner)**. The repository path
must be a folder on the same computer running Streamlit.
