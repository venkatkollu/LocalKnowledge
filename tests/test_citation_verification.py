import pytest
from conftest import chat, chunk_ids_for


def test_verification_structure(client, corpus, active_index_with_corpus):
    r = chat(client, "What optimizer does LoRA use?")
    v = r["verification"]
    assert v["enabled"] is True
    assert isinstance(v["claims"], list) and v["claims"]
    for claim in v["claims"]:
        assert {"claim", "entailment", "supported", "citation_chunk_id"} <= claim.keys()
    assert v["decision"] in {"verified", "partial", "unsupported"}


def test_citations_carry_per_chunk_flag(client, corpus, active_index_with_corpus):
    r = chat(client, "What optimizer does LoRA use?")
    flags = {c["verification"] for c in r["citations"]}
    # Current implementation uses "verified" and "unverified"
    assert flags <= {"verified", "unverified"}, flags


def test_unsupported_answer_downgrades_decision(client, corpus, active_index_with_corpus, monkeypatch):
    def fake_verify(answer, citations):
        return {
            "enabled": True, "model": "mock",
            "claims": [{
                "claim": answer, "entailment": 0.1,
                "supported": False,
                "citation_chunk_id": citations[0]["chunk_id"],
            }],
            "verified_ratio": 0.0, "decision": "unsupported",
        }
    monkeypatch.setattr("backend.main.verify_claims", fake_verify)
    r = chat(client, "What optimizer does LoRA use?")
    assert r["evidence"]["decision"] != "answer"


def test_verify_claims_endpoint(client, corpus, active_index_with_corpus):
    lora_chunk = chunk_ids_for(corpus["lora.txt"]["id"])[0]
    r = client.post("/api/verify/claims", json={
        "answer": "LoRA uses the AdamW optimizer.",
        "citation_chunk_ids": [lora_chunk],
    })
    assert r.status_code == 200
    assert r.json()["claims"]


@pytest.mark.nli
def test_nli_rejects_contradiction(client, corpus, active_index_with_corpus):
    r = chat(client, "Does LoRA quantize the base model?")
    assert r["verification"]["decision"] in {"partial", "unsupported"}