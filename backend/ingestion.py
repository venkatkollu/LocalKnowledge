"""Upload storage, job queue and the ingestion pipeline."""
from __future__ import annotations

import hashlib
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from fastapi import HTTPException, UploadFile

from . import providers, runtime
from .config import CHUNK_OVERLAP, CHUNK_SIZE, SETTINGS
from .db import db
from .documents import document_row, row_document
from .indexes import active_index, refresh_index_membership
from .chunking import StructureAwareChunker
from .parsing import extract_document
from .providers import choose_provider, embedding_identity
from .security import PRIVATE_FILE_MODE, ensure_private_dir, set_private_mode
from .utils import (
    content_hash,
    extension,
    json_dumps,
    language_for,
    now_ms,
    safe_filename,
)


def set_job(connection: sqlite3.Connection, job_id: str, **fields: Any) -> None:
    assignments = ", ".join(f"{key}=?" for key in fields)
    values = list(fields.values()) + [now_ms(), job_id]
    connection.execute(f"UPDATE jobs SET {assignments}, updated_at=? WHERE id=?", values)



def clear_resolved_failures(connection: sqlite3.Connection, workspace_id: str, document_id: str, job_id: str) -> None:
    """Drop earlier failed attempts once a document ingests successfully."""
    connection.execute(
        "DELETE FROM jobs WHERE workspace_id=? AND document_id=? AND id<>? AND status IN ('failed', 'cancelled')",
        (workspace_id, document_id, job_id),
    )



def emit_event(workspace_id: str, kind: str, title: str, detail: str | None = None, document_id: str | None = None, trace_id: str | None = None) -> None:
    with db() as connection:
        connection.execute("INSERT INTO events(id, workspace_id, kind, title, detail, document_id, trace_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (str(uuid.uuid4()), workspace_id, kind, title, detail, document_id, trace_id, now_ms()))



def purge_document(connection: sqlite3.Connection, workspace_id: str, document_id: str) -> None:
    """Remove a document and every database trace of it."""
    connection.execute("DELETE FROM chunks_fts WHERE document_id=? AND workspace_id=?", (document_id, workspace_id))
    connection.execute("DELETE FROM index_chunk_embeddings WHERE chunk_id IN (SELECT id FROM chunks WHERE document_id=?)", (document_id,))
    connection.execute("DELETE FROM index_chunks WHERE chunk_id IN (SELECT id FROM chunks WHERE document_id=?)", (document_id,))
    connection.execute("DELETE FROM chunks WHERE document_id=?", (document_id,))
    connection.execute("DELETE FROM document_versions WHERE document_id=?", (document_id,))
    connection.execute("DELETE FROM jobs WHERE document_id=?", (document_id,))
    connection.execute("DELETE FROM documents WHERE id=?", (document_id,))
    connection.execute("DELETE FROM cache_entries WHERE workspace_id=?", (workspace_id,))



def reconcile_missing_documents(workspace_id: str) -> list[str]:
    """Vacuum documents whose original file disappeared from storage.

    Live rows whose source file is gone are hard-removed; soft-deleted rows
    are dropped as well once their storage file is missing. Keeps the catalog
    clean instead of leaving documents stuck in a failed state that retried
    jobs cannot resolve. Rows, chunks, index membership, job history and
    cached answers are cleared together.
    """
    removed: list[str] = []
    with db() as connection:
        for row in connection.execute(
            "SELECT id, filename, storage_path, deleted_at FROM documents WHERE workspace_id=?",
            (workspace_id,),
        ).fetchall():
            if Path(row["storage_path"]).exists():
                continue
            purge_document(connection, workspace_id, row["id"])
            removed.append(row["filename"])
    if removed:
        emit_event(workspace_id, "document", f"{len(removed)} document(s) removed", "Original files missing from storage; chunks and index rows cleared")
    return removed



def process_job(job_id: str) -> None:
    with db() as connection:
        job = connection.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if job is None or not job["document_id"]:
        return
    workspace_id = job["workspace_id"]
    document_id = job["document_id"]
    try:
        with db() as connection:
            document = document_row(connection, workspace_id, document_id)
            if document is None:
                raise RuntimeError("Document not found")
            set_job(connection, job_id, status="running", stage="parsing", progress=0.05)
            connection.execute("UPDATE documents SET status='processing', stage='parsing', progress=0.05, error=NULL WHERE id=?", (document_id,))
        if not Path(document["storage_path"]).exists():
            # The original file is gone; a retry could never succeed. Drop the
            # document and all of its rows so the queue stays meaningful.
            emit_event(workspace_id, "document", f"{document['filename']} removed", "Original file missing from storage; chunks cleared")
            with db() as connection:
                purge_document(connection, workspace_id, document_id)
            return
        source = Path(document["path"]) / document["filename"] if Path(document["path"]).is_absolute() else None
        if source and source.exists() and source.resolve() != Path(document["storage_path"]).resolve():
            live_digest = content_hash(source)
            if live_digest != document["content_hash"]:
                copied, live_size, _ = save_local_file(source, workspace_id)
                with db() as connection:
                    connection.execute("UPDATE documents SET storage_path=?, size_bytes=?, content_hash=?, status='changed', updated_at=? WHERE id=?", (str(copied), live_size, live_digest, now_ms(), document_id))
                with db() as connection:
                    document = document_row(connection, workspace_id, document_id)
        extracted = extract_document(Path(document["storage_path"]), document["filename"])
        text = extracted.text
        pages = extracted.pages
        chunker = StructureAwareChunker(chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP)
        chunk_infos = chunker.chunk(
            text,
            document_id=document_id,
            page_spans=extracted.page_spans or None,
        )
        chunks = [
            {
                "chunk_id": c.chunk_id,
                "text": c.text,
                "ordinal": c.ordinal,
                "line_start": c.line_start,
                "line_end": c.line_end,
                "section": c.section_path,
                "chunk_type": c.chunk_type,
                "page_number": c.page_number,
                "start_offset": c.start_offset,
                "end_offset": c.end_offset,
                "tokens": c.tokens,
            }
            for c in chunk_infos
        ]
        with db() as connection:
            set_job(connection, job_id, stage="structure", progress=0.18)
            connection.execute("UPDATE documents SET stage='structure', progress=0.18 WHERE id=?", (document_id,))
            set_job(connection, job_id, stage="chunking", progress=0.32)
            connection.execute("UPDATE documents SET stage='chunking', progress=0.32 WHERE id=?", (document_id,))
            current = connection.execute("SELECT version, content_hash FROM documents WHERE id=?", (document_id,)).fetchone()
            if current is None:
                raise RuntimeError("Document not found")
            version = int(current["version"]) + 1
            embedding_row = choose_provider(connection, workspace_id, "Embeddings")
            previous_chunk_ids = [row["id"] for row in connection.execute("SELECT id FROM chunks WHERE document_id=? AND superseded=0", (document_id,)).fetchall()]
            content_hash_for_version = current["content_hash"]

        # Embedding calls can take seconds (or longer). Never keep a SQLite
        # transaction open while waiting on Ollama or a remote provider.
        embedding_row = dict(embedding_row) if embedding_row is not None else None
        with db() as connection:
            set_job(connection, job_id, stage="embedding", progress=0.58)
            connection.execute("UPDATE documents SET stage='embedding', progress=0.58, embedding=? WHERE id=?", (embedding_identity(embedding_row), document_id))
        embedded_chunks = [(chunk, providers.embed_text(embedding_row, chunk["text"])) for chunk in chunks]

        with db() as connection:
            current = connection.execute("SELECT version, content_hash FROM documents WHERE id=?", (document_id,)).fetchone()
            if current is None or int(current["version"]) != version - 1 or current["content_hash"] != content_hash_for_version:
                raise RuntimeError("Document changed while it was being indexed; please retry")
            connection.execute("UPDATE document_versions SET current=0 WHERE document_id=?", (document_id,))
            for chunk, vector in embedded_chunks:
                chunk_id = str(uuid.uuid4())
                connection.execute(
                    "INSERT INTO chunks(id, workspace_id, document_id, version, ordinal, text, line_start, line_end, section, chunk_type, page_number, start_offset, end_offset, tokens, embedding_json) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        chunk_id, workspace_id, document_id, version, chunk["ordinal"], chunk["text"],
                        chunk["line_start"], chunk["line_end"], chunk.get("section"),
                        chunk.get("chunk_type", "text"), chunk.get("page_number"),
                        chunk.get("start_offset"), chunk.get("end_offset"), chunk["tokens"],
                        json_dumps(vector),
                    ),
                )
                connection.execute("INSERT INTO chunks_fts(text, chunk_id, workspace_id, document_id) VALUES (?, ?, ?, ?)", (chunk["text"], chunk_id, workspace_id, document_id))
            if previous_chunk_ids:
                connection.executemany("UPDATE chunks SET superseded=1 WHERE id=?", [(chunk_id,) for chunk_id in previous_chunk_ids])
                connection.executemany("DELETE FROM chunks_fts WHERE chunk_id=?", [(chunk_id,) for chunk_id in previous_chunk_ids])
            # Keep the live index aligned without waiting for a manual rebuild.
            # Candidate indexes remain isolated snapshots until activation.
            active = active_index(connection, workspace_id)
            if active is not None:
                refresh_index_membership(connection, workspace_id, active["id"])
            # New or changed chunks invalidate cached answers for this workspace.
            connection.execute("DELETE FROM cache_entries WHERE workspace_id=?", (workspace_id,))
            set_job(connection, job_id, stage="indexing", progress=0.78)
            connection.execute("UPDATE documents SET stage='indexing', progress=0.78 WHERE id=?", (document_id,))
            connection.execute("INSERT INTO document_versions(id, workspace_id, document_id, version, content_hash, created_at, chunks, reused, newly_embedded, note) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (str(uuid.uuid4()), workspace_id, document_id, version, content_hash_for_version, now_ms(), len(chunks), 0, len(chunks), "Initial ingestion" if version == 1 else "Incremental update"))
            set_job(connection, job_id, stage="validating", progress=0.93)
            connection.execute("UPDATE documents SET stage='validating', progress=0.93 WHERE id=?", (document_id,))
            connection.execute("UPDATE documents SET status='synced', stage=NULL, progress=NULL, indexed_at=?, version=?, parser=?, chunker=?, pages=?, title=?, author=?, error=NULL WHERE id=?", (now_ms(), version, f"{extension(document['filename']) or 'text'}-v1", f"fixed-{CHUNK_SIZE}-{CHUNK_OVERLAP}", pages, extracted.title or document["title"] or Path(document["filename"]).stem, extracted.author, document_id))
            set_job(connection, job_id, status="completed", stage="completed", progress=1)
            clear_resolved_failures(connection, workspace_id, document_id, job_id)
        emit_event(workspace_id, "sync", f"{document['filename']} indexed", f"{len(chunks)} chunks", document_id=document_id)
    except Exception as exc:
        with db() as connection:
            set_job(connection, job_id, status="failed", stage="failed", progress=1, last_error=str(exc))
            connection.execute("UPDATE documents SET status='failed', stage=NULL, progress=NULL, error=? WHERE id=?", (str(exc), document_id))
        emit_event(workspace_id, "error", "Ingestion failed", str(exc), document_id=document_id)



def save_upload(upload: UploadFile, workspace_id: str) -> tuple[Path, int, str]:
    target_dir = SETTINGS.files_dir / workspace_id
    ensure_private_dir(target_dir)
    target = target_dir / f"{uuid.uuid4()}-{safe_filename(upload.filename or 'upload')}"
    digest = hashlib.sha256()
    total = 0
    with target.open("wb") as handle:
        set_private_mode(target, PRIVATE_FILE_MODE)
        while True:
            block = upload.file.read(1024 * 1024)
            if not block:
                break
            total += len(block)
            if total > SETTINGS.max_upload_bytes:
                target.unlink(missing_ok=True)
                raise HTTPException(413, f"File exceeds {SETTINGS.max_upload_bytes} bytes")
            digest.update(block)
            handle.write(block)
    return target, total, digest.hexdigest()



def save_local_file(source: Path, workspace_id: str) -> tuple[Path, int, str]:
    """Copy a local source into workspace storage while hashing it in one pass."""
    target_dir = SETTINGS.files_dir / workspace_id
    ensure_private_dir(target_dir)
    target = target_dir / f"{uuid.uuid4()}-{safe_filename(source.name)}"
    digest = hashlib.sha256()
    total = 0
    try:
        with source.open("rb") as source_handle, target.open("wb") as target_handle:
            set_private_mode(target, PRIVATE_FILE_MODE)
            for block in iter(lambda: source_handle.read(1024 * 1024), b""):
                total += len(block)
                if total > SETTINGS.max_upload_bytes:
                    raise HTTPException(413, f"File exceeds {SETTINGS.max_upload_bytes} bytes")
                digest.update(block)
                target_handle.write(block)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return target, total, digest.hexdigest()



def queue_document(workspace_id: str, filename: str, path: Path, size: int, digest: str, source_path: str = "Uploads") -> tuple[dict[str, Any], dict[str, Any] | None]:
    timestamp = now_ms()
    with db() as connection:
        source_existing = connection.execute("SELECT * FROM documents WHERE workspace_id=? AND path=? AND filename=? AND deleted_at IS NULL ORDER BY updated_at DESC LIMIT 1", (workspace_id, source_path, filename)).fetchone()
        if source_existing:
            if source_existing["content_hash"] == digest:
                return row_document(source_existing), None
            hash_owner = connection.execute("SELECT * FROM documents WHERE workspace_id=? AND content_hash=? AND deleted_at IS NULL AND id!=?", (workspace_id, digest, source_existing["id"])).fetchone()
            if hash_owner:
                return row_document(hash_owner), None
            document_id = source_existing["id"]
            connection.execute("UPDATE documents SET storage_path=?, size_bytes=?, content_hash=?, status='changed', updated_at=?, error=NULL, progress=NULL, stage=NULL WHERE id=?", (str(path), size, digest, timestamp, document_id))
            idempotency_key = f"ingest:{document_id}:{digest}"
            job_id = str(uuid.uuid4())
            connection.execute("INSERT INTO jobs(id, workspace_id, document_id, kind, status, stage, idempotency_key, created_at, updated_at) VALUES (?, ?, ?, 'ingest', 'queued', 'parsing', ?, ?, ?)", (job_id, workspace_id, document_id, idempotency_key, timestamp, timestamp))
            document = connection.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()
            job = connection.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            submit_job = job_id
        else:
            submit_job = None
        existing = connection.execute("SELECT * FROM documents WHERE workspace_id=? AND content_hash=?", (workspace_id, digest)).fetchone()
        if source_existing:
            pass
        elif existing and existing["deleted_at"] is None:
            return row_document(existing), None
        elif existing:
            document_id = existing["id"]
            connection.execute("UPDATE documents SET filename=?, path=?, storage_path=?, extension=?, language=?, size_bytes=?, status='not_indexed', updated_at=?, deleted_at=NULL, error=NULL, progress=NULL, stage=NULL WHERE id=?", (filename, source_path, str(path), extension(filename), language_for(filename), size, timestamp, document_id))
            idempotency_key = f"ingest:{digest}:{timestamp}"
            job_id = str(uuid.uuid4())
            connection.execute("INSERT INTO jobs(id, workspace_id, document_id, kind, status, stage, idempotency_key, created_at, updated_at) VALUES (?, ?, ?, 'ingest', 'queued', 'parsing', ?, ?, ?)", (job_id, workspace_id, document_id, idempotency_key, timestamp, timestamp))
            document = connection.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()
            job = connection.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            submit_job = job_id
        elif not source_existing:
            document_id = str(uuid.uuid4())
            connection.execute("INSERT INTO documents(id, workspace_id, filename, path, storage_path, extension, language, size_bytes, content_hash, status, title, uploaded_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'not_indexed', ?, ?, ?)", (document_id, workspace_id, filename, source_path, str(path), extension(filename), language_for(filename), size, digest, Path(filename).stem, timestamp, timestamp))
            idempotency_key = f"ingest:{digest}"
            job_id = str(uuid.uuid4())
            connection.execute("INSERT INTO jobs(id, workspace_id, document_id, kind, status, stage, idempotency_key, created_at, updated_at) VALUES (?, ?, ?, 'ingest', 'queued', 'parsing', ?, ?, ?)", (job_id, workspace_id, document_id, idempotency_key, timestamp, timestamp))
            document = connection.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()
            job = connection.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            submit_job = job_id
    runtime.EXECUTOR.submit(process_job, submit_job)
    return row_document(document), dict(job)



def job_public(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    get = row.__getitem__
    return {"id": get("id"), "document_id": get("document_id"), "document_name": get("document_name") if "document_name" in row.keys() else None, "stage": get("stage"), "status": get("status"), "progress": get("progress"), "error": get("last_error")}



def enqueue_existing(workspace_id: str, document_id: str, kind: str) -> dict[str, Any]:
    timestamp = now_ms()
    with db() as connection:
        document = document_row(connection, workspace_id, document_id)
        if document is None:
            raise HTTPException(404, "Document not found")
        key = f"{kind}:{document_id}:{document['content_hash']}"
        current = connection.execute("SELECT * FROM jobs WHERE workspace_id=? AND idempotency_key=?", (workspace_id, key)).fetchone()
        if current and current["status"] in {"queued", "running"}:
            return job_public(current)
        if current and current["status"] == "failed":
            # A previously failed job must always be retried, even when the
            # source bytes are unchanged. Returning the failed row made Retry
            # a no-op for documents whose embedding provider was broken.
            key = f"{key}:{timestamp}"
        elif current and kind == "sync":
            source = Path(document["path"]) / document["filename"] if Path(document["path"]).is_absolute() else Path(document["storage_path"])
            if not source.exists() or content_hash(source) == document["content_hash"]:
                return job_public(current)
            key = f"{key}:{timestamp}"
        elif current:
            key = f"{key}:{timestamp}"
        job_id = str(uuid.uuid4())
        connection.execute("INSERT INTO jobs(id, workspace_id, document_id, kind, status, stage, idempotency_key, created_at, updated_at) VALUES (?, ?, ?, ?, 'queued', 'parsing', ?, ?, ?)", (job_id, workspace_id, document_id, kind, key, timestamp, timestamp))
        job = connection.execute("SELECT j.*, d.filename AS document_name FROM jobs j LEFT JOIN documents d ON d.id=j.document_id WHERE j.id=?", (job_id,)).fetchone()
    runtime.EXECUTOR.submit(process_job, job_id)
    return job_public(job)
