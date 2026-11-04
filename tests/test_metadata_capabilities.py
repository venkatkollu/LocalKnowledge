"""Metadata model, format parsing, filters and combined routing."""

import io
from datetime import datetime, timedelta, timezone

import pytest

import backend.main as m
from conftest import chat


def upload(client, name, data, mime="application/octet-stream"):
    response = client.post(
        "/api/documents", files={"files": (name, io.BytesIO(data), mime)}
    )
    assert response.status_code == 200, response.text
    assert name in response.json()["accepted"], response.json()


def document(client, name):
    return next(
        d for d in client.get("/api/documents").json()["documents"] if d["filename"] == name
    )


def test_document_metadata_contract(client, corpus):
    row = document(client, "lora.txt")
    assert row["document_id"] == row["id"] == corpus["lora.txt"]["id"]
    assert row["file_type"] == "txt"
    assert row["file_size"] > 0
    assert len(row["file_hash"]) == 64
    assert row["page_count"] is None
    assert row["total_chunks"] == 1
    assert row["processing_status"] == "synced"
    assert row["upload_date"]
    assert row["title"] == "lora"


def test_chunk_metadata_contract(client, corpus):
    document_id = corpus["lora.txt"]["id"]
    detail = client.get(f"/api/documents/{document_id}").json()
    chunk = detail["chunks"][0]
    assert chunk["chunk_id"] == chunk["id"]
    assert chunk["document_id"] == document_id
    assert chunk["chunk_index"] == 0
    assert chunk["chunk_type"] == "text"
    assert chunk["content"] and chunk["excerpt"] == chunk["content"]
    assert isinstance(chunk["start_offset"], int)
    assert chunk["end_offset"] > chunk["start_offset"]
    assert chunk["page_number"] is None


def test_chunk_type_classification():
    assert m.classify_chunk("# Title") == "heading"
    assert m.classify_chunk("| a | b |\n| --- | --- |\n| 1 | 2 |") == "table"
    assert m.classify_chunk("- one\n- two") == "list"
    assert m.classify_chunk("```python\nprint(1)\n```") == "code"
    assert m.classify_chunk("$$\nx = y\n$$") == "equation"
    assert m.classify_chunk("Figure 2: attention map") == "figure"
    assert m.classify_chunk("Plain paragraph.") == "text"
    assert set(m.CHUNK_TYPES) == {"text", "heading", "table", "figure", "list", "code", "equation"}


def test_chunk_positions_page_and_sections():
    text = "# Intro\n\n" + ("a" * 1300) + "\n\n## Methods\n\n" + ("b" * 1300)
    chunks = m.split_chunks(text, [(1, 0, len(text) // 2), (2, len(text) // 2, len(text))])
    assert chunks[0]["section"] == "Intro"
    assert any(chunk["section"] == "Methods" for chunk in chunks)
    assert chunks[-1]["page_number"] == 2
    offsets = [(chunk["start_offset"], chunk["end_offset"]) for chunk in chunks]
    assert offsets == sorted(offsets)
    assert all(0 <= start < end for start, end in offsets)


def test_docx_tables_and_combined_routing(client, corpus, active_index_with_corpus):
    document_module = pytest.importorskip("docx")

    doc = document_module.Document()
    doc.add_heading("Neural Networks", level=1)
    doc.add_paragraph("Transformers rely on self-attention.")
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Model"
    table.cell(0, 1).text = "Layers"
    table.cell(1, 0).text = "BERT"
    table.cell(1, 1).text = "12"
    buffer = io.BytesIO()
    doc.save(buffer)
    upload(client, "networks.docx", buffer.getvalue())

    row = document(client, "networks.docx")
    assert row["file_type"] == "docx"
    assert row["processing_status"] == "synced"
    detail = client.get(f"/api/documents/{row['id']}").json()
    assert "self-attention" in detail["content"]
    assert any(chunk["chunk_type"] == "table" for chunk in detail["chunks"])

    tables = chat(client, "which documents contain tables")
    assert tables["evidence"]["decision"] == "metadata_answer"
    assert "networks.docx" in tables["answer"]

    combined = chat(client, "Which document discusses networks, and what does it say?")
    assert combined["retrieval"]["combined"] is True
    assert combined["retrieval"]["candidate_documents"]
    assert {c["filename"] for c in combined["citations"]} <= {
        d["filename"] for d in combined["retrieval"]["candidate_documents"]
    }


def test_pdf_page_filter(client, corpus):
    pypdf = pytest.importorskip("pypdf")
    writer = pypdf.PdfWriter()
    for _ in range(3):
        writer.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)
    upload(client, "paper.pdf", buffer.getvalue(), "application/pdf")

    row = document(client, "paper.pdf")
    assert row["page_count"] == 3

    filtered = chat(client, "which documents have more than 2 pages")
    assert filtered["evidence"]["decision"] == "metadata_answer"
    assert "paper.pdf" in filtered["answer"]
    assert "lora.txt" not in filtered["answer"]

    counted = chat(client, "how many documents have at least 3 pages")
    assert counted["evidence"]["decision"] == "metadata_answer"
    assert "1 document" in counted["answer"]


def test_file_type_and_upload_date_filters(client, corpus):
    by_type = chat(client, "how many documents are indexed", filters={"file_type": "txt"})
    assert by_type["evidence"]["decision"] == "metadata_answer"
    assert str(len(corpus)) in by_type["answer"]

    recent = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    recent_count = chat(client, "how many documents are indexed", filters={"uploaded_after": recent})
    assert str(len(corpus)) in recent_count["answer"]

    old = datetime(2000, 1, 1, tzinfo=timezone.utc).isoformat()
    old_count = chat(client, "how many documents are indexed", filters={"uploaded_before": old})
    assert "0 documents" in old_count["answer"]


def test_spreadsheet_csv_html_and_slides(client, corpus):
    openpyxl = pytest.importorskip("openpyxl")
    pptx = pytest.importorskip("pptx")

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Models"
    sheet.append(["Model", "Layers"])
    sheet.append(["BERT", 12])
    buffer = io.BytesIO()
    workbook.save(buffer)
    upload(client, "models.xlsx", buffer.getvalue())
    xlsx_detail = client.get(f"/api/documents/{document(client, 'models.xlsx')['id']}").json()
    assert "BERT" in xlsx_detail["content"]
    assert any(chunk["chunk_type"] == "table" for chunk in xlsx_detail["chunks"])

    upload(client, "models.csv", b"Model,Layers\nBERT,12\n")
    csv_detail = client.get(f"/api/documents/{document(client, 'models.csv')['id']}").json()
    assert "BERT" in csv_detail["content"]

    html = b"<html><head><title>Docs</title></head><body><h1>Intro</h1><p>Hello</p></body></html>"
    upload(client, "page.html", html)
    html_row = document(client, "page.html")
    assert html_row["title"] == "Docs"
    html_detail = client.get(f"/api/documents/{html_row['id']}").json()
    assert "Hello" in html_detail["content"]

    presentation = pptx.Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[1])
    slide.shapes.title.text = "Model Architecture"
    slide.placeholders[1].text = "Transformers use attention"
    slides = io.BytesIO()
    presentation.save(slides)
    upload(client, "deck.pptx", slides.getvalue())
    deck_row = document(client, "deck.pptx")
    assert deck_row["page_count"] == 1
    deck_detail = client.get(f"/api/documents/{deck_row['id']}").json()
    assert "attention" in deck_detail["content"]
    assert deck_detail["chunks"][0]["page_number"] == 1
