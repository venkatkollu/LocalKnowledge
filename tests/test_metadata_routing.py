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


def test_document_names_list(client, corpus):
    r = chat(client, "what are the document names")
    assert r["evidence"]["decision"] == "metadata_answer"
    for name in corpus:
        assert name in r["answer"]


def test_catalog_overview_answers_from_metadata(client, corpus):
    r = chat(client, "what are all the documents about")
    assert r["evidence"]["decision"] == "metadata_answer"
    assert r["citations"] == []
    assert "lora.txt" in r["answer"]
    assert "LoRA freezes" in r["answer"]
    # The empty fixture has no chunks, so it has nothing to summarize.
    assert "empty.txt" not in r["answer"]


def test_catalog_overview_leaves_named_content_questions_to_retrieval():
    from backend.utils import is_catalog_overview

    assert is_catalog_overview("what are all the pdfs about?")
    assert is_catalog_overview("summarize the documents")
    assert not is_catalog_overview("what does lora.txt say about the optimizer?")
    assert not is_catalog_overview("what are the documents about LoRA?")


def test_greeting_typo_is_conversational(client):
    r = chat(client, "helo")
    assert r["evidence"]["decision"] == "conversational"
    assert r["citations"] == []


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
    monkeypatch.setattr("backend.answering.retrieve", boom)
    r = chat(client, "how many documents")
    assert r["evidence"]["decision"] == "metadata_answer"


def test_total_pages(client, corpus):
    r = chat(client, "what is the total number of pages across my documents")
    assert r["evidence"]["decision"] == "metadata_answer"
    assert "0 pages" in r["answer"]


def test_pages_of_named_document_without_page_metadata(client, corpus):
    r = chat(client, "how many pages does lora.txt have")
    assert r["evidence"]["decision"] == "metadata_answer"
    assert "no stored page count" in r["answer"]


def test_pdf_page_counts(client, tmp_path):
    import io

    from pypdf import PdfWriter

    writer = PdfWriter()
    for _ in range(3):
        writer.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)
    buffer.seek(0)
    r = client.post(
        "/api/documents",
        files={"files": ("paper.pdf", buffer, "application/pdf")},
    )
    assert r.status_code == 200, r.text
    assert "paper.pdf" in r.json()["accepted"], r.json()
    listing = client.get("/api/documents").json()["documents"]
    paper = next(d for d in listing if d["filename"] == "paper.pdf")
    assert paper["pages"] == 3, paper

    per_document = chat(client, "how many pages does paper.pdf have")
    assert per_document["evidence"]["decision"] == "metadata_answer"
    assert "3" in per_document["answer"]

    total = chat(client, "what is the total number of pages across my documents")
    assert total["evidence"]["decision"] == "metadata_answer"
    assert "3 pages" in total["answer"]

    names = chat(client, "what are the pdfs names")
    assert names["evidence"]["decision"] == "metadata_answer"
    assert "paper.pdf" in names["answer"]

    count = chat(client, "how many files are pdfs")
    assert count["evidence"]["decision"] == "metadata_answer"
    assert "1 file" in count["answer"]


def test_metadata_trace_outcome(client, corpus):
    chat(client, "list all documents")
    from backend.db import db

    with db() as conn:
        row = conn.execute(
            "SELECT outcome FROM traces WHERE route='/chat' "
            "ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    assert row["outcome"] == "metadata_answer"