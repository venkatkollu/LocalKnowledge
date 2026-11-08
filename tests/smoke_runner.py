#!/usr/bin/env python3
"""Comprehensive test runner using subprocess isolation."""
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

print("=" * 60)
print("Local KnowledgeOS Test Suite")
print("=" * 60)

# Test 1: Routing Classification
print("\n[1] Routing Classification")
from backend.routing import classify_tier1

test_cases = [
    ("How many documents are in this workspace?", "SQL"),
    ("What does the policy say about refunds?", "VECTOR"),
    ("Which document discusses compliance and what does it say?", "HYBRID"),
    ("Documents uploaded this month", "SQL"),
    ("Explain the chunking strategy", "VECTOR"),
]

correct = sum(1 for q, exp in test_cases if classify_tier1(q).route == exp)
accuracy = correct / len(test_cases)
print(f"  Accuracy: {accuracy:.1%} ({correct}/{len(test_cases)})")

# Test 2: Index Build (in subprocess for isolation)
print("\n[2] Index Build")
tmpdir = tempfile.mkdtemp(prefix="lkos-idx-")
try:
    env = dict(os.environ)
    env["KNOWLEDGEOS_DATA_DIR"] = tmpdir
    
    code = '''
import os
os.environ["KNOWLEDGEOS_ALLOW_HASH_EMBEDDING_FALLBACK"] = "true"
os.environ["KNOWLEDGEOS_ALLOW_ANONYMOUS"] = "true"

from fastapi.testclient import TestClient
from backend.main import app
from backend.db import init_db

init_db()
client = TestClient(app)

r = client.post("/api/documents", files={"files": ("test.md", b"Hello world.", "text/markdown")})
if r.status_code != 200:
    print("ERROR: upload failed")
    exit(1)

r = client.post("/api/indexes", json={"notes": "test"})
idx_id = r.json()["index"]["id"]

r = client.post(f"/api/indexes/{idx_id}/build")
if r.status_code != 200:
    print("ERROR: build failed")
    exit(1)

r = client.post(f"/api/indexes/{idx_id}/validate")
if r.status_code != 200:
    print("ERROR: validate failed")
    exit(1)

print(f"Index built: {idx_id}")
'''
    
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    
    if result.returncode == 0:
        print(f"  Status: PASS")
        print(f"  {result.stdout.strip()}")
    else:
        print(f"  Status: FAIL")
        print(f"  {result.stderr[:200]}")
finally:
    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)

# Summary
print("\n" + "=" * 60)
print("SUMMARY")
print("=" * 60)
routing_ok = accuracy >= 0.95
print(f"  Routing accuracy: {accuracy:.1%} {'PASS' if routing_ok else 'FAIL'}")
print(f"  Index build:       {'PASS' if result.returncode == 0 else 'FAIL'}")
print()

if routing_ok and result.returncode == 0:
    print("ALL TESTS PASSED")
    sys.exit(0)
else:
    print("SOME TESTS FAILED")
    sys.exit(1)