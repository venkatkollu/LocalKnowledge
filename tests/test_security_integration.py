import os
from pathlib import Path


def test_adversarial_corpus_is_classified_as_untrusted():
    from app.security import evidence_is_untrusted
    poisoned = Path("eval/corpus/malicious.md").read_text()
    assert evidence_is_untrusted(poisoned)


def test_index_has_model_registry_and_lifecycle(tmp_path, monkeypatch):
    # This test validates the storage contract without loading the API's global DB.
    monkeypatch.setenv("KNOWLEDGEOS_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("KNOWLEDGEOS_DB", str(tmp_path / "data" / "db.sqlite"))
    monkeypatch.setenv("KNOWLEDGEOS_KNOWLEDGE", str(tmp_path / "knowledge"))
    monkeypatch.setenv("KNOWLEDGEOS_AUTO_SYNC", "0")
    from app.config import Settings
    from app.storage import SQLiteStorage
    settings = Settings.load()
    storage = SQLiteStorage(settings)
    storage.initialize()
    index = storage.create_index("v1")
    assert index["embedding_model"]
    assert "registry" in index["config"]
    assert storage.validate_index(index["id"])["valid"] is False
