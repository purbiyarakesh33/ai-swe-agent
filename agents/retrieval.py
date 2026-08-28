"""Two-stage retrieval: 1) file-level embedding narrows to candidate files,
2) chunk-level embedding within those files finds the specific relevant part."""
import os
import re
import numpy as np
from langchain_ollama import OllamaEmbeddings

embedder = OllamaEmbeddings(model="nomic-embed-text")


def _cosine_sim(a: list[float], b: list[float]) -> float:
    a, b = np.array(a), np.array(b)
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def _chunk_file(content: str, fpath: str) -> list[dict]:
    """Split a Python file into chunks at top-level def/class boundaries."""
    pattern = re.compile(r"^(def |class )", re.MULTILINE)
    matches = list(pattern.finditer(content))
    if not matches:
        return [{"file": fpath, "text": content, "start_line": 1}]

    chunks = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        chunk_text = content[start:end]
        start_line = content[:start].count("\n") + 1
        chunks.append({"file": fpath, "text": chunk_text, "start_line": start_line})
    return chunks


def get_relevant_files(repo_path: str, issue_description: str, top_k: int = 5) -> list[str]:
    """Stage 1: whole-file embedding, narrows the repo to candidate files."""
    files = []
    for root, dirs, filenames in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in (".git", "__pycache__", "node_modules", "venv", ".venv")]
        for fname in filenames:
            if not fname.endswith(".py") or fname.startswith("test_"):
                continue
            files.append(os.path.join(root, fname))

    if not files:
        return []

    contents = []
    for fpath in files:
        with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
            contents.append(f.read())

    file_embeddings = embedder.embed_documents(contents)
    issue_embedding = embedder.embed_query(issue_description)

    scored = [(_cosine_sim(issue_embedding, emb), fpath) for emb, fpath in zip(file_embeddings, files)]
    scored.sort(reverse=True)
    return [fpath for _, fpath in scored[:top_k]]


def get_relevant_chunks(repo_path: str, issue_description: str,
                         file_top_k: int = 5, chunk_top_k: int = 8) -> list[dict]:
    """Stage 2: chunk only the candidate files from stage 1, then rank chunks by similarity."""
    candidate_files = get_relevant_files(repo_path, issue_description, top_k=file_top_k)

    all_chunks = []
    for fpath in candidate_files:
        try:
            with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except OSError:
            continue
        all_chunks.extend(_chunk_file(content, fpath))

    if not all_chunks:
        return []

    texts = [c["text"] for c in all_chunks]
    chunk_embeddings = embedder.embed_documents(texts)
    issue_embedding = embedder.embed_query(issue_description)

    scored = [(_cosine_sim(issue_embedding, emb), chunk) for emb, chunk in zip(chunk_embeddings, all_chunks)]
    scored.sort(key=lambda x: x[0], reverse=True)
    return [chunk for _, chunk in scored[:chunk_top_k]]