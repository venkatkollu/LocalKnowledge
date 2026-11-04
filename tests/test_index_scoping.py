import backend.main as m
from conftest import chat, active_index_with_corpus


def test_activation_controls_retrieval(client, corpus, active_index_with_corpus):
    """Test that retrieval is scoped to the active index."""
    # The active index should contain all corpus documents
    r = chat(client, "What is LoRA?")
    assert r["citations"]
    files = {c["filename"] for c in r["citations"]}
    # All retrieved files should be from the corpus
    assert files <= set(corpus.keys())


def test_index_chunks_snapshot_populated(client, corpus, active_index_with_corpus):
    idx_id = active_index_with_corpus
    with m.db() as conn:
        snap = conn.execute(
            "SELECT COUNT(*) FROM index_chunks WHERE index_id=?", (idx_id,)
        ).fetchone()[0]
    assert snap > 0


def test_embeddings_precomputed_per_index(client, corpus, active_index_with_corpus):
    idx_id = active_index_with_corpus
    with m.db() as conn:
        emb = conn.execute(
            "SELECT COUNT(*) FROM index_chunk_embeddings WHERE index_id=?", (idx_id,)
        ).fetchone()[0]
        mem = conn.execute(
            "SELECT COUNT(*) FROM index_chunks WHERE index_id=?", (idx_id,)
        ).fetchone()[0]
    assert emb == mem, f"embeddings {emb} != membership {mem}"