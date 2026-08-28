param(
    [string]$Model = "qwen2.5-coder:7b"
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    Write-Error "Ollama is not installed or is not on PATH. Install Ollama, then run this script again."
}

Write-Host "Using local Ollama model: $Model"
ollama pull $Model

$env:OLLAMA_LOCAL_BASE_URL = "http://localhost:11434"
$env:OLLAMA_LOCAL_MODEL = $Model

Write-Host "Starting the SWE Agent UI..."
streamlit run .\streamlit_app.py
