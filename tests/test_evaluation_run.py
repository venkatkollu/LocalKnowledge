import json
from pathlib import Path

import pytest
import backend.main as m
from conftest import chunk_ids_for, active_index_with_corpus

GOLDEN = json.loads((Path(__file__).parent / "data" / "golden_set.json").read_text())


@pytest.mark.slow
def test_golden_recall_at_least_07(client, corpus, active_index_with_corpus):
    idx_id = active_index_with_corpus

    registered = 0
    for item in GOLDEN:
        doc = corpus.get(item["doc"])
        if not doc:
            continue
        chunks = chunk_ids_for(doc["id"])
        if not chunks:
            continue
        client.post("/api/evaluations/golden", json={
            "question": item["question"],
            "expected_chunk_id": chunks[0],
        })
        registered += 1

    assert registered > 0, "no golden items registered"

    p = m.Principal(workspace_id="default", user_id="local")
    m.run_index_evaluation(idx_id, p)

    with m.db() as conn:
        row = conn.execute(
            "SELECT recall100, ndcg10, mrr10 FROM evaluations "
            "WHERE index_version=? ORDER BY created_at DESC LIMIT 1",
            (idx_id,),
        ).fetchone()
    assert row["recall100"] >= 0.7
    assert row["ndcg10"] >= 0.5
    assert row["mrr10"] >= 0.5