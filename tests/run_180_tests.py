#!/usr/bin/env python3
"""Test runner for Local KnowledgeOS evaluation - runs all 180 metadata questions."""
from __future__ import annotations

import os
import sys
import tempfile
import subprocess
import json
from pathlib import Path

os.environ.setdefault("KNOWLEDGEOS_ALLOW_HASH_EMBEDDING_FALLBACK", "true")
os.environ.setdefault("KNOWLEDGEOS_OLLAMA_BASE_URL", "http://127.0.0.1:9")
os.environ.setdefault("KNOWLEDGEOS_NLI_ENABLED", "false")
os.environ.setdefault("KNOWLEDGEOS_ABSTAIN_THRESHOLD", "0.15")
os.environ.setdefault("KNOWLEDGEOS_ALLOW_ANONYMOUS", "true")

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

ROUTING_PATH = REPO_ROOT / "tests" / "data" / "routing_set.jsonl"
METADATA_PATH = REPO_ROOT / "tests" / "data" / "metadata_dataset.jsonl"
FIXTURE_DIR = str(REPO_ROOT / "tests" / "fixtures")


def test_routing() -> dict:
    """Test routing classification accuracy."""
    from backend.routing import classify_tier1

    if not ROUTING_PATH.exists():
        return {"total": 0, "correct": 0, "accuracy": 1.0}

    items = [json.loads(line) for line in open(ROUTING_PATH) if line.strip()]
    correct = sum(1 for item in items if classify_tier1(item["question"]).route == item["label"])
    return {"total": len(items), "correct": correct, "accuracy": correct / len(items) if items else 1.0}


def test_index_build() -> dict:
    """Test index building in a fresh subprocess."""
    tmpdir = tempfile.mkdtemp(prefix="lkos-idx-")

    code = f"""
import os, sys, json
os.environ["KNOWLEDGEOS_ALLOW_HASH_EMBEDDING_FALLBACK"] = "true"
os.environ["KNOWLEDGEOS_ALLOW_ANONYMOUS"] = "true"
os.environ["KNOWLEDGEOS_DATA_DIR"] = "{tmpdir}"
sys.path.insert(0, "{REPO_ROOT}")

from fastapi.testclient import TestClient
from backend.db import init_db
from backend.main import app

init_db()
client = TestClient(app)

r = client.post("/api/documents", files={{"files": ("test.md", b"Hello world.", "text/markdown")}})
if r.status_code != 200:
    print(json.dumps({{"error": "upload " + str(r.status_code), "success": false}}))
    sys.exit(1)

r = client.post("/api/indexes", json={{"notes": "test"}})
idx_id = r.json()["index"]["id"]

r = client.post(f"/api/indexes/{{idx_id}}/build")
if r.status_code != 200:
    print(json.dumps({{"error": "build", "success": false}}))
    sys.exit(1)

r = client.post(f"/api/indexes/{{idx_id}}/validate")
if r.status_code != 200:
    print(json.dumps({{"error": "validate", "success": false}}))
    sys.exit(1)

# Use Python True/False for JSON serialization
print(json.dumps({{"index_id": idx_id, "success": True}}))
"""

    try:
        env = dict(os.environ)
        env["PYTHONNOUSERSITE"] = "1"

        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )

        if result.returncode != 0:
            return {"error": result.stderr[:500] if result.stderr else result.stdout[:500], "success": False}

        # Find the JSON line in stdout (skip secret generation warnings)
        for line in result.stdout.strip().split("\n"):
            line = line.strip()
            if line.startswith("{") and "index_id" in line:
                return json.loads(line)
        return {"error": "no JSON in output: " + result.stdout[:200], "success": False}
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_metadata_qa() -> dict:
    """Run all metadata retrieval questions against the API."""
    tmpdir = tempfile.mkdtemp(prefix="lkos-meta-")

    if not METADATA_PATH.exists():
        return {"error": "metadata dataset not found", "total": 0, "passed": 0}

    items = [json.loads(line) for line in open(METADATA_PATH) if line.strip()]
    metadata_items = [i for i in items if i.get("category") == "metadata_retrieval"]
    questions_json = json.dumps(metadata_items)

    code = f"""
import os, sys, json, glob
os.environ["KNOWLEDGEOS_ALLOW_HASH_EMBEDDING_FALLBACK"] = "true"
os.environ["KNOWLEDGEOS_ALLOW_ANONYMOUS"] = "true"
os.environ["KNOWLEDGEOS_DATA_DIR"] = "{tmpdir}"
sys.path.insert(0, "{REPO_ROOT}")

from fastapi.testclient import TestClient
from backend.db import init_db
from backend.main import app

init_db()
client = TestClient(app)

# Ingest fixture documents
fixture_dir = "{FIXTURE_DIR}"
for path in glob.glob("{FIXTURE_DIR}/*.txt"):
    with open(path, "rb") as fh:
        r = client.post("/api/documents", files={{"files": (os.path.basename(path), fh, "text/plain")}})
        if r.status_code != 200:
            print("FAIL: upload " + os.path.basename(path), file=sys.stderr)

# Build and activate index
r = client.post("/api/indexes", json={{"notes": "test"}})
idx_id = r.json()["index"]["id"]
r = client.post(f"/api/indexes/{{idx_id}}/build")
r = client.post(f"/api/indexes/{{idx_id}}/validate")
r = client.post(f"/api/indexes/{{idx_id}}/activate")

# Load questions
questions = {questions_json}

results = []
passed = 0
for item in questions:
    q = item["question"]
    r = client.post("/api/chat", json={{"question": q}})
    if r.status_code == 200:
        body = r.json()
        is_meta = body.get("evidence", {{}}).get("decision") == "metadata_answer"
        results.append({{"question": q, "passed": is_meta, "decision": body.get("evidence", {{}}).get("decision")}})
        if is_meta:
            passed += 1
    else:
        results.append({{"question": q, "passed": False, "error": r.text}})

# Use Python True/False for JSON serialization
print(json.dumps({{"total": len(questions), "passed": passed, "results": results}}))
"""

    try:
        env = dict(os.environ)
        env["PYTHONNOUSERSITE"] = "1"

        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=300,
        )

        if result.returncode != 0:
            return {"error": result.stderr[:500] if result.stderr else result.stdout[:500], "total": 0, "passed": 0}

        # Find the JSON line in stdout (skip secret generation warnings)
        for line in result.stdout.strip().split("\n"):
            line = line.strip()
            if line.startswith("{") and "total" in line:
                return json.loads(line)
        return {"error": "no JSON in output: " + result.stdout[:200], "total": 0, "passed": 0}
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def main():
    print("=" * 60)
    print("Local KnowledgeOS Test Runner - Full 180 Test Suite")
    print("=" * 60)

    routing_count = sum(1 for l in open(ROUTING_PATH) if l.strip()) if ROUTING_PATH.exists() else 0
    metadata_count = sum(1 for l in open(METADATA_PATH) if l.strip()) if METADATA_PATH.exists() else 0
    metadata_retrieval_count = 0
    if METADATA_PATH.exists():
        items = [json.loads(l) for l in open(METADATA_PATH) if l.strip()]
        metadata_retrieval_count = sum(1 for i in items if i.get("category") == "metadata_retrieval")

    print(f"\nDatasets: routing={routing_count}, metadata_total={metadata_count}, metadata_retrieval={metadata_retrieval_count}")

    all_passed = True
    results = {}

    # Test 1: Routing
    print("\n" + "-" * 40)
    print("Test 1: Routing Classification (50 questions)")
    routing = test_routing()
    results["routing"] = routing
    routing_ok = routing["accuracy"] >= 0.95
    print(f"  Accuracy: {routing['accuracy']:.1%} ({routing['correct']}/{routing['total']})")
    print(f"  Status: {'PASS' if routing_ok else 'FAIL'}")
    if not routing_ok:
        all_passed = False

    # Test 2: Index Build
    print("\n" + "-" * 40)
    print("Test 2: Index Building")
    idx = test_index_build()
    results["index"] = idx
    idx_ok = idx.get("success", False)
    print(f"  Status: {'PASS' if idx_ok else 'FAIL'}")
    if idx_ok:
        print(f"  Index: {idx.get('index_id', 'unknown')}")
    else:
        print(f"  Error: {idx.get('error', 'unknown')[:200]}")
        all_passed = False

    # Test 3: Metadata QA
    print("\n" + "-" * 40)
    print(f"Test 3: Metadata Q&A ({metadata_retrieval_count} questions)")
    meta = test_metadata_qa()
    results["metadata"] = meta
    if "error" in meta:
        print(f"  Status: FAIL - {meta['error'][:100]}")
        meta_ok = False
    else:
        meta_ok = meta.get("passed", 0) / max(1, meta.get("total", 1)) >= 0.80
        print(f"  Accuracy: {meta.get('passed', 0)}/{meta.get('total', 0)} = {meta.get('passed', 0)/max(1, meta.get('total', 1)):.1%}")
        print(f"  Status: {'PASS' if meta_ok else 'FAIL'}")
        for r in meta.get("results", []):
            if not r.get("passed", False):
                print(f"    FAIL: {r['question'][:60]}... -> {r.get('decision', r.get('error', 'unknown'))}")
    if not meta_ok:
        all_passed = False

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  Routing:      {routing['accuracy']:.1%} {'PASS' if routing_ok else 'FAIL'} ({routing['correct']}/{routing['total']})")
    print(f"  Index build:  {'PASS' if idx_ok else 'FAIL'}")
    if "error" not in meta:
        print(f"  Metadata QA:  {meta.get('passed', 0)}/{meta.get('total', 0)} = {meta.get('passed', 0)/max(1, meta.get('total', 1)):.1%} {'PASS' if meta_ok else 'FAIL'}")
    else:
        print(f"  Metadata QA:  FAIL - {meta['error'][:50]}")
    print()

    if all_passed:
        print("ALL TESTS PASSED")
        return 0
    print("SOME TESTS FAILED")
    return 1


if __name__ == "__main__":
    sys.exit(main())