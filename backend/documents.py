"""Document catalog rows and API serialization."""
from __future__ import annotations

import sqlite3
from typing import Any

from .utils import utc_iso


def row_document(row: sqlite3.Row) -> dict[str, Any]:
    """Canonical document metadata. Descriptive aliases mirror the ingest
    contract (file_type, file_size, page_count, ...) while the original field
    names stay for existing clients."""
    return {
        "id": row["id"], "document_id": row["id"], "filename": row["filename"], "path": row["path"], "extension": row["extension"],
        "language": row["language"], "size_bytes": row["size_bytes"], "chunks": 0, "status": row["status"],
        "updated_at": row["updated_at"], "indexed_at": row["indexed_at"], "version": row["version"],
        "content_hash": row["content_hash"], "parser": row["parser"], "chunker": row["chunker"],
        "embedding": row["embedding"], "error": row["error"], "progress": row["progress"], "stage": row["stage"],
        "pages": row["pages"], "title": row["title"], "author": row["author"],
        "uploaded_at": row["uploaded_at"],
        "file_type": row["extension"], "file_size": row["size_bytes"], "file_hash": row["content_hash"],
        "upload_date": utc_iso(row["uploaded_at"]), "page_count": row["pages"],
        "processing_status": row["status"], "total_chunks": 0,
    }



def document_row(connection: sqlite3.Connection, workspace_id: str, document_id: str) -> sqlite3.Row | None:
    return connection.execute("SELECT d.*, (SELECT COUNT(*) FROM chunks c WHERE c.document_id=d.id AND c.superseded=0) AS chunks FROM documents d WHERE d.workspace_id=? AND d.id=? AND d.deleted_at IS NULL", (workspace_id, document_id)).fetchone()
