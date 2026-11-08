"""Answer cache identity, lookup and storage."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import uuid
from typing import Any

from .config import (
    CACHE_DISABLED_DURING_EVAL,
    CACHE_TTL_SECONDS,
    PROMPT_VERSION,
    SEMANTIC_CACHE_ENABLED,
    SEMANTIC_CACHE_THRESHOLD,
)
from .utils import cosine, json_dumps, now_ms


def _cache_fingerprint(
    index_id: str,
    filters: dict[str, Any],
    intent: str,
    top_k: int | None = None,
    model: str | None = None,
    embedding: str | None = None,
    combined: bool = False,
) -> str:
    identity: dict[str, Any] = {
        "index_id": index_id,
        "filters": filters,
        "intent": intent,
        "combined": combined,
    }
    if top_k is not None:
        identity["top_k"] = top_k
    if model:
        identity["model"] = model
    if embedding:
        identity["embedding"] = embedding
    return hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()



def _cache_query_hash(question: str, fingerprint: str) -> str:
    return hashlib.sha256(f"{question.strip().lower()}|{fingerprint}".encode()).hexdigest()



_EVAL_STATE = threading.local()



def _set_eval_active(value: bool) -> None:
    _EVAL_STATE.active = value



def cache_disabled_for_eval() -> bool:
    return CACHE_DISABLED_DURING_EVAL and getattr(_EVAL_STATE, "active", False)



def cache_lookup(
    connection: sqlite3.Connection,
    workspace_id: str,
    index_id: str,
    provider_id: str | None,
    question: str,
    query_embedding: list[float],
    fingerprint: str,
    intent: str,
) -> dict[str, Any] | None:
    digest = _cache_query_hash(question, fingerprint)
    rows = connection.execute(
        "SELECT response_json, embedding_json, query_hash FROM cache_entries "
        "WHERE workspace_id=? AND index_version=? AND model_profile_id IS ? "
        "AND prompt_version=? AND expires_at>? "
        "AND filter_fingerprint IS ? AND intent_class IS ? "
        "ORDER BY created_at DESC",
        (workspace_id, index_id, provider_id, PROMPT_VERSION, now_ms(), fingerprint, intent),
    ).fetchall()
    best: sqlite3.Row | None = None
    best_score = 0.0
    for row in rows:
        if row["query_hash"] == digest:
            return json.loads(row["response_json"])
        if SEMANTIC_CACHE_ENABLED and row["embedding_json"] and SEMANTIC_CACHE_THRESHOLD <= 1.0:
            score = cosine(query_embedding, json.loads(row["embedding_json"]))
            if score >= SEMANTIC_CACHE_THRESHOLD and score > best_score:
                best, best_score = row, score
    return json.loads(best["response_json"]) if best else None



def cache_store(
    connection: sqlite3.Connection,
    workspace_id: str,
    index_id: str,
    provider_id: str | None,
    question: str,
    query_embedding: list[float],
    response: dict[str, Any],
    confidence: float,
    fingerprint: str,
    intent: str,
) -> None:
    if confidence < 0.55:
        return
    digest = _cache_query_hash(question, fingerprint)
    # model_profile_id may be NULL, which SQLite treats as distinct in a
    # UNIQUE constraint. Delete first so repeated identical questions replace
    # instead of accumulating duplicate rows.
    connection.execute(
        "DELETE FROM cache_entries WHERE workspace_id=? AND index_version=? AND model_profile_id IS ? "
        "AND prompt_version=? AND query_hash=?",
        (workspace_id, index_id, provider_id, PROMPT_VERSION, digest),
    )
    connection.execute(
        "INSERT OR REPLACE INTO cache_entries(id, workspace_id, index_version, model_profile_id, "
        "prompt_version, query_hash, query_text, embedding_json, response_json, confidence, "
        "created_at, expires_at, filter_fingerprint, intent_class) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            str(uuid.uuid4()),
            workspace_id,
            index_id,
            provider_id,
            PROMPT_VERSION,
            digest,
            question,
            json_dumps(query_embedding),
            json_dumps(response),
            confidence,
            now_ms(),
            now_ms() + CACHE_TTL_SECONDS * 1000,
            fingerprint,
            intent,
        ),
    )
