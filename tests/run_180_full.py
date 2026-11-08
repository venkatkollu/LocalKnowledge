#!/usr/bin/env python3
"""Run all 180 metadata questions with proper validators per category."""
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
    from backend.routing import classify_tier1
    items = [json.loads(l) for l in open(ROUTING_PATH) if l.strip()]
    correct = sum(1 for i in items if classify_tier1(i["question"]).route == i["label"])
    return {"total": len(items), "correct": correct, "accuracy": correct/len(items) if items else 1.0}


def run_in_subprocess(code: str, tmpdir: str) -> dict:
    """Execute code in isolated subprocess and extract JSON result."""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(REPO_ROOT),
        env={**os.environ, "PYTHONNOUSERSITE": "1", "KNOWLEDGEOS_DATA_DIR": tmpdir},
        capture_output=True, text=True, timeout=300,
    )
    if result.returncode != 0:
        return {"error": result.stderr[:500] or result.stdout[:500]}
    # Find JSON line - look for lines that start with { and contain key markers
    for line in result.stdout.strip().split("\n"):
        line = line.strip()
        if line.startswith("{") and any(k in line for k in ("total", "index_id", "success")):
            try:
                return json.loads(line)
            except:
                pass
    return {"error": "no JSON output: " + result.stdout[:200]}


def test_index_build() -> dict:
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
    print("ERROR: upload " + str(r.status_code), file=sys.stderr)
    sys.exit(1)

r = client.post("/api/indexes", json={{"notes": "test"}})
idx_id = r.json()["index"]["id"]

r = client.post(f"/api/indexes/{{idx_id}}/build")
if r.status_code != 200:
    print("ERROR: build", file=sys.stderr)
    sys.exit(1)

r = client.post(f"/api/indexes/{{idx_id}}/validate")
if r.status_code != 200:
    print("ERROR: validate", file=sys.stderr)
    sys.exit(1)

# Output ONLY the JSON result to stdout
print(json.dumps({{"index_id": idx_id, "success": True}}))
"""
    try:
        return run_in_subprocess(code, tmpdir)
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_metadata_category(category: str, questions: list[dict], description: str) -> dict:
    """Run metadata questions for a specific category with appropriate validator."""
    tmpdir = tempfile.mkdtemp(prefix=f"lkos-{category}-")
    questions_json = json.dumps(questions)

    # Validator logic per category
    if category == "metadata_retrieval":
        check_code = 'body.get("evidence", {}).get("decision") == "metadata_answer"'
    elif category == "citation_accuracy":
        check_code = 'len(body.get("citations", [])) > 0 and body.get("evidence", {}).get("decision") in ("answer", "answer_with_uncertainty")'
    elif category == "citation_completeness":
        # Meta-questions about citation quality - accept any non-abstain response
        check_code = 'body.get("evidence", {}).get("decision") != "abstain"'
    elif category == "metadata_preservation":
        check_code = 'body.get("evidence", {}).get("decision") == "metadata_answer"'
    else:
        check_code = 'body.get("evidence", {}).get("decision") != "abstain"'

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

# Ingest fixtures
for path in glob.glob("{FIXTURE_DIR}/*.txt"):
    with open(path, "rb") as fh:
        r = client.post("/api/documents", files={{"files": (os.path.basename(path), fh, "text/plain")}})
        if r.status_code != 200:
            print("FAIL: upload " + os.path.basename(path), file=sys.stderr)

# Build index
r = client.post("/api/indexes", json={{"notes": "test"}})
idx_id = r.json()["index"]["id"]
r = client.post(f"/api/indexes/{{idx_id}}/build")
r = client.post(f"/api/indexes/{{idx_id}}/validate")
r = client.post(f"/api/indexes/{{idx_id}}/activate")

questions = {questions_json}

results = []
passed = 0
for item in questions:
    q = item["question"]
    r = client.post("/api/chat", json={{"question": q}})
    if r.status_code == 200:
        body = r.json()
        is_ok = {check_code}
        results.append({{"id": item.get("id"), "question": q, "passed": is_ok, 
                         "decision": body.get("evidence", {{}}).get("decision"),
                         "verification": body.get("verification", {{}}).get("decision"),
                         "citations": len(body.get("citations", []))}})
        if is_ok: passed += 1
    else:
        results.append({{"id": item.get("id"), "question": q, "passed": False, "error": r.text}})

print(json.dumps({{"category": "{category}", "total": len(questions), "passed": passed, "results": results}}))
"""
    try:
        return run_in_subprocess(code, tmpdir)
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def main():
    print("=" * 70)
    print("LOCAL KNOWLEDGEOS - FULL 180 QUESTION EVALUATION")
    print("=" * 70)

    # Load all datasets
    routing_items = [json.loads(l) for l in open(ROUTING_PATH) if l.strip()]
    all_items = [json.loads(l) for l in open(METADATA_PATH) if l.strip()]

    # Group by category
    categories = {}
    for item in all_items:
        cat = item.get("category", "unknown")
        categories.setdefault(cat, []).append(item)

    print(f"\nLoaded: routing={len(routing_items)}")
    for cat, items in sorted(categories.items()):
        print(f"  {cat}: {len(items)} questions")

    all_results = {"routing": None, "index": None, "categories": {}}
    overall_passed = True

    # 1. Routing
    print("\n" + "=" * 70)
    print("TEST 1: ROUTING CLASSIFICATION")
    print("=" * 70)
    from backend.routing import classify_tier1
    correct = sum(1 for i in routing_items if classify_tier1(i["question"]).route == i["label"])
    routing_acc = correct / len(routing_items) if routing_items else 1.0
    all_results["routing"] = {"total": len(routing_items), "correct": correct, "accuracy": routing_acc}
    print(f"  Accuracy: {routing_acc:.1%} ({correct}/{len(routing_items)})")
    if routing_acc < 0.95: overall_passed = False

    # 2. Index Build
    print("\n" + "=" * 70)
    print("TEST 2: INDEX BUILD")
    print("=" * 70)
    idx = test_index_build()
    all_results["index"] = idx
    idx_ok = idx.get("success", False)
    print(f"  Status: {'PASS' if idx_ok else 'FAIL'}")
    if idx_ok: print(f"  Index: {idx.get('index_id')}")
    else: print(f"  Error: {idx.get('error')[:100]}")
    if not idx_ok: overall_passed = False

    # 3. All Metadata Categories
    print("\n" + "=" * 70)
    print("TEST 3: METADATA QUESTIONS (180 total)")
    print("=" * 70)

    for cat, items in sorted(categories.items()):
        print(f"\n  --- {cat} ({len(items)} questions) ---")
        result = test_metadata_category(cat, items, cat)
        all_results["categories"][cat] = result

        if "error" in result:
            print(f"    ERROR: {result['error'][:80]}")
            overall_passed = False
        else:
            acc = result["passed"] / max(1, result["total"])
            status = "PASS" if acc >= 0.70 else "FAIL"  # 70% threshold per category
            print(f"    {result['passed']}/{result['total']} = {acc:.1%} {status}")
            if acc < 0.70: overall_passed = False

            # Show failures
            for r in result.get("results", []):
                if not r.get("passed", False):
                    q = r["question"][:60]
                    dec = r.get("decision") or r.get("verification") or r.get("error", "unknown")
                    print(f"      ✗ {q}... -> {dec}")

    # Final Summary
    print("\n" + "=" * 70)
    print("FINAL SUMMARY")
    print("=" * 70)
    print(f"  Routing:           {routing_acc:.1%} ({correct}/{len(routing_items)})")
    print(f"  Index Build:       {'PASS' if idx_ok else 'FAIL'}")
    for cat, result in all_results["categories"].items():
        if "error" not in result:
            acc = result["passed"] / max(1, result["total"])
            print(f"  {cat:25} {acc:.1%} ({result['passed']}/{result['total']})")
    print()
    print("  OVERALL: " + ("ALL PASSED" if overall_passed else "SOME FAILED"))
    return 0 if overall_passed else 1


if __name__ == "__main__":
    sys.exit(main())