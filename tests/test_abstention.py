from conftest import chat, active_index_with_corpus


def test_out_of_domain_abstains(client, corpus, active_index_with_corpus):
    r = chat(client, "What is the Krebs cycle?")
    # Should abstain or return low confidence
    assert r["evidence"]["decision"] in ("abstain", "answer_with_uncertainty")


def test_empty_document_scope_abstains(client, corpus):
    r = chat(client, "Summarize this document",
             document_id=corpus["empty.txt"]["id"])
    assert r["evidence"]["decision"] == "abstain"
    assert r["citations"] == []


def test_empty_document_metadata(client, corpus):
    r = chat(client, "how many chunks does empty.txt have")
    assert r["evidence"]["decision"] == "metadata_answer"
    assert "0" in r["answer"]


def test_full_keyword_match_not_rejected_by_evidence_gate(
    client, corpus, active_index_with_corpus, monkeypatch
):
    import backend.main as m

    # Production default gate: a chunk matching every query term must not be
    # discarded just because synthetic hash embeddings score low cosine.
    monkeypatch.setattr(m.SETTINGS, "abstain_threshold", 0.6)
    r = chat(client, "What optimizer does LoRA use?")
    assert r["citations"]
    assert r["evidence"]["decision"] != "abstain"


def test_retrieved_answer_used_when_evidence_exists(client, corpus, active_index_with_corpus):
    r = chat(client, "What optimizer does LoRA use?")
    assert r["evidence"]["decision"] != "abstain"
    assert r["citations"]