"""Golden-set, feedback and claim-verification endpoints."""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ..auth import Principal, principal
from ..db import db
from ..models import FeedbackRequest, GoldenSetItem, VerifyRequest
from ..utils import now_ms
from ..verification import verify_claims

router = APIRouter()


@router.get("/api/evaluations/golden")
def list_golden_set(p: Principal = Depends(principal)) -> dict[str, Any]:
    with db() as connection:
        rows = connection.execute("SELECT id, question, expected_document_id, expected_chunk_id, created_at FROM golden_set WHERE workspace_id=? ORDER BY created_at", (p.workspace_id,)).fetchall()
    return {"items": [dict(row) for row in rows]}



@router.post("/api/evaluations/golden", status_code=201)
def add_golden_item(payload: GoldenSetItem, p: Principal = Depends(principal)) -> dict[str, Any]:
    if not payload.expected_document_id and not payload.expected_chunk_id:
        raise HTTPException(400, "expected_document_id or expected_chunk_id is required")
    item_id = str(uuid.uuid4())
    with db() as connection:
        connection.execute("INSERT INTO golden_set(id, workspace_id, question, expected_document_id, expected_chunk_id, created_at) VALUES (?, ?, ?, ?, ?, ?)", (item_id, p.workspace_id, payload.question, payload.expected_document_id, payload.expected_chunk_id, now_ms()))
        row = connection.execute("SELECT id, question, expected_document_id, expected_chunk_id, created_at FROM golden_set WHERE id=?", (item_id,)).fetchone()
    return dict(row)



@router.post("/api/feedback", status_code=201)
def add_feedback(payload: FeedbackRequest, p: Principal = Depends(principal)) -> dict[str, Any]:
    if payload.rating not in {-1, 1}:
        raise HTTPException(400, "rating must be 1 or -1")
    with db() as connection:
        trace = connection.execute("SELECT id FROM traces WHERE id=? AND workspace_id=?", (payload.trace_id, p.workspace_id)).fetchone()
        if trace is None:
            raise HTTPException(404, "Trace not found")
        connection.execute("INSERT INTO feedback(id, workspace_id, trace_id, rating, comment, created_at) VALUES (?, ?, ?, ?, ?, ?)", (str(uuid.uuid4()), p.workspace_id, payload.trace_id, 1 if payload.rating > 0 else -1, payload.comment, now_ms()))
    return {"accepted": True}



@router.post("/api/verify/claims")
def verify_answer_claims(payload: VerifyRequest, p: Principal = Depends(principal)) -> dict[str, Any]:
    with db() as connection:
        placeholders = ",".join("?" * len(payload.citation_chunk_ids))
        rows = connection.execute(
            f"SELECT id, document_id, text FROM chunks WHERE workspace_id=? AND id IN ({placeholders})",
            (p.workspace_id, *payload.citation_chunk_ids),
        ).fetchall()
    citations = [
        {"chunk_id": row["id"], "document_id": row["document_id"], "excerpt": row["text"]}
        for row in rows
    ]
    return verify_claims(payload.answer, citations)
