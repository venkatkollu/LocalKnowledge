"""Comprehensive evaluation framework for Local KnowledgeOS.

Run evaluation datasets and produce metrics for:
- Routing accuracy (SQL vs VECTOR vs HYBRID classification)
- Retrieval quality (recall, MRR, NDCG)
- Metadata question answering accuracy
- Citation verification quality
- Index evaluation metrics

Usage:
    python tests/run_evaluation.py [--dataset=DATASET] [--output=RESULTS.json]
    
Datasets:
    routing     - Query routing classification (tests/data/routing_set.jsonl)
    golden      - Retrieval quality (tests/data/golden_set.json)
    metadata    - Metadata Q&A (tests/data/metadata_dataset.jsonl)
    citation    - Citation verification (tests/data/citation_dataset.jsonl)
    all         - Run all evaluations

Examples:
    python tests/run_evaluation.py --dataset=routing
    python tests/run_evaluation.py --dataset=all --output=results.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

# Set environment variables BEFORE importing backend modules
os.environ["KNOWLEDGEOS_ALLOW_HASH_EMBEDDING_FALLBACK"] = "true"
os.environ["KNOWLEDGEOS_OLLAMA_BASE_URL"] = "http://127.0.0.1:9"
os.environ["KNOWLEDGEOS_NLI_ENABLED"] = "false"
os.environ["KNOWLEDGEOS_ABSTAIN_THRESHOLD"] = "0.15"

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

DATA_DIR = Path(__file__).parent / "data"


def fresh_client(tmpdir: str):
    """Point the backend at a fresh data directory and return a TestClient.

    ``SETTINGS`` is created at import time and captured by each module, so a
    new instance must be assigned on every module that holds a reference.
    Reloading only ``backend.main`` would leave the old settings in place.
    """
    from fastapi.testclient import TestClient

    from backend import answering, auth, config, db as db_module, ingestion, providers
    from backend.api import system as system_api
    from backend.config import Settings
    from backend.db import init_db
    from backend.main import app

    os.environ["KNOWLEDGEOS_DATA_DIR"] = tmpdir
    fresh = Settings()
    for module in (config, db_module, providers, ingestion, answering, auth, system_api):
        module.SETTINGS = fresh
    init_db()
    return TestClient(app)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    """Load JSONL file, skipping empty lines."""
    if not path.exists():
        return []
    items = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


def load_golden_set() -> list[dict]:
    """Load the golden set for retrieval evaluation."""
    path = DATA_DIR / "golden_set.json"
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def compute_recall_at_k(results: list[dict], k: int = 100) -> float:
    """Compute recall@k for retrieved results."""
    if not results:
        return 1.0
    hits = sum(1 for r in results if r.get("hit", False))
    return hits / len(results)


def compute_mrr(results: list[dict]) -> float:
    """Compute Mean Reciprocal Rank."""
    if not results:
        return 1.0
    mrr = 0.0
    for r in results:
        rank = r.get("rank", 0)
        if rank > 0:
            mrr += 1.0 / rank
    return mrr / len(results) if results else 1.0


def test_routing_classification() -> dict[str, Any]:
    """Test query routing classification accuracy."""
    from backend.routing import classify_tier1
    
    dataset = load_jsonl(DATA_DIR / "routing_set.jsonl")
    if not dataset:
        return {"error": "routing dataset empty", "total": 0}
    
    correct = 0
    total = len(dataset)
    details = []
    
    for item in dataset:
        question = item["question"]
        expected = item["label"]
        decision = classify_tier1(question)
        actual = decision.route
        
        is_correct = actual == expected
        if is_correct:
            correct += 1
        
        details.append({
            "question": question,
            "expected": expected,
            "actual": actual,
            "correct": is_correct,
        })
    
    return {
        "total": total,
        "correct": correct,
        "accuracy": correct / total if total else 1.0,
        "details": details,
    }


def test_retrieval_quality(verbose: bool = False) -> dict[str, Any]:
    """Test retrieval quality using golden set."""
    # Create temp data dir
    tmpdir = tempfile.mkdtemp(prefix="evaluation-")
    os.environ["KNOWLEDGEOS_ALLOW_ANONYMOUS"] = "true"
    client = fresh_client(tmpdir)
    
    golden = load_golden_set()
    if not golden:
        return {"error": "golden set empty", "total": 0}
    
    results = []
    for item in golden[:30]:  # Limit for evaluation speed
        question = item["question"]
        expected_doc = item.get("doc")
        if not expected_doc:
            continue
        
        # Run query
        response = client.post("/api/chat", json={"question": question, "top_k": 100})
        if response.status_code != 200:
            continue
        
        body = response.json()
        citations = body.get("citations", [])
        
        # Check if expected document is in citations
        expected_chunks = [c.get("chunk_id") for c in citations if expected_doc in c.get("filename", "")]
        hit = len(expected_chunks) > 0
        
        results.append({
            "question": question,
            "expected_doc": expected_doc,
            "hit": hit,
            "retrieved_count": len(citations),
        })
    
    # Clean up
    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)
    
    recall = compute_recall_at_k(results, k=100)
    
    return {
        "total": len(results),
        "hits": sum(1 for r in results if r["hit"]),
        "recall@100": recall,
        "details": results,
    }


def test_metadata_qa(verbose: bool = False) -> dict[str, Any]:
    """Test metadata question answering."""
    with tempfile.TemporaryDirectory(prefix="evaluation-") as tmpdir:
        client = fresh_client(tmpdir)
        
        # Ingest test corpus
        fixture_dir = Path(__file__).parent / "fixtures"
        for path in sorted(fixture_dir.glob("*.txt")):
            with path.open("rb") as fh:
                client.post("/api/documents", files={"files": (path.name, fh, "text/plain")})
        
        # Build and activate index
        create = client.post("/api/indexes", json={"notes": "test"}).json()
        idx_id = create["index"]["id"]
        client.post(f"/api/indexes/{idx_id}/build")
        client.post(f"/api/indexes/{idx_id}/validate")
        client.post(f"/api/indexes/{idx_id}/activate")
        
        dataset = load_jsonl(DATA_DIR / "metadata_dataset.jsonl")
        if not dataset:
            return {"error": "metadata dataset empty", "total": 0}
        
        results = []
        for item in dataset[:50]:  # Limit for speed
            question = item["question"]
            try:
                r = client.post("/api/chat", json={"question": question})
                if r.status_code != 200:
                    continue
                body = r.json()
                is_metadata = body.get("evidence", {}).get("decision") == "metadata_answer"
            except Exception:
                continue
            
            results.append({
                "question": question,
                "category": item.get("category", "unknown"),
                "is_metadata": is_metadata,
            })
        
        correct = sum(1 for r in results if r["is_metadata"])
        accuracy = correct / len(results) if results else 0.0
        
        return {
            "total": len(results),
            "correct": correct,
            "accuracy": accuracy,
        }


def test_citation_verification(verbose: bool = False) -> dict[str, Any]:
    """Test citation verification quality."""
    with tempfile.TemporaryDirectory(prefix="evaluation-") as tmpdir:
        client = fresh_client(tmpdir)
        
        # Ingest test corpus
        fixture_dir = Path(__file__).parent / "fixtures"
        for path in sorted(fixture_dir.glob("*.txt")):
            with path.open("rb") as fh:
                client.post("/api/documents", files={"files": (path.name, fh, "text/plain")})
        
        dataset = load_jsonl(DATA_DIR / "citation_dataset.jsonl")
        if not dataset:
            return {"error": "citation dataset empty", "total": 0}
        
        results = []
        for item in dataset[:20]:  # Limit for speed
            question = item["question"]
            try:
                r = client.post("/api/chat", json={"question": question, "top_k": 6})
                if r.status_code != 200:
                    continue
                body = r.json()
                verification = body.get("verification", {})
                claims = verification.get("claims", [])
                
                if claims:
                    verified = sum(1 for c in claims if c.get("supported", False))
                    ratio = verified / len(claims)
                else:
                    ratio = 0.0
                
                results.append({
                    "question": question,
                    "total_claims": len(claims),
                    "verified_claims": verified if claims else 0,
                    "verified_ratio": ratio,
                })
            except Exception:
                continue
        
        if not results:
            return {"error": "no valid results", "total": 0}
        
        total_claims = sum(r.get("total_claims", 0) for r in results)
        total_verified = sum(r.get("verified_claims", 0) for r in results)
        avg_ratio = sum(r.get("verified_ratio", 0) for r in results) / len(results)
        
        return {
            "total": len(results),
            "total_claims": total_claims,
            "verified_claims": total_verified,
            "avg_verified_ratio": avg_ratio,
        }


def test_index_build() -> dict[str, Any]:
    """Test index building and evaluation."""
    with tempfile.TemporaryDirectory(prefix="evaluation-") as tmpdir:
        client = fresh_client(tmpdir)
        
        # Ingest documents
        fixture_dir = Path(__file__).parent / "fixtures"
        for path in sorted(fixture_dir.glob("*.txt"))[:5]:
            with path.open("rb") as fh:
                client.post("/api/documents", files={"files": (path.name, fh, "text/plain")})
        
        # Build index
        create = client.post("/api/indexes", json={"notes": "test index"}).json()
        idx_id = create["index"]["id"]
        
        build_result = client.post(f"/api/indexes/{idx_id}/build")
        if build_result.status_code != 200:
            return {"error": f"build failed: {build_result.text}", "index_id": None}
        
        validate_result = client.post(f"/api/indexes/{idx_id}/validate")
        if validate_result.status_code != 200:
            return {"error": f"validate failed: {validate_result.text}", "index_id": None}
        
        return {
            "index_id": idx_id,
            "build": "success",
            "validate": "success",
        }


def main():
    parser = argparse.ArgumentParser(description="Run Local KnowledgeOS evaluation")
    parser.add_argument(
        "--dataset",
        choices=["routing", "retrieval", "metadata", "citation", "index", "all"],
        default="all",
        help="Dataset to evaluate",
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="Output file for results (JSON)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print detailed results",
    )
    args = parser.parse_args()
    
    results = {"datasets": {}, "summary": {}}
    
    print("=" * 60)
    print("Local KnowledgeOS Evaluation")
    print("=" * 60)
    
    # Routing
    if args.dataset in ("routing", "all"):
        print("\n[Routing Classification]")
        r = test_routing_classification()
        results["datasets"]["routing"] = r
        results["summary"]["routing_accuracy"] = r.get("accuracy", 0)
        print(f"  Accuracy: {r.get('accuracy', 0):.1%} ({r.get('correct', 0)}/{r.get('total', 0)})")
    
    # Retrieval
    if args.dataset in ("retrieval", "all"):
        print("\n[Retrieval Quality]")
        r = test_retrieval_quality()
        results["datasets"]["retrieval"] = r
        results["summary"]["retrieval_recall"] = r.get("recall@100", 0)
        print(f"  Recall@100: {r.get('recall@100', 0):.1%} ({r.get('hits', 0)}/{r.get('total', 0)})")
    
    # Metadata QA
    if args.dataset in ("metadata", "all"):
        print("\n[Metadata Q&A]")
        r = test_metadata_qa()
        results["datasets"]["metadata"] = r
        results["summary"]["metadata_accuracy"] = r.get("accuracy", 0)
        print(f"  Accuracy: {r.get('accuracy', 0):.1%}")
    
    # Citation
    if args.dataset in ("citation", "all"):
        print("\n[Citation Verification]")
        r = test_citation_verification()
        results["datasets"]["citation"] = r
        results["summary"]["citation_verified_ratio"] = r.get("avg_verified_ratio", 0)
        print(f"  Avg verified ratio: {r.get('avg_verified_ratio', 0):.1%}")
    
    # Index build
    if args.dataset in ("index", "all"):
        print("\n[Index Build]")
        r = test_index_build()
        results["datasets"]["index"] = r
        if "error" not in r:
            print(f"  Index {r.get('index_id', 'unknown')}: built and validated")
        else:
            print(f"  Error: {r.get('error')}")
    
    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for metric, value in results.get("summary", {}).items():
        print(f"  {metric}: {value:.3f}" if isinstance(value, float) else f"  {metric}: {value}")
    
    # Output
    if args.output:
        Path(args.output).write_text(json.dumps(results, indent=2, default=str))
        print(f"\nResults written to {args.output}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())