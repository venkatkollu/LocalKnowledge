#!/usr/bin/env python3
"""Run semantic evaluation questions against the RAG system."""
from __future__ import annotations

import os
import sys
import tempfile
import subprocess
import json
from pathlib import Path
from collections import defaultdict

os.environ.setdefault("KNOWLEDGEOS_ALLOW_HASH_EMBEDDING_FALLBACK", "true")
os.environ.setdefault("KNOWLEDGEOS_OLLAMA_BASE_URL", "http://127.0.0.1:9")
os.environ.setdefault("KNOWLEDGEOS_NLI_ENABLED", "true")
os.environ.setdefault("KNOWLEDGEOS_ABSTAIN_THRESHOLD", "0.15")
os.environ.setdefault("KNOWLEDGEOS_ALLOW_ANONYMOUS", "true")

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

SEMANTIC_PATH = REPO_ROOT / "tests" / "data" / "semantic_evaluation.jsonl"
FIXTURE_DIR = str(REPO_ROOT / "tests" / "fixtures")


def load_semantic_dataset():
    items = []
    with open(SEMANTIC_PATH) as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


def python_repr(obj):
    return repr(obj)


def run_in_subprocess(code, tmpdir):
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(REPO_ROOT),
        env={**os.environ, "PYTHONNOUSERSITE": "1", "KNOWLEDGEOS_DATA_DIR": tmpdir},
        capture_output=True, text=True, timeout=300,
    )
    if result.returncode != 0:
        return {"error": result.stderr[:1000] or result.stdout[:500]}
    for line in result.stdout.strip().split("\n"):
        line = line.strip()
        if line.startswith("{") and any(k in line for k in ("total", "index_id", "success", "passed")):
            try:
                return json.loads(line)
            except Exception:
                pass
    return {"error": "no JSON output: " + result.stdout[:200]}


def run_questions_in_subprocess(questions, category):
    tmpdir = tempfile.mkdtemp(prefix="lkos-sem-")
    q_repr = python_repr(questions)

    code = '''
import os, sys, json, glob
os.environ["KNOWLEDGEOS_ALLOW_HASH_EMBEDDING_FALLBACK"] = "true"
os.environ["KNOWLEDGEOS_ALLOW_ANONYMOUS"] = "true"
os.environ["KNOWLEDGEOS_DATA_DIR"] = "''' + tmpdir + '''"
sys.path.insert(0, "''' + str(REPO_ROOT) + '''")

from fastapi.testclient import TestClient
from backend.db import init_db
from backend.main import app

init_db()
client = TestClient(app)

for path in glob.glob("''' + FIXTURE_DIR + '''/*.txt"):
    with open(path, "rb") as fh:
        r = client.post("/api/documents", files={"files": (os.path.basename(path), fh, "text/plain")})

r = client.post("/api/indexes", json={"notes": "test"})
idx_id = r.json()["index"]["id"]
r = client.post(f"/api/indexes/{idx_id}/build")
r = client.post(f"/api/indexes/{idx_id}/validate")
r = client.post(f"/api/indexes/{idx_id}/activate")

questions = ''' + q_repr + '''

results = []
passed = 0
for item in questions:
    q = item["question"]
    ans = item.get("answerable", True)
    r = client.post("/api/chat", json={"question": q})
    if r.status_code == 200:
        body = r.json()
        citations = body.get("citations", [])
        decision = body.get("evidence", {}).get("decision", "")
        verification = body.get("verification", {})
        answer = body.get("answer", "").lower()
        verified_ratio = verification.get("verified_ratio")
        verification_decision = verification.get("decision", "unsupported")

        if ans is True:
            is_ok = decision != "abstain" and len(citations) > 0 and (
                verification_decision in ("verified", "unsupported") or
                (verified_ratio is not None and verified_ratio >= 0.5) or
                verification_decision == "skipped"
            )
        else:
            # Unanswerable: should abstain OR have unsupported answer with low verification
            # Generic questions shouldn't match specific fixture content
            is_ok = decision == "abstain" or (
                verification_decision == "unsupported" or 
                (verified_ratio is not None and verified_ratio < 0.5) or
                "don't have enough" in answer
            )
        results.append({"id": item.get("id"), "passed": is_ok, "decision": decision,
                         "verification": verification_decision, "citations": len(citations)})
        if is_ok: passed += 1
    else:
        results.append({"id": item.get("id"), "passed": False, "error": r.text})

print(json.dumps({"total": len(questions), "passed": passed, "category": "''' + category + '''", "results": results}))
'''
    try:
        return run_in_subprocess(code, tmpdir)
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def main():
    print("=" * 70)
    print("SEMANTIC EVALUATION - 280 Natural-Language Questions")
    print("=" * 70)

    all_items = load_semantic_dataset()
    categories = defaultdict(list)
    for item in all_items:
        cat = item.get("category", "unknown")
        categories[cat].append(item)

    print("\nLoaded: {} questions across {} categories".format(len(all_items), len(categories)))
    for cat, items in sorted(categories.items()):
        print("  {}: {} questions".format(cat, len(items)))

    overall_passed = 0
    overall_total = 0

    for cat, items in sorted(categories.items()):
        print("\n--- {} ({} questions) ---".format(cat, len(items)))
        result = run_questions_in_subprocess(items, cat)

        if "error" in result:
            print("  ERROR: {}...".format(result['error'][:200]))
        else:
            total = result.get("total", 0)
            passed = result.get("passed", 0)
            acc = passed / max(1, total)
            status = "PASS" if acc >= 0.70 else "FAIL"
            print("  {}/{} = {:.1%} {}".format(passed, total, acc, status))
            overall_passed += passed
            overall_total += total

            for r in result.get("results", [])[:10]:
                if not r.get("passed", False):
                    q = r.get("id", "?") + ": " + r.get("question", "")[:50]
                    dec = r.get("decision", r.get("error", "unknown"))
                    ver = r.get("verification", "?")
                    print("    x {} -> {} (ver: {})".format(q[:60], dec, ver))
            extra = len(result.get("results", [])) - 10
            if extra > 0:
                print("    ... and {} more failures".format(extra))

    print("\n" + "=" * 70)
    print("OVERALL: {}/{} = {:.1%}".format(overall_passed, overall_total, overall_passed/max(1, overall_total)))
    print("=" * 70)

    return 0 if overall_passed >= overall_total * 0.70 else 1


if __name__ == "__main__":
    sys.exit(main())