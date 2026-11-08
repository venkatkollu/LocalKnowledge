"""Index listing, creation and lifecycle endpoints."""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends

from ..auth import Principal, principal
from ..db import db
from ..indexes import index_action, index_public
from ..models import IndexCreate
from ..providers import choose_provider, embedding_identity
from ..utils import now_ms

router = APIRouter()


@router.get("/api/indexes")
def list_indexes(p: Principal = Depends(principal)) -> dict[str, Any]:
    with db() as connection:
        rows = connection.execute("SELECT * FROM index_versions WHERE workspace_id=? ORDER BY revision DESC", (p.workspace_id,)).fetchall()
    return {"indexes": [index_public(row) for row in rows]}



@router.post("/api/indexes", status_code=201)
def create_index(payload: IndexCreate, p: Principal = Depends(principal)) -> dict[str, Any]:
    with db() as connection:
        revision = (connection.execute("SELECT COALESCE(MAX(revision), 0) + 1 FROM index_versions WHERE workspace_id=?", (p.workspace_id,)).fetchone()[0])
        row_id = f"index-v{revision}-{uuid.uuid4().hex[:8]}"
        embedding_row = choose_provider(connection, p.workspace_id, "Embeddings")
        connection.execute("INSERT INTO index_versions(id, workspace_id, state, revision, embedding, created_at, notes) VALUES (?, ?, 'building', ?, ?, ?, ?)", (row_id, p.workspace_id, revision, payload.embedding or embedding_identity(embedding_row), now_ms(), payload.notes))
        row = connection.execute("SELECT * FROM index_versions WHERE id=?", (row_id,)).fetchone()
    return {"index": index_public(row)}



@router.post("/api/indexes/{index_id}/build")
def build_index(index_id: str, p: Principal = Depends(principal)) -> dict[str, Any]:
    return index_action(index_id, "build", p)



@router.post("/api/indexes/{index_id}/validate")
def validate_index(index_id: str, p: Principal = Depends(principal)) -> dict[str, Any]:
    return index_action(index_id, "validate", p)



@router.post("/api/indexes/{index_id}/evaluate")
def evaluate_index(index_id: str, p: Principal = Depends(principal)) -> dict[str, Any]:
    return index_action(index_id, "evaluate", p)



@router.post("/api/indexes/{index_id}/activate")
def activate_index(index_id: str, p: Principal = Depends(principal)) -> dict[str, Any]:
    return index_action(index_id, "activate", p)



@router.post("/api/indexes/{index_id}/rollback")
def rollback_index(index_id: str, p: Principal = Depends(principal)) -> dict[str, Any]:
    return index_action(index_id, "rollback", p)
