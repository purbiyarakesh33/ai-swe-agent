import os
from contextvars import ContextVar
from langchain_ollama import ChatOllama

DEFAULT_MODEL_NAME = "devstral-small-2:24b-instruct-2512-q4_K_M"
_runtime_config: ContextVar[dict] = ContextVar("ollama_runtime_config", default={})


def configure_llm(*, base_url: str, token: str = "", model_name: str | None = None) -> None:
    """Set per-run Ollama settings without putting credentials in prompts or UI."""
    _runtime_config.set({
        "base_url": base_url.rstrip("/"),
        "token": token,
        "model_name": model_name or os.environ.get("OLLAMA_MODEL", DEFAULT_MODEL_NAME),
    })


def get_llm(temperature: float = 0.1) -> ChatOllama:
    config = _runtime_config.get()
    base_url = config.get("base_url", os.environ.get("OLLAMA_BASE_URL", "")).rstrip("/")
    token = config.get("token", os.environ.get("OLLAMA_TOKEN", ""))
    model_name = config.get("model_name", os.environ.get("OLLAMA_MODEL", DEFAULT_MODEL_NAME))
    if not base_url:
        raise RuntimeError("OLLAMA_BASE_URL is not configured")

    client_kwargs = {}
    if token:
        client_kwargs["headers"] = {"Authorization": f"Bearer {token}"}
    return ChatOllama(
        model=model_name,
        temperature=temperature,
        num_ctx=32768,
        base_url=base_url,
        client_kwargs=client_kwargs,
    )
