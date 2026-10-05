import httpx
import pytest

from app.config import Settings
from app.embeddings import LocalEmbedding


def test_ollama_embedding_digest_is_pinned_before_embedding(monkeypatch):
    request = httpx.Request("GET", "http://127.0.0.1:11434/api/tags")
    monkeypatch.setattr(httpx, "get", lambda *args, **kwargs: httpx.Response(200, request=request, json={"models": [{"name": "nomic-embed-text:latest", "digest": "changed"}]}))
    embedder = LocalEmbedding(Settings(), "ollama", "nomic-embed-text", 2, revision="original")
    with pytest.raises(ValueError, match="digest changed"):
        embedder.embed(["query"])
    # No provider request for embeddings is needed when identity is wrong.
    embedder = LocalEmbedding(Settings(), "ollama", "nomic-embed-text", 2, revision="changed")
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: httpx.Response(200, request=request, json={"embeddings": [[0.5, 0.5]]}))
    assert embedder.embed(["query"]) == [[0.5, 0.5]]
