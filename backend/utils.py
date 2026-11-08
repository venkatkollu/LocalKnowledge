"""Pure helpers: text, chunking, vectors, routing and evidence hygiene."""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import (
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    INJECTION_PATTERNS,
    INGEST_EXTENSIONS,
    PROMPT_INJECTION_GUARD,
)


def now_ms() -> int:
    return int(time.time() * 1000)



def utc_iso(epoch_ms: int | None) -> str | None:
    if epoch_ms is None:
        return None
    return datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc).isoformat()



def json_dumps(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)



def safe_filename(name: str) -> str:
    name = Path(name or "upload").name
    return re.sub(r"[^A-Za-z0-9._ -]", "_", name)[:240] or "upload"



def extension(name: str) -> str:
    return Path(name).suffix.lower().lstrip(".")



def language_for(name: str) -> str:
    ext = extension(name)
    return {
        "md": "Markdown", "txt": "Text", "py": "Python", "js": "JavaScript",
        "ts": "TypeScript", "tsx": "TSX", "jsx": "JSX", "json": "JSON",
        "yaml": "YAML", "yml": "YAML", "csv": "CSV", "sql": "SQL",
        "go": "Go", "rs": "Rust", "pdf": "PDF", "html": "HTML", "htm": "HTML",
        "docx": "Word", "xlsx": "Excel", "pptx": "PowerPoint", "png": "Image",
        "jpg": "Image", "jpeg": "Image", "tif": "Image", "tiff": "Image",
    }.get(ext, ext.upper() if ext else "Document")



def content_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()



def token_count(text: str) -> int:
    return max(1, len(re.findall(r"\S+", text))) if text.strip() else 0



def classify_chunk(value: str) -> str:
    """Assign one structural chunk type using cheap, deterministic rules."""
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    if not lines:
        return "text"
    if value.lstrip().startswith("```") or sum(
        1 for line in value.splitlines() if line.startswith("    ") or line.startswith("\t")
    ) >= max(2, len(lines) // 2):
        return "code"
    if any("$$" in line or line.startswith("\\[") or "\\begin{" in line for line in lines):
        return "equation"
    table_rows = sum(1 for line in lines if line.count("|") >= 2 or line.count("\t") >= 2)
    if table_rows >= 2 or re.match(r"^tables?\s*\d+", lines[0], re.IGNORECASE):
        return "table"
    if re.match(r"^#{1,6}\s+", lines[0]):
        return "heading"
    if re.match(r"^(?:figure|fig\.|exhibit|image|chart)\s*\d+", lines[0], re.IGNORECASE) or lines[0].startswith("!["):
        return "figure"
    if sum(1 for line in lines if re.match(r"^(?:[-*+]|\d+[.)])\s+", line)) >= max(1, len(lines) // 2):
        return "list"
    return "text"



def split_chunks(
    text: str,
    page_spans: list[tuple[int, int, int]] | None = None,
    chunk_size: int | None = None,
    overlap: int | None = None,
) -> list[dict[str, Any]]:
    """Split extracted text into typed chunks with stable position metadata."""
    size = max(1, chunk_size or CHUNK_SIZE)
    overlap_value = max(0, overlap if overlap is not None else CHUNK_OVERLAP)
    cleaned = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not cleaned:
        return []
    headings = [
        (match.start(), match.group(2).strip())
        for match in re.finditer(r"(?m)^(#{1,6})[ \t]+(.+?)[ \t]*$", cleaned)
    ]
    spans = page_spans or []
    chunks: list[dict[str, Any]] = []
    cursor = 0
    ordinal = 0
    while cursor < len(cleaned):
        end = min(len(cleaned), cursor + size)
        if end < len(cleaned):
            boundary = max(cleaned.rfind("\n\n", cursor, end), cleaned.rfind("\n", cursor, end), cleaned.rfind(" ", cursor, end))
            if boundary > cursor + size // 2:
                end = boundary
        raw = cleaned[cursor:end]
        lead = len(raw) - len(raw.lstrip())
        value = raw.strip()
        if value:
            start_offset = cursor + lead
            end_offset = start_offset + len(value)
            line_start = cleaned.count("\n", 0, start_offset) + 1
            line_end = cleaned.count("\n", 0, end_offset) + 1
            chunk_type = classify_chunk(value)
            section = next(
                (title for position, title in reversed(headings) if position <= start_offset),
                None,
            )
            if chunk_type == "heading":
                section = value.splitlines()[0].lstrip("#").strip()
            page_number = next(
                (page for page, span_start, span_end in spans if span_start <= start_offset < span_end),
                None,
            )
            chunks.append({
                "ordinal": ordinal,
                "text": value,
                "line_start": line_start,
                "line_end": line_end,
                "tokens": token_count(value),
                "chunk_type": chunk_type,
                "page_number": page_number,
                "section": section,
                "start_offset": start_offset,
                "end_offset": end_offset,
            })
            ordinal += 1
        if end >= len(cleaned):
            break
        cursor = max(end - overlap_value, cursor + 1)
    return chunks



def deterministic_vector(text: str, dimensions: int = 256) -> list[float]:
    """Compatibility vector used only when explicitly enabled for offline tests."""
    values = [0.0] * dimensions
    for token in re.findall(r"[\w-]+", text.lower()):
        digest = hashlib.blake2b(token.encode(), digest_size=8).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        values[index] += 1.0 if digest[4] & 1 else -1.0
    norm = math.sqrt(sum(value * value for value in values)) or 1.0
    return [value / norm for value in values]



def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    return sum(x * y for x, y in zip(a, b))



_QUERY_STOPWORDS = {
    # articles, prepositions, conjunctions, pronouns
    "the", "and", "or", "for", "with", "from", "that", "this", "these", "those",
    "of", "in", "on", "at", "to", "by", "as", "a", "an", "it", "its",
    "i", "me", "my", "we", "our", "you", "your", "he", "she", "they", "them",
    # interrogatives and auxiliaries that carry no retrieval signal
    "what", "which", "who", "whom", "whose", "why", "how", "when", "where",
    "is", "are", "was", "were", "be", "been", "being", "am", "do", "does", "did",
    "have", "has", "had", "can", "could", "would", "should", "will", "shall", "may",
    "many", "much", "there", "here", "about", "tell", "give", "please",
}



def query_terms(value: str) -> list[str]:
    """Content-bearing tokens used for BM25 and lexical relevance scoring."""
    return [
        term
        for term in re.findall(r"[A-Za-z0-9_]{2,}", value.lower())
        if term not in _QUERY_STOPWORDS
    ]



def fts_query(value: str) -> str:
    terms = query_terms(value)
    return " OR ".join('"' + term.replace('"', "") + '"' for term in terms[:24]) or '"__no_terms__"'



def understand_query(question: str) -> tuple[list[str], str]:
    """Cheap, deterministic query routing before retrieval."""
    plan = route_query(question)
    return plan.parts, plan.intent



_METADATA_CONTENT_MARKERS = re.compile(
    r"\b(?:mention|mentions|contain|contains|discuss|discusses|say|says|about|"
    r"explain|explains|summar|describ|compare|according)\w*\b",
    re.IGNORECASE,
)



_OVERVIEW_ASK = re.compile(
    r"\b(?:what(?:'s|\s+is|\s+are)?|summari[sz]e|summary|overview|describe|tell\s+me)\b",
    re.IGNORECASE,
)
_OVERVIEW_SUBJECT = re.compile(
    r"\b(?:all|each|every)\s+(?:of\s+)?(?:the\s+)?"
    r"(?:documents?|docs?|files?|pdfs?|papers?|sources?)\b"
    r"|\b(?:the|these|those|my|our)\s+"
    r"(?:documents?|docs?|files?|pdfs?|papers?|sources?|corpus|library)\b"
    r"|\b(?:corpus|library)\b",
    re.IGNORECASE,
)
_OVERVIEW_TOPIC = re.compile(
    r"\b(?:about|cover|covers|contain|contains|topics?)\b\s*[?.!]*\s*$",
    re.IGNORECASE,
)
_OVERVIEW_IMPLIED = re.compile(
    r"\b(?:summari[sz]e|summary|overview|describe)\b"
    r"|\btell\s+me\s+about\b",
    re.IGNORECASE,
)
_OVERVIEW_CONTENT_VERB = re.compile(
    r"\b(?:say|says|said|state|states|mention|mentions|discuss|discusses|explain|explains)\b",
    re.IGNORECASE,
)
_NAMED_DOCUMENT = re.compile(
    r"[\w.\-]+\.(?:pdf|md|markdown|txt|py|json|yaml|yml|csv|sql|html|"
    r"docx|xlsx|pptx|png|jpe?g|tiff?)\b",
    re.IGNORECASE,
)


def is_catalog_overview(question: str) -> bool:
    """True when the question asks what the whole catalog is about.

    Content questions such as "what does LoRA.pdf say about rank?" name a
    document or use a reporting verb, so they stay on the retrieval path.
    Overviews describe the catalog and can be answered from document metadata.
    """
    if _NAMED_DOCUMENT.search(question) or _OVERVIEW_CONTENT_VERB.search(question):
        return False
    if not (_OVERVIEW_ASK.search(question) and _OVERVIEW_SUBJECT.search(question)):
        return False
    if _OVERVIEW_IMPLIED.search(question):
        return True
    return bool(_OVERVIEW_TOPIC.search(question))


@dataclass
class QueryPlan:
    intent: str                      # metadata | figure | table | text
    document_ids: list[str]
    filters: dict[str, Any]          # filename, filenames, extension, ...
    parts: list[str]
    raw: str



def route_query(question: str) -> QueryPlan:
    """Waterfall router: regex identifiers first, then intent class.

    Emits structured filters consumed by retrieve() so the search space is
    constrained before scoring, not after.
    """
    clean = re.sub(r"\s+", " ", question.strip())
    lower = clean.casefold()

    structural = bool(
        re.search(
            r"\b(?:contain|containing|include|including|with|having)\b.{0,40}\b(?:tables?|figures?|images?)\b",
            lower,
        )
    )
    if is_catalog_overview(clean):
        intent = "metadata"
    elif re.search(
        r"\b(list|show|find|how\s+many|count|which|what|total)\b.*\b(documents?|files?|pages?)\b"
        r"|\b(?:total|number\s+of)\s+pages?\b",
        lower,
    ) and (not _METADATA_CONTENT_MARKERS.search(clean) or structural):
        intent = "metadata"
    elif re.search(r"\b(figure|image|diagram|chart|plot)\b", lower):
        intent = "figure"
    elif re.search(r"\b(table|row|column|sql|count|sum|average)\b", lower):
        intent = "table"
    else:
        intent = "text"

    document_ids = re.findall(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", lower
    )

    filters: dict[str, Any] = {}
    ext_group = "|".join(sorted(re.escape(item) for item in INGEST_EXTENSIONS))
    filenames: list[str] = []
    filename_pattern = re.compile(
        rf"[\"']([^\"']+\.(?:{ext_group}))[\"']|([\w.\-]+\.(?:{ext_group}))\b",
        re.IGNORECASE,
    )
    for match in filename_pattern.finditer(clean):
        name = (match.group(1) or match.group(2) or "").strip()
        if name:
            filenames.append(name)
    filenames = list(dict.fromkeys(filenames))
    if len(filenames) == 1:
        filters["filename"] = filenames[0]
    elif filenames:
        filters["filenames"] = filenames

    parts = [
        part.strip(" ,")
        for part in re.split(
            r"(?<=[?!.])\s+|;\s+|\s+(?:and|also)\s+(?=(?:how|what|which|why|where|when)\b)",
            clean,
            flags=re.IGNORECASE,
        )
        if part.strip()
    ]
    return QueryPlan(
        intent=intent,
        document_ids=document_ids,
        filters=filters,
        parts=parts[:4] or [clean],
        raw=clean,
    )



MONTH_NAMES = (
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
)



def is_metadata_question(question: str) -> bool:
    """True only for questions about the document catalog itself."""
    if is_catalog_overview(question):
        return True
    if not re.search(
        r"\b(?:documents?|files?|chunks?|corpus|catalog|library)\b|\b\s?sizes?\b|\bhow\s+big\b"
        r"|\b(?:how\s+many|total|number\s+of)\s+pages?\b",
        question,
        re.IGNORECASE,
    ):
        return False
    structural = re.search(
        r"\b(?:contain|containing|include|including|with|having)\b.{0,40}\b(?:tables?|figures?|images?)\b",
        question,
        re.IGNORECASE,
    )
    if _METADATA_CONTENT_MARKERS.search(question) and not structural:
        return False
    return bool(
        re.search(
            r"\b(?:list|show|find|how\s+many|count|which|what|name|names|status|size|"
            r"indexed|uploaded|with|having|containing|top|rank|ranked|order(?:ed)?|"
            r"sort(?:ed)?|average|mean|total|biggest|largest|smallest|fewest|least|"
            r"most|newest|latest|recent)\b",
            question,
            re.IGNORECASE,
        )
    )



def sanitize_evidence(text: str) -> tuple[str, bool]:
    """Redact obvious prompt-injection markers from retrieved text."""
    if not PROMPT_INJECTION_GUARD:
        return text, False
    flagged = False
    for pattern in INJECTION_PATTERNS:
        if pattern.search(text):
            text = pattern.sub("[REDACTED]", text)
            flagged = True
    return text, flagged



def is_combined_question(question: str) -> bool:
    """True when the question asks which document covers a topic *and* what it says."""
    return bool(
        re.search(
            r"\b(?:which|what|identify\s+the)\s+(?:document|documents|file|files|paper|papers|source|sources?)\b",
            question,
            re.IGNORECASE,
        )
        and _METADATA_CONTENT_MARKERS.search(question)
    )
