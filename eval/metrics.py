from __future__ import annotations

import math
import re
import os
from pathlib import Path
from typing import Iterable


def unique_sources(results: list[dict]) -> list[str]:
    return list(dict.fromkeys(item["filename"] for item in results))


def retrieval_metrics(results: list[dict], expected: Iterable[str]) -> dict:
    """Document-level metrics: exact IDs, deduplicated ranking, full MRR."""
    expected = set(expected)
    ranking = unique_sources(results)
    if not expected:
        return {}
    output = {}
    for k in (5, 10, 20):
        hits = len(set(ranking[:k]) & expected)
        output[f"recall_at_{k}"] = hits / len(expected)
        output[f"precision_at_{k}"] = hits / k
    output["mrr"] = next((1 / i for i, source in enumerate(ranking, 1) if source in expected), 0.0)
    dcg = sum(1 / math.log2(i + 1) for i, source in enumerate(ranking[:10], 1) if source in expected)
    ideal = sum(1 / math.log2(i + 1) for i in range(1, min(10, len(expected)) + 1))
    output["ndcg_at_10"] = dcg / ideal
    return output


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * p
    lo, hi = math.floor(position), math.ceil(position)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (position - lo)


def answer_relevance(answer: str, terms: list[str]) -> float | None:
    if not terms:
        return None
    tokens = set(re.findall(r"\w+", answer.lower()))
    return sum(set(re.findall(r"\w+", term.lower())) <= tokens for term in terms) / len(terms)


def current_rss_mb():
    path = Path("/proc/self/statm")
    return int(path.read_text().split()[1]) * os.sysconf("SC_PAGE_SIZE") / (1024 * 1024) if path.exists() else None
