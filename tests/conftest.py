from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import backend.main as m


# --- isolation ---------------------------------------------------------------

@pytest.fixture()
def data_dir(tmp_path: Path) -> Path:
    d = tmp_path / "kos"
    d.mkdir()
    return d


@pytest.fixture()
def settings(monkeypatch, data_dir):
    monkeypatch.setenv("KNOWLEDGEOS_DATA_DIR", str(data_dir))
    monkeypatch.setenv("KNOWLEDGEOS_ALLOW_ANONYMOUS", "true")
    monkeypatch.setenv("KNOWLEDGEOS_ALLOW_HASH_EMBEDDING_FALLBACK", "true")
    monkeypatch.setenv("KNOWLEDGEOS_ABSTAIN_THRESHOLD", "0.15")
    fresh = m.Settings()
    monkeypatch.setattr(m, "SETTINGS", fresh)
    return fresh


@pytest.fixture()
def client(settings):
    with TestClient(m.app) as c:
        yield c


# --- deterministic embeddings + LLM -----------------------------------------

@pytest.fixture(autouse=True)
def deterministic_embeddings(monkeypatch):
    cache: dict[str, list[float]] = {}

    def _normalize(text: str) -> str:
        stop = {"what", "is", "the", "a", "an", "how", "many",
                "does", "do", "which", "are", "there", "of"}
        return " ".join(w.lower() for w in text.split() if w.lower() not in stop)

    def fake_embed(row, text):
        key = _normalize(text)
        if key not in cache:
            cache[key] = m.deterministic_vector(key, dimensions=64)
        return cache[key]

    def fake_provider(row, path, payload, timeout=30.0, method="POST"):
        if path == "/chat/completions":
            user = (payload.get("messages") or [{}])[-1].get("content", "")
            evidence = ""
            if "<evidence>" in user:
                evidence = user.split("<evidence>", 1)[1].split("</evidence>", 1)[0]
            first = evidence.strip().split("\n\n", 1)[0] if evidence.strip() else "no evidence"
            return {"choices": [{"message": {"content": first[:400]}}]}
        if path == "/embeddings":
            return {"data": [{"embedding": fake_embed(None, payload.get("input", ""))}]}
        if path == "/models":
            return {"data": [{"id": "fake"}]}
        return {}

    monkeypatch.setattr(m, "embed_text", fake_embed)
    monkeypatch.setattr(m, "ollama_embed_text", lambda text: fake_embed(None, text))
    monkeypatch.setattr(m, "provider_request", fake_provider)


@pytest.fixture(autouse=True)
def sync_executor(monkeypatch):
    monkeypatch.setattr(m.EXECUTOR, "submit", lambda fn, *a, **kw: fn(*a, **kw))


# --- corpus ------------------------------------------------------------------

FIXTURE_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture()
def corpus(client):
    ingested: dict[str, dict[str, Any]] = {}
    for path in sorted(FIXTURE_DIR.glob("*.txt")):
        with path.open("rb") as fh:
            r = client.post(
                "/api/documents",
                files={"files": (path.name, fh, "text/plain")},
            )
        assert r.status_code == 200, r.text
        assert path.name in r.json()["accepted"], r.json()
        listing = client.get("/api/documents").json()["documents"]
        ingested[path.name] = next(d for d in listing if d["filename"] == path.name)
    return ingested


@pytest.fixture()
def active_index_with_corpus(client, corpus):
    """Create and activate an index containing all corpus documents."""
    create = client.post("/api/indexes", json={"notes": "test-corpus"}).json()
    idx_id = create["index"]["id"]
    client.post(f"/api/indexes/{idx_id}/build")
    client.post(f"/api/indexes/{idx_id}/validate")
    client.post(f"/api/indexes/{idx_id}/activate")
    return idx_id


# --- helpers -----------------------------------------------------------------

def chat(client, question: str, **extra):
    r = client.post("/api/chat", json={"question": question, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def cache_count() -> int:
    with m.db() as conn:
        return conn.execute("SELECT COUNT(*) FROM cache_entries").fetchone()[0]


def chunk_ids_for(doc_id: str) -> list[str]:
    with m.db() as conn:
        return [
            row[0]
            for row in conn.execute(
                "SELECT id FROM chunks WHERE document_id=? AND superseded=0",
                (doc_id,),
            ).fetchall()
        ]