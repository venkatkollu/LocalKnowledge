from conftest import chat, cache_count, active_index_with_corpus


def test_same_query_hits_cache(client, corpus, active_index_with_corpus):
    chat(client, "What is LoRA?")
    b = chat(client, "What is LoRA?")
    with __import__("backend.main", fromlist=["db"]).db() as conn:
        hit = conn.execute(
            "SELECT cache_hit FROM traces WHERE id=?", (b["trace_id"],)
        ).fetchone()[0]
    assert hit == 1


def test_lora_vs_qlora_not_collided(client, corpus, active_index_with_corpus):
    a = chat(client, "What is LoRA?")
    b = chat(client, "What is QLoRA?")
    assert a["trace_id"] != b["trace_id"]
    assert "LoRA" in a["answer"]
    assert "QLoRA" in b["answer"] or "4-bit" in b["answer"]


def test_eval_toggle_round_trip():
    import backend.main as m
    assert m.cache_disabled_for_eval() is False
    m._set_eval_active(True)
    try:
        assert m.cache_disabled_for_eval() is True
    finally:
        m._set_eval_active(False)
    assert m.cache_disabled_for_eval() is False