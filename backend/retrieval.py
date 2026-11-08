"""Hybrid lexical/dense retrieval over the workspace chunk catalog."""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from typing import Any

from .utils import cosine, fts_query, query_terms


def _epoch_ms(value: Any) -> int | None:
    if isinstance(value, (int, float)):
        return int(value)
    try:
        return int(datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return None



def document_filter_clauses(
    filters: dict[str, Any],
    document_alias: str = "d",
    chunk_alias: str = "fc",
) -> tuple[list[str], list[Any]]:
    """Translate catalog filters into SQL so they constrain the candidate set
    before ranking instead of filtering results afterwards."""
    clauses: list[str] = []
    params: list[Any] = []
    filename = filters.get("filename")
    if filename:
        clauses.append(f"{document_alias}.filename=? COLLATE NOCASE")
        params.append(str(filename).strip())
    filenames = filters.get("filenames")
    if isinstance(filenames, str):
        filenames = [filenames]
    if isinstance(filenames, (list, tuple, set)):
        names = [str(name).strip() for name in filenames if str(name).strip()]
        if names:
            placeholders = ",".join("?" * len(names))
            clauses.append(f"{document_alias}.filename COLLATE NOCASE IN ({placeholders})")
            params.extend(names)
    file_type = filters.get("file_type") or filters.get("extension")
    if file_type:
        clauses.append(f"{document_alias}.extension=?")
        params.append(str(file_type).lower().lstrip("."))
    for key, operator in (("min_pages", ">="), ("max_pages", "<=")):
        if filters.get(key) is None:
            continue
        try:
            threshold = int(filters[key])
        except (TypeError, ValueError):
            continue
        clauses.append(f"{document_alias}.pages IS NOT NULL AND {document_alias}.pages {operator} ?")
        params.append(threshold)
    for key, operator in (("uploaded_after", ">="), ("uploaded_before", "<=")):
        if filters.get(key) is None:
            continue
        timestamp = _epoch_ms(filters[key])
        if timestamp is None:
            continue
        clauses.append(
            f"COALESCE({document_alias}.uploaded_at, {document_alias}.updated_at) {operator} ?"
        )
        params.append(timestamp)
    for key, chunk_type in (("has_tables", "table"), ("has_figures", "figure")):
        if not filters.get(key):
            continue
        clauses.append(
            f"EXISTS (SELECT 1 FROM chunks {chunk_alias} "
            f"WHERE {chunk_alias}.document_id={document_alias}.id "
            f"AND {chunk_alias}.superseded=0 AND {chunk_alias}.chunk_type='{chunk_type}')"
        )
    return clauses, params



def retrieve(
    connection: sqlite3.Connection,
    workspace_id: str,
    question: str,
    top_k: int,
    embedding: list[float],
    document_id: str | None = None,
    document_ids: list[str] | None = None,
    filters: dict[str, Any] | None = None,
    index_id: str | None = None,
    use_dense: bool = True,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    scope_clauses: list[str] = []
    scope_params: list[Any] = []

    if document_id:
        scope_clauses.append("c.document_id=?")
        scope_params.append(document_id)
    if document_ids:
        placeholders = ",".join("?" * len(document_ids))
        scope_clauses.append(f"c.document_id IN ({placeholders})")
        scope_params.extend(document_ids)
    if filters:
        filter_clauses, filter_params = document_filter_clauses(filters, "d", "fc")
        scope_clauses.extend(filter_clauses)
        scope_params.extend(filter_params)

    scope_sql = (" AND " + " AND ".join(scope_clauses)) if scope_clauses else ""
    index_join = (
        " JOIN index_chunks ic ON ic.chunk_id=c.id AND ic.index_id=?"
        if index_id
        else ""
    )
    dense_join = (
        " JOIN index_chunks ic ON ic.chunk_id=c.id AND ic.index_id=?"
        " LEFT JOIN index_chunk_embeddings ice ON ice.index_id=ic.index_id AND ice.chunk_id=c.id"
        if index_id
        else ""
    )
    dense_embedding = "COALESCE(ice.embedding_json, c.embedding_json)" if index_id else "c.embedding_json"

    lexical_rows: list[sqlite3.Row] = []
    try:
        lexical_sql = (
            "SELECT c.*, d.filename, d.path, d.version AS document_version, bm25(chunks_fts) AS rank "
            "FROM chunks_fts "
            "JOIN chunks c ON c.id=chunks_fts.chunk_id "
            "JOIN documents d ON d.id=c.document_id"
            + index_join
            + " WHERE chunks_fts.workspace_id=? AND chunks_fts MATCH ? "
            "AND c.superseded=0 AND d.deleted_at IS NULL"
            + scope_sql
            + " ORDER BY rank LIMIT ?"
        )
        params = (
            ([index_id] if index_id else [])
            + [workspace_id, fts_query(question)]
            + scope_params
            + [max(30, top_k * 5)]
        )
        lexical_rows = connection.execute(lexical_sql, params).fetchall()
    except sqlite3.OperationalError:
        lexical_rows = []

    dense_rows: list[sqlite3.Row] = []
    if use_dense:
        dense_sql = (
            "SELECT c.*, d.filename, d.path, d.version AS document_version, "
            f"{dense_embedding} AS active_embedding_json "
            "FROM chunks c JOIN documents d ON d.id=c.document_id"
            + dense_join
            + " WHERE c.workspace_id=? AND c.superseded=0 AND d.deleted_at IS NULL"
            + scope_sql
            + " ORDER BY c.id LIMIT ?"
        )
        dense_params = (
            ([index_id] if index_id else [])
            + [workspace_id]
            + scope_params
            + [int(os.getenv("KNOWLEDGEOS_DENSE_SCAN_LIMIT", "50000"))]
        )
        dense_rows = connection.execute(dense_sql, dense_params).fetchall()

    by_id = {row["id"]: row for row in lexical_rows}
    for row in dense_rows:
        by_id.setdefault(row["id"], row)
    lexical_rank = {row["id"]: rank for rank, row in enumerate(lexical_rows, start=1)}
    dense_scores = {row["id"]: cosine(embedding, json.loads(row["active_embedding_json"] or "[]")) for row in dense_rows}
    dense_rank = {chunk_id: rank for rank, (chunk_id, _) in enumerate(sorted(dense_scores.items(), key=lambda item: item[1], reverse=True), start=1)}
    candidates: list[dict[str, Any]] = []
    terms = set(query_terms(question))
    for chunk_id, row in by_id.items():
        lexical = sum(1 for term in terms if term in row["text"].lower()) / max(1, len(terms))
        dense = dense_scores.get(chunk_id, 0.0)
        bm25_position = lexical_rank.get(chunk_id)
        dense_position = dense_rank.get(chunk_id)
        source = "both" if bm25_position and dense_position else "bm25" if bm25_position else "dense"
        # The fused reranker score ranks candidates; the evidence score is the
        # strongest independent relevance signal. Gating on the fused score
        # alone rejects chunks that match every query term but score a lower
        # dense similarity (for example after a provider/embedding change).
        candidates.append({"chunk_id": row["id"], "document_id": row["document_id"], "filename": row["filename"], "source": source, "cosine": dense, "bm25_rank": bm25_position, "lexical_score": lexical, "rrf_score": (1 / (60 + bm25_position) if bm25_position else 0) + (1 / (60 + dense_position) if dense_position else 0), "reranker_score": lexical * 0.55 + max(0, dense) * 0.45, "evidence_score": max(lexical, max(0.0, dense)), "excerpt": row["text"]})
    candidates.sort(key=lambda value: (value["reranker_score"], value["rrf_score"]), reverse=True)
    citations = []
    for candidate in candidates[:top_k]:
        row = by_id[candidate["chunk_id"]]
        citations.append({"chunk_id": row["id"], "document_id": row["document_id"], "filename": row["filename"], "path": row["path"], "line_start": row["line_start"], "line_end": row["line_end"], "version": row["document_version"], "excerpt": row["text"], "chunk_type": row["chunk_type"] or "text", "page_number": row["page_number"], "section": row["section"], "start_offset": row["start_offset"], "end_offset": row["end_offset"], "score": candidate["reranker_score"], "lexical_score": candidate["lexical_score"], "evidence_score": candidate["evidence_score"], "verification": "unverified"})
    return candidates[:top_k], citations
