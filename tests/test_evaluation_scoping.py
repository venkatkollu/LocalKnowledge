import pytest
from fastapi import HTTPException
import backend.main as m
from conftest import chat, chunk_ids_for, active_index_with_corpus


def test_eval_passes_when_candidate_contains_expected(client, corpus, active_index_with_corpus):
    """Test that evaluation passes when candidate index contains expected chunks."""
    idx_id = active_index_with_corpus

    lora_chunks = chunk_ids_for(corpus["lora.txt"]["id"])
    client.post("/api/evaluations/golden", json={
        "question": "What optimizer does LoRA use?",
        "expected_chunk_id": lora_chunks[0],
    })
    p = m.Principal(workspace_id="default", user_id="local")
    result = m.run_index_evaluation(idx_id, p)
    assert result["index"]["evaluation_score"] is not None
    assert result["index"]["evaluated"] is True


def test_eval_fails_when_index_not_ready(client, corpus):
    """Test that evaluation fails for unvalidated index."""
    create = client.post("/api/indexes", json={"notes": "unvalidated"}).json()
    v1 = create["index"]["id"]
    # Don't build or validate

    p = m.Principal(workspace_id="default", user_id="local")
    with pytest.raises(HTTPException) as exc:
        m.run_index_evaluation(v1, p)
    assert exc.value.status_code == 409
    assert "Build and validate" in str(exc.value.detail)