from conftest import chat, cache_count, active_index_with_corpus


def test_same_query_hits_cache(client, corpus, active_index_with_corpus):
    chat(client, "What is LoRA?")
    b = chat(client, "What is LoRA?")
    from backend.db import db

    with db() as conn:
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
    from backend.cache import _set_eval_active, cache_disabled_for_eval

    assert cache_disabled_for_eval() is False
    _set_eval_active(True)
    try:
        assert cache_disabled_for_eval() is True
    finally:
        _set_eval_active(False)
    assert cache_disabled_for_eval() is False