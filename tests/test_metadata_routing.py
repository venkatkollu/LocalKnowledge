import pytest
from conftest import chat


def test_count_documents(client, corpus):
    r = chat(client, "how many documents are indexed")
    assert r["evidence"]["decision"] == "metadata_answer"
    assert str(len(corpus)) in r["answer"]


def test_list_documents(client, corpus):
    r = chat(client, "list all documents")
    assert r["evidence"]["decision"] == "metadata_answer"
    for name in corpus:
        assert name in r["answer"]


def test_zero_chunks_count(client, corpus):
    r = chat(client, "how many documents have zero chunks")
    assert r["evidence"]["decision"] == "metadata_answer"
    assert "1" in r["answer"]
    assert str(len(corpus)) not in r["answer"]


def test_zero_chunks_list(client, corpus):
    r = chat(client, "which documents have zero chunks")
    assert r["evidence"]["decision"] == "metadata_answer"
    assert "empty.txt" in r["answer"]
    assert "lora.txt" not in r["answer"]
    assert "bert.txt" not in r["answer"]


def test_chunks_of_named_document(client, corpus):
    r = chat(client, "how many chunks does lora.txt have")
    assert r["evidence"]["decision"] == "metadata_answer"
    assert "1" in r["answer"]


def test_chunks_of_named_document_no_extension(client, corpus):
    r = chat(client, "how many chunks does bert have")
    assert r["evidence"]["decision"] == "metadata_answer"
    assert "1" in r["answer"]


def test_extension_filter_markdown(client, corpus):
    r = chat(client, "how many files are markdown")
    assert r["evidence"]["decision"] == "metadata_answer"
    assert "0" in r["answer"]


def test_extension_filter_txt(client, corpus):
    r = chat(client, "how many files are txt")
    assert r["evidence"]["decision"] == "metadata_answer"
    assert str(len(corpus)) in r["answer"]


def test_most_chunks_named(client, corpus):
    r = chat(client, "which document has the most chunks")
    assert r["evidence"]["decision"] == "metadata_answer"
    assert any(name in r["answer"] for name in ("lora.txt", "qlora.txt", "bert.txt"))


def test_status_filter(client, corpus):
    r = chat(client, "which documents are not indexed")
    assert r["evidence"]["decision"] == "metadata_answer"


def test_metadata_bypasses_retrieval(client, corpus, monkeypatch):
    def boom(*a, **kw):
        raise AssertionError("retrieve() called for a metadata question")
    monkeypatch.setattr("backend.main.retrieve", boom)
    r = chat(client, "how many documents")
    assert r["evidence"]["decision"] == "metadata_answer"


def test_metadata_trace_outcome(client, corpus):
    chat(client, "list all documents")
    with __import__("backend.main", fromlist=["db"]).db() as conn:
        row = conn.execute(
            "SELECT outcome FROM traces WHERE route='/chat' "
            "ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    assert row["outcome"] == "metadata_answer"