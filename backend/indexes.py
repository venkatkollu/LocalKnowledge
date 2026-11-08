"""Blue/green index lifecycle: build, validate, evaluate, activate, roll back."""
from __future__ import annotations

import json
import math
import sqlite3
import statistics
import uuid
from typing import Any

from fastapi import HTTPException

from . import providers
from .auth import Principal
from .cache import _set_eval_active
from .db import db
from .providers import choose_provider, embedding_identity
from .retrieval import retrieve
from .utils import json_dumps, now_ms, route_query


def index_public(row: sqlite3.Row) -> dict[str, Any]:
    return {"id": row["id"], "state": row["state"], "embedding": row["embedding"], "dimensions": row["dimensions"], "revision": row["revision"], "documents": row["documents"], "chunks": row["chunks"], "created_at": row["created_at"], "built_at": row["built_at"], "validated": bool(row["validated"]), "evaluated": bool(row["evaluated"]), "evaluation_score": row["evaluation_score"], "notes": row["notes"]}



def run_index_evaluation(index_id: str, p: Principal) -> dict[str, Any]:
    """Evaluate an index without holding SQLite open during embeddings.

    Retrieval is strictly scoped to the candidate index's membership so a
    candidate can never borrow results from the workspace corpus.
    """
    _set_eval_active(True)
    try:
        with db() as connection:
            row = connection.execute("SELECT * FROM index_versions WHERE id=? AND workspace_id=?", (index_id, p.workspace_id)).fetchone()
            if row is None:
                raise HTTPException(404, "Index not found")
            if row["state"] not in {"ready", "active"} or not row["validated"]:
                raise HTTPException(409, "Build and validate the index before evaluating")
            unembedded = index_unembedded_count(connection, index_id)
            if unembedded:
                raise HTTPException(409, f"Index {index_id} has {unembedded} chunks without embeddings; rebuild it before evaluating")
            mismatches = index_dimension_mismatch_count(connection, index_id)
            if mismatches:
                raise HTTPException(409, f"Index {index_id} has {mismatches} embeddings with the wrong dimensions; rebuild it before evaluating")
            golden = [dict(item) for item in connection.execute("SELECT question, expected_document_id, expected_chunk_id FROM golden_set WHERE workspace_id=? ORDER BY created_at", (p.workspace_id,)).fetchall()]
            embedding_row = choose_provider(connection, p.workspace_id, "Embeddings")
        embedding_row = dict(embedding_row) if embedding_row is not None else None
        use_dense = embedding_space_compatible(row, embedding_row)

        scores: list[tuple[float, float, float]] = []
        for item in golden:
            vector = providers.embed_text(embedding_row, item["question"]) if use_dense else []
            plan = route_query(item["question"])
            with db() as connection:
                candidates, _ = retrieve(
                    connection,
                    p.workspace_id,
                    item["question"],
                    100,
                    vector,
                    document_ids=plan.document_ids or None,
                    filters=plan.filters or None,
                    index_id=index_id,
                    use_dense=use_dense,
                )
            expected_chunk = item["expected_chunk_id"]
            expected_document = item["expected_document_id"]
            hit_index = next((index for index, candidate in enumerate(candidates) if (expected_chunk and candidate["chunk_id"] == expected_chunk) or (expected_document and candidate.get("document_id") == expected_document)), None)
            if hit_index is None:
                scores.append((0.0, 0.0, 0.0))
            else:
                rank = hit_index + 1
                scores.append((1.0, 1.0 / rank, 1.0 / math.log2(rank + 1) if rank <= 10 else 0.0))
        recall100 = statistics.mean(score[0] for score in scores) if scores else 1.0
        mrr10 = statistics.mean(score[1] for score in scores) if scores else 1.0
        ndcg10 = statistics.mean(score[2] for score in scores) if scores else 1.0

        with db() as connection:
            baseline = connection.execute("SELECT e.index_version, e.recall100, e.ndcg10 FROM evaluations e JOIN index_versions i ON i.id=e.index_version WHERE e.workspace_id=? AND i.state='active' ORDER BY e.created_at DESC LIMIT 1", (p.workspace_id,)).fetchone()
            passed = baseline is None or (recall100 >= baseline[1] - 0.03 and ndcg10 >= baseline[2] - 0.05)
            connection.execute("UPDATE index_versions SET evaluated=1, evaluation_score=?, notes=? WHERE id=?", (ndcg10, "No golden set configured" if not golden else ("Passed golden-set regression gate" if passed else "Failed golden-set regression gate"), index_id))
            connection.execute("INSERT INTO evaluations(id, workspace_id, index_version, recall100, ndcg10, mrr10, passed, compared_index, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (str(uuid.uuid4()), p.workspace_id, index_id, recall100, ndcg10, mrr10, int(passed), baseline[0] if baseline else None, now_ms()))
            updated = connection.execute("SELECT * FROM index_versions WHERE id=?", (index_id,)).fetchone()
        if not passed:
            raise HTTPException(409, "Index evaluation gate failed")
        return {"index": index_public(updated)}
    finally:
        _set_eval_active(False)



def index_action(index_id: str, action: str, p: Principal) -> dict[str, Any]:
    if action == "evaluate":
        return run_index_evaluation(index_id, p)

    if action == "build":
        # 1. Read the snapshot and identify chunks that need vectors. Provider
        # calls happen outside any transaction so a slow/failed embedding call
        # cannot leave a half-written index behind.
        with db() as connection:
            row = connection.execute("SELECT * FROM index_versions WHERE id=? AND workspace_id=?", (index_id, p.workspace_id)).fetchone()
            if row is None:
                raise HTTPException(404, "Index not found")
            embedding_row_value = choose_provider(connection, p.workspace_id, "Embeddings")
            embedding_row_dict = dict(embedding_row_value) if embedding_row_value is not None else None
            model_identity = embedding_identity(embedding_row_dict)
            recompute_all = row["embedding"] != model_identity
            was_active = row["state"] == "active"
            expected_dimensions = None if recompute_all else (row["dimensions"] or None)
            if recompute_all:
                missing = connection.execute(
                    "SELECT c.id AS chunk_id, c.text FROM chunks c JOIN documents d ON d.id=c.document_id "
                    "WHERE c.workspace_id=? AND c.superseded=0 AND d.deleted_at IS NULL",
                    (p.workspace_id,),
                ).fetchall()
            else:
                missing = connection.execute(
                    "SELECT c.id AS chunk_id, c.text FROM chunks c JOIN documents d ON d.id=c.document_id "
                    "LEFT JOIN index_chunk_embeddings ice ON ice.index_id=? AND ice.chunk_id=c.id "
                    "WHERE c.workspace_id=? AND c.superseded=0 AND d.deleted_at IS NULL "
                    "AND ice.embedding_json IS NULL",
                    (index_id, p.workspace_id),
                ).fetchall()

        # 2. Compute embeddings with no lock held.
        computed: list[tuple[str, list[float]]] = []
        dimensions: int | None = None
        for missing_row in missing:
            try:
                vector = providers.embed_text(embedding_row_dict, missing_row["text"])
            except Exception as exc:
                raise HTTPException(500, f"Embedding precompute failed for chunk {missing_row['chunk_id']}: {exc}") from exc
            if dimensions is None:
                dimensions = len(vector)
            elif len(vector) != dimensions:
                raise HTTPException(
                    500,
                    f"Embedding provider returned inconsistent dimensions: {dimensions} and {len(vector)}",
                )
            if expected_dimensions is not None and len(vector) != expected_dimensions:
                raise HTTPException(
                    500,
                    f"Embedding provider returned {len(vector)} dimensions but index {index_id} uses {expected_dimensions}",
                )
            computed.append((missing_row["chunk_id"], vector))

        # 3. Materialize membership + vectors in one short transaction.
        with db() as connection:
            connection.execute("DELETE FROM index_chunks WHERE index_id=?", (index_id,))
            connection.execute(
                "INSERT INTO index_chunks(index_id, workspace_id, chunk_id) "
                "SELECT ?, c.workspace_id, c.id FROM chunks c JOIN documents d ON d.id=c.document_id "
                "WHERE c.workspace_id=? AND c.superseded=0 AND d.deleted_at IS NULL",
                (index_id, p.workspace_id),
            )
            if recompute_all:
                connection.execute("DELETE FROM index_chunk_embeddings WHERE index_id=?", (index_id,))
            for chunk_id, vector in computed:
                connection.execute(
                    "INSERT OR REPLACE INTO index_chunk_embeddings(index_id, workspace_id, chunk_id, embedding_json, model) VALUES (?, ?, ?, ?, ?)",
                    (index_id, p.workspace_id, chunk_id, json_dumps(vector), model_identity),
                )
                if recompute_all:
                    # A provider change is a corpus re-embed, not just a new
                    # index. Keep the corpus in the new space so unscoped
                    # retrieval and later ingestion stay consistent.
                    connection.execute(
                        "UPDATE chunks SET embedding_json=? WHERE id=? AND workspace_id=?",
                        (json_dumps(vector), chunk_id, p.workspace_id),
                    )
            if recompute_all:
                connection.execute(
                    "UPDATE documents SET embedding=? WHERE workspace_id=? AND deleted_at IS NULL",
                    (model_identity, p.workspace_id),
                )
            connection.execute(
                "DELETE FROM index_chunk_embeddings WHERE index_id=? AND chunk_id NOT IN (SELECT chunk_id FROM index_chunks WHERE index_id=?)",
                (index_id, index_id),
            )
            unembedded = index_unembedded_count(connection, index_id)
            if unembedded:
                raise HTTPException(500, f"Index {index_id} has {unembedded} chunks without embeddings")
            if dimensions is None:
                sample = connection.execute("SELECT embedding_json FROM index_chunk_embeddings WHERE index_id=? LIMIT 1", (index_id,)).fetchone()
                if sample is not None:
                    try:
                        dimensions = len(json.loads(sample["embedding_json"]))
                    except (TypeError, ValueError):
                        dimensions = None
            counts = connection.execute(
                "SELECT COUNT(DISTINCT c.document_id), COUNT(ic.chunk_id) FROM index_chunks ic "
                "JOIN chunks c ON c.id=ic.chunk_id JOIN documents d ON d.id=c.document_id "
                "WHERE ic.index_id=? AND ic.workspace_id=? AND c.superseded=0 AND d.deleted_at IS NULL",
                (index_id, p.workspace_id),
            ).fetchone()
            connection.execute(
                "UPDATE index_versions SET state=?, embedding=?, dimensions=?, documents=?, chunks=?, "
                "built_at=?, validated=0, evaluated=0, evaluation_score=NULL WHERE id=?",
                ("active" if was_active else "ready", model_identity, dimensions, counts[0], counts[1], now_ms(), index_id),
            )
            # A rebuilt index must not serve answers produced from its old corpus.
            connection.execute("DELETE FROM cache_entries WHERE workspace_id=? AND index_version=?", (p.workspace_id, index_id))
            if recompute_all:
                connection.execute("DELETE FROM cache_entries WHERE workspace_id=?", (p.workspace_id,))
            return {"index": index_public(connection.execute("SELECT * FROM index_versions WHERE id=?", (index_id,)).fetchone())}

    with db() as connection:
        row = connection.execute("SELECT * FROM index_versions WHERE id=? AND workspace_id=?", (index_id, p.workspace_id)).fetchone()
        if row is None:
            raise HTTPException(404, "Index not found")
        if action == "validate":
            if row["state"] not in {"ready", "active"}:
                raise HTTPException(409, "Build the index before validating")
            unembedded = index_unembedded_count(connection, index_id)
            if unembedded:
                raise HTTPException(409, f"Index {index_id} has {unembedded} chunks without embeddings; rebuild it before validating")
            mismatches = index_dimension_mismatch_count(connection, index_id)
            if mismatches:
                raise HTTPException(409, f"Index {index_id} has {mismatches} embeddings with the wrong dimensions; rebuild it before validating")
            connection.execute("UPDATE index_versions SET validated=1 WHERE id=?", (index_id,))
        elif action == "activate":
            updated = connection.execute("SELECT * FROM index_versions WHERE id=?", (index_id,)).fetchone()
            if not updated["validated"]:
                raise HTTPException(409, "Index must pass validation before activation")
            golden_count = connection.execute("SELECT COUNT(*) FROM golden_set WHERE workspace_id=?", (p.workspace_id,)).fetchone()[0]
            if golden_count and not updated["evaluated"]:
                raise HTTPException(409, "Run the golden-set evaluation before activation")
            if updated["evaluated"] and updated["evaluation_score"] is not None and updated["notes"] == "Failed golden-set regression gate":
                raise HTTPException(409, "Index evaluation gate failed")
            connection.execute("UPDATE index_versions SET state='retired' WHERE workspace_id=? AND state='active'", (p.workspace_id,))
            connection.execute("UPDATE index_versions SET state='active' WHERE id=?", (index_id,))
            # Pull in current chunks that share this index's embedding space so
            # documents ingested after the candidate build are not lost.
            refresh_index_membership(connection, p.workspace_id, index_id)
            unembedded = index_unembedded_count(connection, index_id)
            if unembedded:
                raise HTTPException(409, f"Index {index_id} has {unembedded} chunks without embeddings; rebuild it before activation")
            mismatches = index_dimension_mismatch_count(connection, index_id)
            if mismatches:
                raise HTTPException(409, f"Index {index_id} has {mismatches} embeddings with the wrong dimensions; rebuild it before activation")
            connection.execute("DELETE FROM cache_entries WHERE workspace_id=?", (p.workspace_id,))
        elif action == "rollback":
            active = connection.execute("SELECT * FROM index_versions WHERE workspace_id=? AND state='active' ORDER BY revision DESC LIMIT 1", (p.workspace_id,)).fetchone()
            target = connection.execute("SELECT * FROM index_versions WHERE workspace_id=? AND state='retired' AND validated=1 ORDER BY revision DESC LIMIT 1", (p.workspace_id,)).fetchone()
            if target is None:
                raise HTTPException(409, "No validated retired index is available")
            connection.execute("UPDATE index_versions SET state='retired' WHERE id=?", ((active["id"] if active else ""),))
            connection.execute("UPDATE index_versions SET state='active' WHERE id=?", (target["id"],))
            refresh_index_membership(connection, p.workspace_id, target["id"])
            unembedded = index_unembedded_count(connection, target["id"])
            if unembedded:
                raise HTTPException(409, f"Index {target['id']} has {unembedded} chunks without embeddings; rebuild it before rolling back")
            mismatches = index_dimension_mismatch_count(connection, target["id"])
            if mismatches:
                raise HTTPException(409, f"Index {target['id']} has {mismatches} embeddings with the wrong dimensions; rebuild it before rolling back")
            connection.execute("DELETE FROM cache_entries WHERE workspace_id=?", (p.workspace_id,))
        else:
            raise HTTPException(400, "Unsupported index action")
        target_id = target["id"] if action == "rollback" else index_id
        return {"index": index_public(connection.execute("SELECT * FROM index_versions WHERE id=?", (target_id,)).fetchone())}



def active_index(connection: sqlite3.Connection, workspace_id: str) -> sqlite3.Row | None:
    return connection.execute("SELECT * FROM index_versions WHERE workspace_id=? AND state='active' ORDER BY revision DESC LIMIT 1", (workspace_id,)).fetchone()



def embedding_space_compatible(index: sqlite3.Row | None, provider: sqlite3.Row | dict[str, Any] | None) -> bool:
    """A query vector can only score an index built in the same space."""
    if index is None:
        return True
    identity = index["embedding"]
    return not identity or identity == embedding_identity(provider)



def index_unembedded_count(connection: sqlite3.Connection, index_id: str) -> int:
    return connection.execute(
        "SELECT COUNT(*) FROM index_chunks ic "
        "LEFT JOIN index_chunk_embeddings ice ON ice.index_id=ic.index_id AND ice.chunk_id=ic.chunk_id "
        "WHERE ic.index_id=? AND ice.embedding_json IS NULL",
        (index_id,),
    ).fetchone()[0]



def index_dimension_mismatch_count(connection: sqlite3.Connection, index_id: str) -> int:
    row = connection.execute(
        "SELECT dimensions FROM index_versions WHERE id=?", (index_id,)
    ).fetchone()
    if row is None or not row["dimensions"]:
        return 0
    expected = int(row["dimensions"])
    mismatches = 0
    for item in connection.execute(
        "SELECT embedding_json FROM index_chunk_embeddings WHERE index_id=?", (index_id,)
    ).fetchall():
        try:
            if len(json.loads(item["embedding_json"])) != expected:
                mismatches += 1
        except (TypeError, ValueError):
            mismatches += 1
    return mismatches



def refresh_index_membership(connection: sqlite3.Connection, workspace_id: str, index_id: str) -> int:
    """Keep a live index aligned with current chunks without mixing spaces.

    Candidate indexes are snapshots until activation. This helper is only used
    for the active index (startup and ingestion) and immediately after an
    activation, so the live corpus stays searchable.
    """
    index_row = connection.execute(
        "SELECT embedding FROM index_versions WHERE id=? AND workspace_id=?",
        (index_id, workspace_id),
    ).fetchone()
    if index_row is None:
        return 0
    index_identity = index_row["embedding"]

    # Existing members keep their index-local vectors even if the corpus was
    # re-embedded for another index. Only new members are gated by the current
    # document embedding space.
    # Drop superseded/deleted chunks.
    connection.execute(
        "DELETE FROM index_chunks WHERE index_id=? AND chunk_id NOT IN ("
        "SELECT c.id FROM chunks c JOIN documents d ON d.id=c.document_id "
        "WHERE c.workspace_id=? AND c.superseded=0 AND d.deleted_at IS NULL)",
        (index_id, workspace_id),
    )
    inserted = connection.execute(
        "INSERT OR IGNORE INTO index_chunks(index_id, workspace_id, chunk_id) "
        "SELECT ?, c.workspace_id, c.id FROM chunks c JOIN documents d ON d.id=c.document_id "
        "WHERE c.workspace_id=? AND c.superseded=0 AND d.deleted_at IS NULL "
        "AND (? IS NULL OR d.embedding IS NULL OR d.embedding=?)",
        (index_id, workspace_id, index_identity, index_identity),
    ).rowcount
    connection.execute(
        "INSERT OR IGNORE INTO index_chunk_embeddings(index_id, workspace_id, chunk_id, embedding_json, model) "
        "SELECT ic.index_id, ic.workspace_id, ic.chunk_id, c.embedding_json, COALESCE(i.embedding, 'unknown') "
        "FROM index_chunks ic JOIN chunks c ON c.id=ic.chunk_id "
        "JOIN documents d ON d.id=c.document_id JOIN index_versions i ON i.id=ic.index_id "
        "WHERE ic.index_id=? AND c.embedding_json IS NOT NULL "
        "AND (i.embedding IS NULL OR d.embedding IS NULL OR d.embedding=i.embedding) "
        "AND NOT EXISTS (SELECT 1 FROM index_chunk_embeddings ice WHERE ice.index_id=ic.index_id AND ice.chunk_id=ic.chunk_id)",
        (index_id,),
    )
    connection.execute(
        "DELETE FROM index_chunk_embeddings WHERE index_id=? AND chunk_id NOT IN (SELECT chunk_id FROM index_chunks WHERE index_id=?)",
        (index_id, index_id),
    )
    counts = connection.execute(
        "SELECT COUNT(DISTINCT c.document_id), COUNT(ic.chunk_id) FROM index_chunks ic "
        "JOIN chunks c ON c.id=ic.chunk_id JOIN documents d ON d.id=c.document_id "
        "WHERE ic.index_id=? AND ic.workspace_id=? AND c.superseded=0 AND d.deleted_at IS NULL",
        (index_id, workspace_id),
    ).fetchone()
    connection.execute(
        "UPDATE index_versions SET documents=?, chunks=? WHERE id=?",
        (counts[0], counts[1], index_id),
    )
    return inserted
