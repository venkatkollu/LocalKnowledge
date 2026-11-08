"""Document catalog, upload, sync, job and repository endpoints."""
from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi import Request as FastAPIRequest

from ..auth import Principal, principal
from ..config import INGEST_EXTENSIONS, MAX_BATCH_FILES
from ..db import db
from ..documents import document_row, row_document
from ..ingestion import (
    emit_event,
    enqueue_existing,
    job_public,
    queue_document,
    reconcile_missing_documents,
    save_local_file,
    save_upload,
)
from ..models import SyncRequest
from ..parsing import read_document_text
from ..utils import extension, now_ms, safe_filename

router = APIRouter()


@router.get("/api/documents")
def list_documents(p: Principal = Depends(principal)) -> dict[str, Any]:
    reconcile_missing_documents(p.workspace_id)
    with db() as connection:
        rows = connection.execute("SELECT d.*, (SELECT COUNT(*) FROM chunks c WHERE c.document_id=d.id AND c.superseded=0) AS chunks FROM documents d WHERE d.workspace_id=? AND d.deleted_at IS NULL ORDER BY d.updated_at DESC", (p.workspace_id,)).fetchall()
        return {"documents": [row_document(row) | {"chunks": row["chunks"], "total_chunks": row["chunks"]} for row in rows]}



@router.post("/api/documents")
async def upload_documents(
    request: FastAPIRequest,
    files: list[UploadFile] = File(default=[]),
    p: Principal = Depends(principal),
) -> dict[str, Any]:
    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" not in content_type:
        body = await request.json()
        source = Path(str(body.get("path", "")).strip()).expanduser()
        try:
            source = source.resolve(strict=True)
        except FileNotFoundError as exc:
            raise HTTPException(400, "Folder path does not exist") from exc
        if not source.is_dir():
            raise HTTPException(400, "Folder path must point to a directory")
        candidates: list[Path] = []
        for item in source.rglob("*"):
            if item.is_file() and not item.is_symlink() and extension(item.name) in INGEST_EXTENSIONS:
                candidates.append(item)
                if len(candidates) > MAX_BATCH_FILES:
                    raise HTTPException(413, f"Folder contains more than {MAX_BATCH_FILES} supported files")
        jobs: list[dict[str, Any]] = []
        accepted: list[str] = []
        for item in candidates:
            try:
                stored, size, digest = save_local_file(item, p.workspace_id)
                document, job = queue_document(p.workspace_id, safe_filename(item.name), stored, size, digest, str(item.parent))
                if job:
                    jobs.append(job_public(job))
                    accepted.append(document["filename"])
                else:
                    stored.unlink(missing_ok=True)
            except HTTPException:
                raise
            except OSError as exc:
                raise HTTPException(400, f"Could not read {item.name}: {exc}") from exc
        return {"accepted": accepted, "jobs": jobs, "files_seen": len(candidates)}
        
    jobs: list[dict[str, Any]] = []
    accepted: list[str] = []
    if len(files) > MAX_BATCH_FILES:
        raise HTTPException(413, f"Upload contains more than {MAX_BATCH_FILES} files")
    for upload in files:
        path, size, digest = save_upload(upload, p.workspace_id)
        document, job = queue_document(p.workspace_id, safe_filename(upload.filename or "upload"), path, size, digest)
        accepted.append(document["filename"])
        if job:
            jobs.append(job_public(job))
        else:
            path.unlink(missing_ok=True)
    return {"accepted": accepted, "jobs": jobs}



@router.get("/api/documents/{document_id}")
def get_document(document_id: str, p: Principal = Depends(principal)) -> dict[str, Any]:
    with db() as connection:
        row = document_row(connection, p.workspace_id, document_id)
        if row is None:
            raise HTTPException(404, "Document not found")
        chunks = connection.execute("SELECT id, document_id, ordinal, line_start, line_end, section, symbol, chunk_type, page_number, start_offset, end_offset, tokens, text FROM chunks WHERE workspace_id=? AND document_id=? AND superseded=0 ORDER BY ordinal", (p.workspace_id, document_id)).fetchall()
        versions = connection.execute("SELECT version, chunks, created_at, current, content_hash, reused, newly_embedded, note FROM document_versions WHERE workspace_id=? AND document_id=? ORDER BY version DESC", (p.workspace_id, document_id)).fetchall()
    text = read_document_text(Path(row["storage_path"]), row["filename"])
    return {
        "document": row_document(row) | {"chunks": row["chunks"], "total_chunks": row["chunks"]},
        "content": text,
        "chunks": [
            {
                "id": c["id"], "chunk_id": c["id"], "document_id": c["document_id"],
                "index": c["ordinal"], "chunk_index": c["ordinal"],
                "line_start": c["line_start"], "line_end": c["line_end"],
                "section": c["section"], "section_title": c["section"], "symbol": c["symbol"],
                "chunk_type": c["chunk_type"] or "text", "page_number": c["page_number"],
                "start_offset": c["start_offset"], "end_offset": c["end_offset"],
                "tokens": c["tokens"], "excerpt": c["text"], "content": c["text"],
            }
            for c in chunks
        ],
        "versions": [dict(v) for v in versions],
    }



@router.delete("/api/documents/{document_id}", status_code=202)
def delete_document(document_id: str, p: Principal = Depends(principal)) -> dict[str, Any]:
    with db() as connection:
        row = document_row(connection, p.workspace_id, document_id)
        if row is None:
            raise HTTPException(404, "Document not found")
        connection.execute("UPDATE documents SET deleted_at=?, status='processing' WHERE id=?", (now_ms(), document_id))
        connection.execute("DELETE FROM chunks_fts WHERE document_id=? AND workspace_id=?", (document_id, p.workspace_id))
        connection.execute("UPDATE chunks SET superseded=1 WHERE document_id=?", (document_id,))
        connection.execute("DELETE FROM cache_entries WHERE workspace_id=?", (p.workspace_id,))
    emit_event(p.workspace_id, "document", f"{row['filename']} deleted")
    return {"accepted": True, "document_id": document_id}



@router.delete("/api/documents/{document_id}/chunks", status_code=202)
def clear_document_chunks(document_id: str, p: Principal = Depends(principal)) -> dict[str, Any]:
    with db() as connection:
        row = document_row(connection, p.workspace_id, document_id)
        if row is None:
            raise HTTPException(404, "Document not found")
        removed = connection.execute("SELECT COUNT(*) FROM chunks WHERE document_id=? AND superseded=0", (document_id,)).fetchone()[0]
        connection.execute("DELETE FROM chunks_fts WHERE document_id=? AND workspace_id=?", (document_id, p.workspace_id))
        connection.execute("DELETE FROM chunks WHERE document_id=?", (document_id,))
        connection.execute("DELETE FROM cache_entries WHERE workspace_id=?", (p.workspace_id,))
        connection.execute("UPDATE documents SET status='not_indexed', version=0, embedding=NULL, parser=NULL, chunker=NULL, indexed_at=NULL, stage=NULL, progress=NULL, error=NULL, updated_at=? WHERE id=?", (now_ms(), document_id))
    emit_event(p.workspace_id, "document", f"{row['filename']} chunks removed", str(removed))
    return {"accepted": True, "document_id": document_id, "removed_chunks": removed}



@router.post("/api/documents/reconcile")
def reconcile_documents(p: Principal = Depends(principal)) -> dict[str, Any]:
    removed = reconcile_missing_documents(p.workspace_id)
    return {"accepted": True, "removed": removed, "count": len(removed)}



@router.get("/api/changes/latest")
def latest_changes(p: Principal = Depends(principal)) -> dict[str, Any]:
    with db() as connection:
        rows = connection.execute("SELECT d.id AS document_id, d.filename, d.path, d.updated_at AS changed_at, d.version AS current_version, 0 AS previous_version, 0 AS previous_chunks, (SELECT COUNT(*) FROM chunks c WHERE c.document_id=d.id AND c.superseded=0) AS current_chunks FROM documents d WHERE d.workspace_id=? AND d.status='changed' AND d.deleted_at IS NULL ORDER BY d.updated_at DESC", (p.workspace_id,)).fetchall()
    return {"changes": [dict(row) for row in rows]}



@router.get("/api/jobs/{job_id}")
def get_job(job_id: str, p: Principal = Depends(principal)) -> dict[str, Any]:
    with db() as connection:
        row = connection.execute("SELECT j.*, d.filename AS document_name FROM jobs j LEFT JOIN documents d ON d.id=j.document_id WHERE j.workspace_id=? AND j.id=?", (p.workspace_id, job_id)).fetchone()
    if row is None:
        raise HTTPException(404, "Job not found")
    return job_public(row)



@router.delete("/api/jobs/{job_id}", status_code=202)
def cancel_job(job_id: str, p: Principal = Depends(principal)) -> dict[str, Any]:
    with db() as connection:
        row = connection.execute("SELECT j.*, d.filename AS document_name FROM jobs j LEFT JOIN documents d ON d.id=j.document_id WHERE j.workspace_id=? AND j.id=?", (p.workspace_id, job_id)).fetchone()
    if row is None:
        raise HTTPException(404, "Job not found")
    if row["status"] not in {"queued", "running"}:
        raise HTTPException(409, f"Job is already {row['status']}; only queued or running jobs can be cancelled")
    with db() as connection:
        connection.execute("UPDATE jobs SET status='cancelled', stage='failed', progress=0, last_error='Cancelled by user' WHERE id=?", (job_id,))
        # Reset the associated document so it is not left stuck in processing.
        if row["document_id"]:
            connection.execute("UPDATE documents SET status='not_indexed', stage=NULL, progress=NULL, error=NULL WHERE id=? AND workspace_id=?", (row["document_id"], p.workspace_id))
    emit_event(p.workspace_id, "error", f"{row['document_name'] or 'Job'} cancelled", job_id=job_id, document_id=row["document_id"])
    return {"accepted": True, "job_id": job_id}



@router.get("/api/sync")
def sync_queue(p: Principal = Depends(principal)) -> dict[str, Any]:
    # Only surface work that still needs attention. Historical failures for a
    # document that has since synced (or a failure that a newer attempt
    # replaced) are not part of the queue.
    with db() as connection:
        rows = connection.execute(
            "SELECT j.*, d.filename AS document_name FROM jobs j "
            "LEFT JOIN documents d ON d.id=j.document_id "
            "WHERE j.workspace_id=? AND j.status IN ('queued', 'running', 'failed') "
            "AND (j.status <> 'failed' OR (d.status='failed' AND d.deleted_at IS NULL "
            "AND j.id=(SELECT x.id FROM jobs x WHERE x.workspace_id=j.workspace_id "
            "AND x.document_id=j.document_id AND x.status='failed' "
            "ORDER BY x.created_at DESC LIMIT 1))) "
            "ORDER BY j.created_at DESC LIMIT 200",
            (p.workspace_id,),
        ).fetchall()
    return {"jobs": [job_public(row) for row in rows]}



@router.post("/api/documents/sync")
def sync_documents(payload: SyncRequest, p: Principal = Depends(principal)) -> dict[str, Any]:
    if payload.document_id:
        return {"job": enqueue_existing(p.workspace_id, payload.document_id, "sync")}
    with db() as connection:
        ids = [row["id"] for row in connection.execute("SELECT id FROM documents WHERE workspace_id=? AND deleted_at IS NULL", (p.workspace_id,)).fetchall()]
    jobs = [enqueue_existing(p.workspace_id, document_id, "sync") for document_id in ids]
    return {"jobs": jobs}



@router.post("/api/documents/index")
def index_document(payload: SyncRequest, p: Principal = Depends(principal)) -> dict[str, Any]:
    if not payload.document_id:
        raise HTTPException(400, "document_id is required")
    return {"job": enqueue_existing(p.workspace_id, payload.document_id, "index")}



@router.post("/api/repositories/git", status_code=202)
def git_repository(payload: dict[str, Any], p: Principal = Depends(principal)) -> dict[str, Any]:
    url = str(payload.get("url", ""))
    if not re.fullmatch(r"https://[^\s]+", url):
        raise HTTPException(400, "Only HTTPS repository URLs are accepted")
    branch = str(payload.get("branch") or "").strip()
    if branch and not re.fullmatch(r"[A-Za-z0-9._/-]{1,200}", branch):
        raise HTTPException(400, "Invalid branch name")
    with tempfile.TemporaryDirectory(prefix="knowledgeos-git-") as directory:
        clone_target = Path(directory) / "repo"
        command = ["git", "clone", "--depth", "1"]
        if branch:
            command.extend(["--branch", branch])
        command.extend([url, str(clone_target)])
        try:
            subprocess.run(command, check=True, capture_output=True, text=True, timeout=180)
            commit = subprocess.run(["git", "-C", str(clone_target), "rev-parse", "HEAD"], check=True, capture_output=True, text=True, timeout=15).stdout.strip()
        except FileNotFoundError as exc:
            raise HTTPException(503, "Git is not installed on the backend host") from exc
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or "git clone failed").strip()[-1000:]
            raise HTTPException(502, detail) from exc
        except subprocess.TimeoutExpired as exc:
            raise HTTPException(504, "Git clone timed out") from exc
        files = [item for item in clone_target.rglob("*") if item.is_file() and not item.is_symlink() and ".git" not in item.parts and extension(item.name) in INGEST_EXTENSIONS]
        if len(files) > MAX_BATCH_FILES:
            raise HTTPException(413, f"Repository contains more than {MAX_BATCH_FILES} supported files")
        jobs: list[dict[str, Any]] = []
        for item in files:
            stored, size, digest = save_local_file(item, p.workspace_id)
            relative_parent = str(item.parent.relative_to(clone_target)) if item.parent != clone_target else "."
            document, job = queue_document(p.workspace_id, safe_filename(item.name), stored, size, digest, f"git:{url}#{relative_parent}")
            if job:
                jobs.append(job_public(job))
            else:
                stored.unlink(missing_ok=True)
    return {"accepted": True, "files": len(files), "commit": commit, "jobs": jobs}
