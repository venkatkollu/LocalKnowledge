"""Structure-aware chunking for ingestion.

The heavy lifting lives in :func:`backend.utils.split_chunks`, which already
keeps character offsets, line numbers, page spans, heading breadcrumbs and a
content type for every chunk. This module adapts those dictionaries to the
``ChunkInfo`` contract used by the ingestion pipeline.

Keeping one splitter implementation means retrieval metadata and the API
cannot drift apart.
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import CHUNK_OVERLAP, CHUNK_SIZE
from .utils import split_chunks

CHUNK_TYPES = frozenset({"text", "heading", "table", "figure", "list", "code", "equation"})


@dataclass(frozen=True)
class ChunkInfo:
    chunk_id: str
    document_id: str | None = None
    ordinal: int = 0
    text: str = ""
    line_start: int = 0
    line_end: int = 0
    tokens: int = 0
    chunk_type: str = "text"
    section_path: str = ""
    page_number: int | None = None
    start_offset: int = 0
    end_offset: int = 0


class StructureAwareChunker:
    """Split text at semantic boundaries and preserve location metadata."""

    def __init__(self, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> None:
        self.chunk_size = chunk_size
        self.overlap = overlap

    def chunk(
        self,
        text: str,
        document_id: str | None = None,
        page_spans: list[tuple[int, int, int]] | None = None,
    ) -> list[ChunkInfo]:
        pieces = split_chunks(
            text,
            page_spans=page_spans,
            chunk_size=self.chunk_size,
            overlap=self.overlap,
        )
        return [
            ChunkInfo(
                chunk_id=f"{document_id}-{piece['ordinal']}" if document_id else f"chunk-{piece['ordinal']}",
                document_id=document_id,
                ordinal=piece["ordinal"],
                text=piece["text"],
                line_start=piece["line_start"],
                line_end=piece["line_end"],
                tokens=piece["tokens"],
                chunk_type=piece["chunk_type"] if piece["chunk_type"] in CHUNK_TYPES else "text",
                section_path=piece.get("section") or "",
                page_number=piece.get("page_number"),
                start_offset=piece["start_offset"],
                end_offset=piece["end_offset"],
            )
            for piece in pieces
        ]


__all__ = ["CHUNK_TYPES", "ChunkInfo", "StructureAwareChunker"]
