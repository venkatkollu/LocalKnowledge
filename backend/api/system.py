"""Health, metrics, activity, configuration and storage endpoints."""
from __future__ import annotations

import json
import statistics
from typing import Any

from fastapi import APIRouter, Depends, Query

from ..auth import Principal, principal
from ..config import (
    APP_VERSION,
    CACHE_TTL_SECONDS,
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    MAX_BATCH_FILES,
    SETTINGS,
)
from ..db import db
from ..providers import choose_provider, embedding_identity

router = APIRouter()


@router.get("/health")
@router.get("/api/health")
def health(p: Principal = Depends(principal)) -> dict[str, Any]:
    with db() as connection:
        documents = connection.execute("SELECT COUNT(*) FROM documents WHERE workspace_id=? AND deleted_at IS NULL", (p.workspace_id,)).fetchone()[0]
        chunks = connection.execute("SELECT COUNT(*) FROM chunks WHERE workspace_id=? AND superseded=0", (p.workspace_id,)).fetchone()[0]
        active = connection.execute("SELECT id FROM index_versions WHERE workspace_id=? AND state='active' ORDER BY revision DESC LIMIT 1", (p.workspace_id,)).fetchone()
        embedding_row = choose_provider(connection, p.workspace_id, "Embeddings")
    return {"ok": True, "version": APP_VERSION, "documents": documents, "chunks": chunks, "fts5_active": True, "active_index": active["id"] if active else None, "embedding_provider": embedding_identity(embedding_row), "ollama": {"base_url": SETTINGS.ollama_base_url, "model": SETTINGS.ollama_embedding_model, "hash_fallback": SETTINGS.allow_hash_embedding_fallback}}



@router.get("/api/metrics")
def metrics(p: Principal = Depends(principal)) -> dict[str, Any]:
    with db() as connection:
        rows = connection.execute("SELECT * FROM traces WHERE workspace_id=? ORDER BY created_at DESC LIMIT 1000", (p.workspace_id,)).fetchall()
    latencies = [sum(json.loads(row["stage_timings_json"]).values()) for row in rows]
    outcomes = [row["outcome"] for row in rows]
    stage_values: dict[str, list[float]] = {}
    for row in rows:
        for label, value in json.loads(row["stage_timings_json"]).items():
            stage_values.setdefault(label, []).append(float(value))
    def percentile(value: float) -> float | None:
        if not latencies:
            return None
        return round(statistics.quantiles(latencies, n=100, method="inclusive")[max(0, min(98, int(value) - 1))], 2) if len(latencies) > 1 else round(latencies[0], 2)
    return {"latency": {"p50": percentile(50), "p95": percentile(95), "p99": percentile(99)}, "queries": len(rows), "answers": outcomes.count("answer"), "answers_with_uncertainty": outcomes.count("answer_with_uncertainty"), "abstentions": outcomes.count("abstain"), "errors": outcomes.count("error"), "mean_ms": round(statistics.mean(latencies), 2) if latencies else None, "stages": [{"label": label, "ms": round(statistics.mean(values), 2)} for label, values in stage_values.items()]}



@router.get("/api/activity")
def activity(limit: int = Query(default=100, ge=1, le=500), p: Principal = Depends(principal)) -> dict[str, Any]:
    with db() as connection:
        rows = connection.execute("SELECT * FROM events WHERE workspace_id=? ORDER BY created_at DESC LIMIT ?", (p.workspace_id, limit)).fetchall()
    return {"events": [dict(row) for row in rows]}



@router.get("/api/config")
def config(p: Principal = Depends(principal)) -> dict[str, Any]:
    with db() as connection:
        profiles = connection.execute("SELECT id, name, kind, model, role, base_url FROM provider_profiles WHERE workspace_id=? AND enabled=1", (p.workspace_id,)).fetchall()
        embedding_row = choose_provider(connection, p.workspace_id, "Embeddings")
    return {"providers": [dict(row) for row in profiles], "embedding": {"provider": embedding_identity(embedding_row), "ollama_base_url": SETTINGS.ollama_base_url, "ollama_model": SETTINGS.ollama_embedding_model, "hash_fallback": SETTINGS.allow_hash_embedding_fallback}, "limits": {"max_upload_bytes": SETTINGS.max_upload_bytes, "max_batch_files": MAX_BATCH_FILES, "chunk_size": CHUNK_SIZE, "chunk_overlap": CHUNK_OVERLAP, "cache_ttl_seconds": CACHE_TTL_SECONDS}}



@router.get("/api/storage")
def storage(p: Principal = Depends(principal)) -> dict[str, Any]:
    with db() as connection:
        documents = connection.execute("SELECT COUNT(*), COALESCE(SUM(size_bytes), 0) FROM documents WHERE workspace_id=? AND deleted_at IS NULL", (p.workspace_id,)).fetchone()
        chunks = connection.execute("SELECT COUNT(*) FROM chunks WHERE workspace_id=? AND superseded=0", (p.workspace_id,)).fetchone()[0]
    return {"documents": documents[0], "original_bytes": documents[1], "chunks": chunks, "storage": "local filesystem", "data_directory": str(SETTINGS.files_dir / p.workspace_id)}


@router.get("/api/routing/stats")
def routing_stats(p: Principal = Depends(principal)) -> dict[str, Any]:
    with db() as connection:
        total = connection.execute("SELECT COUNT(*) FROM routing_log WHERE workspace_id=?", (p.workspace_id,)).fetchone()[0]
        route_counts = dict(connection.execute("SELECT route, COUNT(*) FROM routing_log WHERE workspace_id=? GROUP BY route", (p.workspace_id,)).fetchall())
        tier_counts = dict(connection.execute("SELECT tier, COUNT(*) FROM routing_log WHERE workspace_id=? GROUP BY tier", (p.workspace_id,)).fetchall())
        outcome_counts = dict(connection.execute("SELECT COALESCE(outcome, 'pending'), COUNT(*) FROM routing_log WHERE workspace_id=? GROUP BY outcome", (p.workspace_id,)).fetchall())
        resolved = connection.execute("SELECT COUNT(*) FROM routing_log WHERE workspace_id=? AND outcome IS NOT NULL", (p.workspace_id,)).fetchone()[0]
        accurate = connection.execute(
            "SELECT COUNT(*) FROM routing_log WHERE workspace_id=? AND outcome IS NOT NULL "
            "AND ((route='SQL' AND outcome='metadata_answer') "
            "OR (route IN ('VECTOR','HYBRID') AND outcome NOT IN ('metadata_answer','conversational')))",
            (p.workspace_id,),
        ).fetchone()[0]
        disagreements = connection.execute(
            "SELECT COUNT(*) FROM routing_log WHERE workspace_id=? AND disagreement=1",
            (p.workspace_id,),
        ).fetchone()[0]
    return {
        "total": total,
        "by_route": route_counts,
        "by_tier": tier_counts,
        "by_outcome": outcome_counts,
        "accuracy": round(accurate / resolved, 4) if resolved else 1.0,
        "disagreements": disagreements,
    }
