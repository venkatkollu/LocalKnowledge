"""Document format parsers and normalized extraction results."""
from __future__ import annotations

import csv
import os
import re
from dataclasses import dataclass, field
from html import unescape
from pathlib import Path

from .utils import extension


@dataclass
class ExtractedDocument:
    """Normalized extraction result: text plus the metadata the parser knows."""

    text: str
    pages: int | None = None
    title: str | None = None
    author: str | None = None
    page_spans: list[tuple[int, int, int]] = field(default_factory=list)
    section_path: str = ""  # breadcrumb path: "H1 > H2 > H3"
    chunk_type: str = "text"  # text, heading, table, list, figure
    section_level: int | None = None  # 1-6 for headings



class _TextBuilder:
    """Join blocks and keep character spans for page attribution."""

    def __init__(self) -> None:
        self.parts: list[str] = []
        self.spans: list[tuple[int, int, int]] = []
        self.length = 0

    def add(self, block: str, page: int | None = None) -> None:
        block = block.strip()
        if not block:
            return
        if self.parts:
            self.length += 2
        start = self.length
        self.parts.append(block)
        self.length += len(block)
        if page is not None:
            self.spans.append((page, start, self.length))

    def text(self) -> str:
        return "\n\n".join(self.parts)



def _decode_text_file(path: Path) -> str:
    output: list[str] = []
    remaining = int(os.getenv("KNOWLEDGEOS_MAX_EXTRACTED_BYTES", str(64 * 1024 * 1024)))
    with path.open("rb") as handle:
        while remaining > 0:
            block = handle.read(min(1024 * 1024, remaining))
            if not block:
                break
            remaining -= len(block)
            output.append(block.decode("utf-8", errors="replace"))
    return "".join(output)



def _ocr_image(path: Path) -> str:
    """Optional OCR. Missing tesseract or OCR libraries yields no text."""
    try:
        import pytesseract
        from PIL import Image

        with Image.open(path) as image:
            return (pytesseract.image_to_string(image) or "").strip()
    except Exception:
        return ""



def _ocr_pdf_page(path: Path, page_number: int) -> str:
    try:
        import pytesseract
        from pdf2image import convert_from_path

        images = convert_from_path(str(path), first_page=page_number, last_page=page_number)
        return "\n".join((pytesseract.image_to_string(image) or "").strip() for image in images).strip()
    except Exception:
        return ""



def _pdf_document(path: Path) -> ExtractedDocument:
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
    except Exception:
        return ExtractedDocument(text="")
    builder = _TextBuilder()
    for number, page in enumerate(reader.pages, start=1):
        try:
            page_text = page.extract_text() or ""
        except Exception:
            page_text = ""
        if not page_text.strip():
            page_text = _ocr_pdf_page(path, number)
        builder.add(page_text, number)

    metadata = reader.metadata or {}

    def meta(key: str) -> str | None:
        value = metadata.get(key) if hasattr(metadata, "get") else None
        return str(value).strip() or None if value else None

    return ExtractedDocument(
        text=builder.text(),
        pages=len(reader.pages),
        title=meta("/Title"),
        author=meta("/Author"),
        page_spans=builder.spans,
    )



def _docx_document(path: Path) -> ExtractedDocument:
    try:
        from docx import Document as DocxDocument
        from docx.table import Table
        from docx.text.paragraph import Paragraph
    except Exception:
        return ExtractedDocument(text="")
    try:
        document = DocxDocument(str(path))
        builder = _TextBuilder()
        for child in document.element.body.iterchildren():
            tag = child.tag.rsplit("}", 1)[-1]
            if tag == "p":
                paragraph = Paragraph(child, document)
                value = paragraph.text.strip()
                if not value:
                    continue
                style = (paragraph.style.name or "").lower() if paragraph.style is not None else ""
                if style.startswith("title"):
                    builder.add("# " + value)
                elif style.startswith("heading"):
                    builder.add("## " + value)
                else:
                    builder.add(value)
            elif tag == "tbl":
                table = Table(child, document)
                rows = []
                for row in table.rows:
                    cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
                    if any(cells):
                        rows.append("| " + " | ".join(cells) + " |")
                if rows:
                    builder.add("\n".join(rows))
        properties = document.core_properties
        return ExtractedDocument(
            text=builder.text(),
            title=(properties.title or "").strip() or None,
            author=(properties.author or "").strip() or None,
        )
    except Exception:
        return ExtractedDocument(text="")



def _xlsx_document(path: Path) -> ExtractedDocument:
    try:
        from openpyxl import load_workbook

        workbook = load_workbook(filename=str(path), read_only=True, data_only=True)
    except Exception:
        return ExtractedDocument(text="")
    builder = _TextBuilder()
    try:
        for sheet in workbook.worksheets:
            rows = []
            for row in sheet.iter_rows(values_only=True):
                cells = ["" if value is None else str(value) for value in row]
                if any(cell.strip() for cell in cells):
                    rows.append("| " + " | ".join(cells) + " |")
            if rows:
                builder.add(f"## Sheet: {sheet.title}\n" + "\n".join(rows))
    finally:
        workbook.close()
    return ExtractedDocument(text=builder.text())



def _pptx_document(path: Path) -> ExtractedDocument:
    try:
        from pptx import Presentation

        presentation = Presentation(str(path))
    except Exception:
        return ExtractedDocument(text="")
    builder = _TextBuilder()
    for number, slide in enumerate(presentation.slides, start=1):
        blocks: list[str] = []
        for shape in slide.shapes:
            if getattr(shape, "has_text_frame", False) and shape.has_text_frame:
                value = shape.text_frame.text.strip()
                if value:
                    blocks.append(value)
            if getattr(shape, "has_table", False) and shape.has_table:
                for row in shape.table.rows:
                    cells = [cell.text.strip() for cell in row.cells]
                    if any(cells):
                        blocks.append("| " + " | ".join(cells) + " |")
        if blocks:
            builder.add("\n\n".join(blocks), number)
    properties = presentation.core_properties
    return ExtractedDocument(
        text=builder.text(),
        pages=len(presentation.slides),
        title=(properties.title or "").strip() or None,
        author=(properties.author or "").strip() or None,
        page_spans=builder.spans,
    )



def _csv_document(path: Path) -> ExtractedDocument:
    builder = _TextBuilder()
    rows = []
    with path.open(newline="", encoding="utf-8", errors="replace") as handle:
        for row in csv.reader(handle):
            cells = [cell.strip() for cell in row]
            if any(cells):
                rows.append("| " + " | ".join(cells) + " |")
    builder.add("\n".join(rows))
    return ExtractedDocument(text=builder.text())



def _html_document(path: Path) -> ExtractedDocument:
    raw = _decode_text_file(path)
    title_match = re.search(r"<title[^>]*>(.*?)</title>", raw, re.IGNORECASE | re.DOTALL)
    title = unescape(title_match.group(1)).strip() if title_match else None
    body = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw)
    body = re.sub(
        r"(?i)<h([1-6])[^>]*>",
        lambda match: "\n\n" + "#" * int(match.group(1)) + " ",
        body,
    )
    body = re.sub(r"(?i)</h[1-6]>|<br\s*/?>|</p>|</div>|</li>|</tr>", "\n", body)
    body = re.sub(r"(?i)<td[^>]*>", " | ", body)
    body = re.sub(r"<[^>]+>", " ", body)
    text = unescape(body)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return ExtractedDocument(text=text, title=title or None)



def _image_document(path: Path) -> ExtractedDocument:
    return ExtractedDocument(text=_ocr_image(path))



def extract_document(path: Path, name: str) -> ExtractedDocument:
    """Extract normalized text and available metadata for a supported format."""
    ext = extension(name)
    if ext == "pdf":
        return _pdf_document(path)
    if ext == "docx":
        return _docx_document(path)
    if ext == "xlsx":
        return _xlsx_document(path)
    if ext == "pptx":
        return _pptx_document(path)
    if ext == "csv":
        return _csv_document(path)
    if ext in {"html", "htm"}:
        return _html_document(path)
    if ext in {"png", "jpg", "jpeg", "tif", "tiff"}:
        return _image_document(path)
    return ExtractedDocument(text=_decode_text_file(path))



def read_document_text(path: Path, name: str) -> str:
    return extract_document(path, name).text
