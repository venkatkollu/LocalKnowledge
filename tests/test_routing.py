"""Tests for Layer 1 query classification and routing.

Run with: python3 -m pytest tests/test_routing.py -v
"""
from __future__ import annotations

import json
from pathlib import Path

GOLDEN_SET_PATH = Path(__file__).resolve().parent / "data" / "routing_set.jsonl"


def test_sql_route_exact_id_lookups():
    from backend.routing import classify_tier1
    
    tests = [
        ("alpha-1234", "SQL"),
        ("DOC-5678", "SQL"),
        ("Which file is ABC-9999?", "SQL"),
        ("ID: xyz-9999", "SQL"),
    ]
    for q, label in tests:
        d = classify_tier1(q)
        assert d.route == label, f"Expected SQL for {q!r}, got {d.route}"


def test_vector_route_narrative_questions():
    from backend.routing import classify_tier1
    
    tests = [
        "What does the policy say about refunds?",
        "Explain the chunking strategy.",
        "Why was the model fine-tuned?",
        "How does the retrieval work?",
        "Summarize the results.",
    ]
    for t in tests:
        d = classify_tier1(t)
        assert d.route == "VECTOR", f"Expected VECTOR for {t!r}, got {d.route}"


def test_content_questions_with_aggregate_wording_stay_vector():
    """Generic words like "many" or "rank" are not catalog subjects.

    Treating them as one sent content questions to the metadata branch, which
    answered with the document count instead of retrieved evidence.
    """
    from backend.routing import classify_tier1

    tests = [
        "What three activation types does IA3 rescale with learned vectors, and "
        "how many new parameters does it introduce relative to the base model?",
        "Rank the methods by the fraction of trainable parameters they report.",
        "How many parameters does LoRA introduce?",
        "How many bias terms does BERT have?",
    ]
    for question in tests:
        d = classify_tier1(question)
        assert d.route == "VECTOR", f"Expected VECTOR for {question!r}, got {d.route}"


def test_hybrid_route_combined_questions():
    from backend.routing import classify_tier1
    
    tests = [
        "Which document discusses compliance and what does it say?",
        "Which source contains table analysis and what does it say?",
    ]
    for t in tests:
        d = classify_tier1(t)
        assert d.route == "HYBRID", f"Expected HYBRID for {t!r}, got {d.route}"


def test_golden_routing_accuracy():
    if not GOLDEN_SET_PATH.exists():
        return
    with open(GOLDEN_SET_PATH) as f:
        items = [json.loads(l) for l in f if l.strip()]

    from backend.routing import classify_tier1
    correct = 0
    false_sql = 0
    for item in items:
        d = classify_tier1(item["question"])
        if d.route == item["label"]:
            correct += 1
        elif d.route == "SQL":
            false_sql += 1

    accuracy = correct / len(items) if items else 1.0
    assert accuracy >= 0.95, f"Accuracy {accuracy:.2%} < 95%"
    assert false_sql <= int(len(items) * 0.02), f"False-SQL rate {false_sql}/{len(items)} exceeds 2%"