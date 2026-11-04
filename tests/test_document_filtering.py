from conftest import chat


def test_single_document_scope(client, corpus):
    lora = corpus["lora.txt"]["id"]
    r = chat(client, "What optimizer is used?", document_id=lora)
    assert r["citations"]
    assert {c["filename"] for c in r["citations"]} == {"lora.txt"}


def test_unknown_document_returns_404(client):
    r = client.post("/api/chat", json={"question": "x", "document_id": "nope"})
    assert r.status_code == 404


def test_document_list_scope(client, corpus):
    ids = [corpus["lora.txt"]["id"], corpus["bert.txt"]["id"]]
    r = chat(client, "What learning rate is used?", document_ids=ids)
    files = {c["filename"] for c in r["citations"]}
    assert files and files <= {"lora.txt", "bert.txt"}


def test_filename_filter(client, corpus):
    r = chat(client, "What learning rate is used?",
             filters={"filename": "bert.txt"})
    assert {c["filename"] for c in r["citations"]} == {"bert.txt"}


def test_extension_filter(client, corpus):
    r = chat(client, "What learning rate is used?",
             filters={"extension": "txt"})
    assert all(c["filename"].endswith(".txt") for c in r["citations"])


def test_no_filter_spans_multiple_documents(client, corpus):
    r = chat(client, "What learning rate is used?", top_k=6)
    files = {c["filename"] for c in r["citations"]}
    assert len(files) >= 2, f"expected multiple sources, got {files}"


def test_intent_reflected_in_response(client, corpus):
    r = chat(client, "What optimizer does LoRA use?")
    assert r["retrieval"]["intent"] == "text"
    # index_id may be None if no active index
    assert "index_id" in r["retrieval"]