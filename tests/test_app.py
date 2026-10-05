import os
import tempfile
from pathlib import Path

TEMP = tempfile.TemporaryDirectory(prefix="knowledgeos-tests-", dir=os.getenv("KNOWLEDGEOS_TMP"))
TEST_DATA = Path(TEMP.name) / "data"
TEST_KNOWLEDGE = Path(TEMP.name) / "knowledge"

os.environ["KNOWLEDGEOS_AUTO_SYNC"] = "0"
os.environ["KNOWLEDGEOS_OFFLINE"] = "1"
os.environ["KNOWLEDGEOS_DATA"] = str(TEST_DATA)
os.environ["KNOWLEDGEOS_KNOWLEDGE"] = str(TEST_KNOWLEDGE)
os.environ["KNOWLEDGEOS_DB"] = str(TEST_DATA / "test.db")

from fastapi.testclient import TestClient
import app


def setup_module():
    import shutil
    shutil.rmtree(TEST_DATA, ignore_errors=True)
    shutil.rmtree(TEST_KNOWLEDGE, ignore_errors=True)
    TEST_KNOWLEDGE.mkdir(parents=True)
    (TEST_KNOWLEDGE / "note.md").write_text("Redis is used for caching API responses. PostgreSQL stores durable data.")
    app.init_db()
    app.scan()


def test_health_documents_versions_and_metrics():
    with TestClient(app.app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["documents"] == 1
        assert health.json()["embedded_chunks"] == 1
        docs = client.get("/documents")
        assert docs.json()[0]["filename"] == "note.md"
        versions = client.get(f"/documents/{docs.json()[0]['id']}/versions")
        assert versions.status_code == 200
        assert versions.json()[0]["version"] == 1
        assert client.get("/metrics").status_code == 200


def test_search_chat_citations_and_evaluation():
    with TestClient(app.app) as client:
        result = client.post("/search", json={"query": "What is used for caching?"})
        assert result.status_code == 200
        assert result.json()["results"]
        assert "reranked" in result.json()["stats"]
        chat = client.post("/chat", json={"query": "What is used for caching?"})
        assert chat.status_code == 200
        assert chat.json()["citations"]
        assert "Redis" in chat.json()["answer"]
        evaluation = client.post("/evaluation/run", json={"questions": [{"question": "What is used for caching?", "expected_source": "note.md"}]})
        assert evaluation.status_code == 200
        assert evaluation.json()["recall_at_5"] == 1.0
        assert client.get("/evaluation/results").json()


def test_sync_job_is_created():
    with TestClient(app.app) as client:
        response = client.post("/documents/sync")
        assert response.status_code == 200
        job_id = response.json()["job_id"]
        status = client.get(f"/jobs/{job_id}")
        assert status.status_code == 200
        assert status.json()["kind"] == "sync"
