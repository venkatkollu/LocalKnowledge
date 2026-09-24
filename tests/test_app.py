import os
from pathlib import Path

os.environ["KNOWLEDGEOS_AUTO_SYNC"] = "0"
os.environ["KNOWLEDGEOS_DATA"] = "/tmp/knowledgeos-test-data"
os.environ["KNOWLEDGEOS_KNOWLEDGE"] = "/tmp/knowledgeos-test-knowledge"
os.environ["KNOWLEDGEOS_DB"] = "/tmp/knowledgeos-test-data/test.db"

from fastapi.testclient import TestClient
import app


def setup_module():
    import shutil
    shutil.rmtree("/tmp/knowledgeos-test-data", ignore_errors=True)
    shutil.rmtree("/tmp/knowledgeos-test-knowledge", ignore_errors=True)
    Path("/tmp/knowledgeos-test-knowledge").mkdir(parents=True)
    Path("/tmp/knowledgeos-test-knowledge/note.md").write_text("Redis is used for caching API responses. PostgreSQL stores durable data.")
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
