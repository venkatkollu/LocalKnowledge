#!/usr/bin/env python3
"""Debug script to inspect specific test failures."""
import os, sys, json, glob, tempfile, subprocess
from pathlib import Path
from collections import defaultdict

os.environ["KNOWLEDGEOS_ALLOW_HASH_EMBEDDING_FALLBACK"] = "true"
os.environ["KNOWLEDGEOS_OLLAMA_BASE_URL"] = "http://127.0.0.1:9"
os.environ["KNOWLEDGEOS_NLI_ENABLED"] = "false"
os.environ["KNOWLEDGEOS_ABSTAIN_THRESHOLD"] = "0.15"
os.environ["KNOWLEDGEOS_ALLOW_ANONYMOUS"] = "true"

REPO_ROOT = Path("/home/venkatkollu/Downloads/projects/local-knowledgeos-permanent/localrag")
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


def python_repr(obj, indent=0):
    return repr(obj)


def run_subprocess_test(questions, category):
    tmpdir = tempfile.mkdtemp(prefix=f"lkos-debug-{category[:8]}-")
    q_repr = python_repr(questions)

    code_parts = [
        "import os, sys, json, glob",
        'os.environ["KNOWLEDGEOS_ALLOW_HASH_EMBEDDING_FALLBACK"] = "true"',
        'os.environ["KNOWLEDGEOS_ALLOW_ANONYMOUS"] = "true"',
        f'os.environ["KNOWLEDGEOS_DATA_DIR"] = """{tmpdir}"""',
        f'sys.path.insert(0, """{REPO_ROOT}""")',
        "",
        "from fastapi.testclient import TestClient",
        "from backend.db import init_db",
        "from backend.main import app",
        "",
        "init_db()",
        "client = TestClient(app)",
        "",
        "# Ingest fixtures",
        "for path in glob.glob(\"" + FIXTURE_DIR + "/*.txt\"):",
        "    with open(path, 'rb') as fh:",
        '        r = client.post("/api/documents", files={"files": (os.path.basename(path), fh, "text/plain")})',
        "",
        "# Build index",
        'r = client.post("/api/indexes", json={"notes": "test"})',
        'idx_id = r.json()["index"]["id"]',
        'r = client.post(f"/api/indexes/{idx_id}/build")',
        'r = client.post(f"/api/indexes/{idx_id}/validate")',
        'r = client.post(f"/api/indexes/{idx_id}/activate")',
        "",
        "questions = " + q_repr,
        "",
        "results = []",
        "passed = 0",
        "for item in questions:",
        '    q = item["question"]',
        '    ans = item.get("answerable", True)',
        '    r = client.post("/api/chat", json={"question": q})',
        "    if r.status_code == 200:",
        "        body = r.json()",
        '        citations = body.get("citations", [])',
        '        decision = body.get("evidence", {}).get("decision", "")',
        '        answer = body.get("answer", "").lower()',
        "",
        "        if ans is True:",
        '            is_ok = decision != "abstain" and len(citations) > 0',
        "        else:",
        '            is_ok = decision == "abstain" or "don\'t have enough" in answer',
        "",
        '        results.append({"id": item.get("id"), "passed": is_ok, "decision": decision, "citations": len(citations), "answer": body.get("answer", "")[:150]})',
        "        if is_ok: passed += 1",
        "    else:",
        '        results.append({"id": item.get("id"), "passed": False, "error": r.text})',
        "",
        'print(json.dumps({"total": len(questions), "passed": passed, "results": results}))',
    ]

    code = "\n".join(code_parts)

    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(REPO_ROOT),
        env={**os.environ, "PYTHONNOUSERSITE": "1", "KNOWLEDGEOS_DATA_DIR": tmpdir},
        capture_output=True, text=True, timeout=300,
    )

    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)

    if result.returncode != 0:
        return {"error": result.stderr[:1000] or result.stdout[:500]}

    for line in result.stdout.strip().split("\n"):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except Exception:
                pass
    return {"error": "no JSON output: " + result.stdout[:200]}


def main():
    all_items = load_semantic_dataset()

    # Find the failing unanswered questions
    unanswerable = [i for i in all_items if i.get("category") == "ambiguous_unanswerable" and not i.get("answerable", True)]

    print(f"Testing {len(unanswerable)} unanswerable questions...")
    result = run_subprocess_test(unanswerable, "unanswered")

    if "error" in result:
        print(f"Error: {result['error'][:300]}")
        return

    print(f"Passed: {result['passed']}/{result['total']}")
    for r in result.get("results", []):
        print(f"  {r.get('id')}: {r.get('decision')} - {r.get('answer', '')[:80]}")


if __name__ == "__main__":
    main()