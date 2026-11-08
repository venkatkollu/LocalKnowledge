"""Evaluation datasets for Local KnowledgeOS.

This module provides structured evaluation datasets for testing:
- Routing accuracy (SQL vs VECTOR vs HYBRID classification)
- Metadata question answering
- Citation accuracy and completeness
- Retrieval quality (recall, NDCG, MRR)
- Abstention behavior
- Verification quality

Usage:
    python -m pytest tests/test_evaluation_run.py -v
    python tests/run_evaluation.py --dataset=metadata --output=results.json
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DATASET_DIR = Path(__file__).parent / "data"


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


def load_golden_set() -> list[dict[str, str]]:
    """Load the golden set for retrieval evaluation.
    
    Each item has:
    - question: the query to ask
    - doc: expected document fixture name (e.g., "lora.txt")
    """
    path = DATASET_DIR / "golden_set.json"
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_routing_dataset() -> list[dict[str, Any]]:
    """Load routing classification dataset.
    
    Each item has:
    - id: unique identifier
    - question: the query
    - label: expected route (SQL, VECTOR, HYBRID)
    - notes: optional explanation
    """
    return load_jsonl(DATASET_DIR / "routing_set.jsonl")


def load_metadata_dataset() -> list[dict[str, Any]]:
    """Load metadata question answering dataset.
    
    Each item has:
    - id: unique identifier
    - question: the query
    - label: expected route (always SQL for metadata)
    - category: subcategory (metadata_retrieval, metadata_preservation, etc.)
    """
    return load_jsonl(DATASET_DIR / "metadata_dataset.jsonl")


def load_citation_dataset() -> list[dict[str, Any]]:
    """Load citation accuracy dataset.
    
    Each item has:
    - id: unique identifier
    - question: the query
    - label: expected route (VECTOR)
    - category: citation_accuracy or citation_completeness
    """
    return load_jsonl(DATASET_DIR / "citation_dataset.jsonl")


def get_dataset_summary() -> dict[str, int]:
    """Return counts of items in each dataset."""
    return {
        "golden_set": len(load_golden_set()),
        "routing": len(load_routing_dataset()),
        "metadata": len(load_metadata_dataset()),
        "citation": len(load_citation_dataset()),
    }


# --- Metric computation helpers ---------------------------------------------

def compute_recall_at_k(predictions: list[dict], k: int = 100) -> float:
    """Compute recall@k for retrieval evaluation.
    
    Args:
        predictions: List of {question, expected_chunk_id, retrieved_chunk_ids}
        k: Number of top results to consider
    
    Returns:
        Recall score (0.0 to 1.0)
    """
    if not predictions:
        return 1.0
    
    hits = 0
    for pred in predictions:
        expected = pred.get("expected_chunk_id")
        retrieved = pred.get("retrieved_chunk_ids", [])[:k]
        if expected and expected in retrieved:
            hits += 1
    
    return hits / len(predictions)


def compute_mrr(predictions: list[dict]) -> float:
    """Compute Mean Reciprocal Rank.
    
    Args:
        predictions: List of {question, expected_chunk_id, retrieved_chunk_ids}
    
    Returns:
        MRR score (0.0 to 1.0)
    """
    if not predictions:
        return 1.0
    
    reciprocal_ranks = []
    for pred in predictions:
        expected = pred.get("expected_chunk_id")
        retrieved = pred.get("retrieved_chunk_ids", [])
        
        if expected and expected in retrieved:
            rank = retrieved.index(expected) + 1
            reciprocal_ranks.append(1.0 / rank)
        else:
            reciprocal_ranks.append(0.0)
    
    return sum(reciprocal_ranks) / len(reciprocal_ranks)


def compute_ndcg_at_k(predictions: list[dict], k: int = 10) -> float:
    """Compute NDCG@k for retrieval evaluation.
    
    Args:
        predictions: List of {question, expected_chunk_id, retrieved_chunk_ids, scores}
        k: Number of top results to consider
    
    Returns:
        NDCG score (0.0 to 1.0)
    """
    import math
    
    if not predictions:
        return 1.0
    
    ndcg_scores = []
    for pred in predictions:
        expected = pred.get("expected_chunk_id")
        retrieved = pred.get("retrieved_chunk_ids", [])[:k]
        scores = pred.get("scores", [1.0] * len(retrieved))
        
        # DCG: sum of (2^rel - 1) / log2(rank + 1)
        dcg = 0.0
        idcg = 0.0
        
        for i, (chunk_id, score) in enumerate(zip(retrieved, scores)):
            rel = 1.0 if chunk_id == expected else 0.0
            dcg += (2**rel - 1) / math.log2(i + 2)  # +2 because rank starts at 1
        
        # Ideal DCG: expected at position 1
        if expected:
            idcg = 1.0 / math.log2(2)  # = 1.0
        
        ndcg = dcg / idcg if idcg > 0 else 0.0
        ndcg_scores.append(ndcg)
    
    return sum(ndcg_scores) / len(ndcg_scores)


def compute_routing_accuracy(predictions: list[tuple[str, str]]) -> float:
    """Compute routing classification accuracy.
    
    Args:
        predictions: List of (predicted_route, expected_route) tuples
    
    Returns:
        Accuracy (0.0 to 1.0)
    """
    if not predictions:
        return 1.0
    
    correct = sum(1 for pred, expected in predictions if pred == expected)
    return correct / len(predictions)


def compute_confusion_matrix(predictions: list[tuple[str, str]]) -> dict[str, dict[str, int]]:
    """Compute confusion matrix for routing classification.
    
    Args:
        predictions: List of (predicted_route, expected_route) tuples
    
    Returns:
        Dict of {actual: {predicted: count}}
    """
    routes = {"SQL", "VECTOR", "HYBRID"}
    matrix = {actual: {predicted: 0 for predicted in routes} for actual in routes}
    
    for pred, expected in predictions:
        if expected in matrix and pred in matrix[expected]:
            matrix[expected][pred] += 1
    
    return matrix


# --- Dataset builders -------------------------------------------------------

def build_evaluation_report(
    routing_results: list[tuple[str, str]] | None = None,
    retrieval_results: list[dict] | None = None,
    metadata_results: list[dict] | None = None,
    citation_results: list[dict] | None = None,
) -> dict[str, Any]:
    """Build a comprehensive evaluation report.
    
    Args:
        routing_results: List of (predicted, expected) route tuples
        retrieval_results: List of {question, expected_chunk_id, retrieved_chunk_ids}
        metadata_results: List of {question, expected_answer, actual_answer, correct}
        citation_results: List of {question, claims_verified, total_claims}
    
    Returns:
        Evaluation report dict with all metrics
    """
    report = {
        "summary": {},
        "routing": {},
        "retrieval": {},
        "metadata": {},
        "citation": {},
    }
    
    # Routing metrics
    if routing_results:
        accuracy = compute_routing_accuracy(routing_results)
        report["routing"] = {
            "accuracy": accuracy,
            "total": len(routing_results),
            "correct": sum(1 for p, e in routing_results if p == e),
            "confusion_matrix": compute_confusion_matrix(routing_results),
        }
        report["summary"]["routing_accuracy"] = accuracy
    
    # Retrieval metrics
    if retrieval_results:
        recall = compute_recall_at_k(retrieval_results, k=100)
        mrr = compute_mrr(retrieval_results)
        ndcg = compute_ndcg_at_k(retrieval_results, k=10)
        report["retrieval"] = {
            "recall@100": recall,
            "mrr": mrr,
            "ndcg@10": ndcg,
            "total": len(retrieval_results),
        }
        report["summary"]["retrieval_recall"] = recall
        report["summary"]["retrieval_mrr"] = mrr
        report["summary"]["retrieval_ndcg"] = ndcg
    
    # Metadata metrics
    if metadata_results:
        correct = sum(1 for r in metadata_results if r.get("correct", False))
        report["metadata"] = {
            "accuracy": correct / len(metadata_results) if metadata_results else 1.0,
            "total": len(metadata_results),
            "correct": correct,
        }
        report["summary"]["metadata_accuracy"] = report["metadata"]["accuracy"]
    
    # Citation metrics
    if citation_results:
        avg_verified = sum(
            r.get("claims_verified", 0) / max(1, r.get("total_claims", 1))
            for r in citation_results
        ) / len(citation_results)
        report["citation"] = {
            "avg_claims_verified": avg_verified,
            "total": len(citation_results),
        }
        report["summary"]["citation_verified_ratio"] = avg_verified
    
    return report


__all__ = [
    "load_golden_set",
    "load_routing_dataset",
    "load_metadata_dataset",
    "load_citation_dataset",
    "get_dataset_summary",
    "compute_recall_at_k",
    "compute_mrr",
    "compute_ndcg_at_k",
    "compute_routing_accuracy",
    "compute_confusion_matrix",
    "build_evaluation_report",
]
