"""Deterministic claim verification against retrieved evidence.

Verification runs after generation, so it must not add model downloads or
inference to the answer path. Content-word overlap with the best citation is
fast, deterministic, and enough to flag sentences the evidence does not
support. A cross-encoder was previously optional here; it changed only the
post-hoc flags, never retrieval or the answer prompt, and cost seconds of
model loading plus a large optional dependency.
"""

from __future__ import annotations

import re
from typing import Any

from .config import NLI_ENABLED, NLI_MAX_CLAIMS, NLI_THRESHOLD

_STOPWORDS = {
    "the", "a", "an", "and", "or", "for", "with", "from", "that", "this", "is",
    "are", "was", "were", "to", "of", "in", "on", "by", "as", "at", "be", "it",
    "its", "which", "who", "has", "have", "had", "will", "can", "not",
}


def _split_claims(answer: str) -> list[str]:
    cleaned = re.sub(r"\[[^\]\n]{1,240}:\d+-\d+\]", " ", answer)
    cleaned = re.sub(r"\s+", " ", cleaned.strip())
    parts = re.split(r"(?<=[.!?])\s+|;\s+", cleaned)
    claims = [part.strip() for part in parts if len(part.strip()) >= 8]
    return claims[:NLI_MAX_CLAIMS] or ([cleaned] if cleaned else [])


def _lexical_entailment(premise: str, hypothesis: str) -> float:
    """Share of the claim's content words that appear in the evidence."""

    def content(text: str) -> set[str]:
        return {
            word
            for word in re.findall(r"[A-Za-z0-9_]{2,}", text.lower())
            if word not in _STOPWORDS
        }

    premise_words, hypothesis_words = content(premise), content(hypothesis)
    return (
        len(premise_words & hypothesis_words) / len(hypothesis_words)
        if hypothesis_words
        else 0.0
    )


def _claim_candidates(answer: str) -> list[tuple[str, list[int]]]:
    """Split an answer into display sentences plus the citation ordinals used.

    Markdown decoration and heading lines are removed so the UI can render the
    claim text with its own citation chips.
    """
    cleaned = re.sub(r"(?m)^\s*#{1,6}\s*[^\n]*$", " ", answer)
    cleaned = re.sub(r"[*_`>#]+", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    candidates: list[tuple[str, list[int]]] = []
    for part in re.split(r"(?<=[.!?])\s+", cleaned):
        identifiers = [int(value) for value in re.findall(r"\[(\d{1,3})\]", part)]
        text = re.sub(r"\[\d{1,3}\]", "", part).strip(" -")
        if text:
            candidates.append((text, identifiers))
    return candidates


def verify_claims(answer: str, citations: list[dict[str, Any]]) -> dict[str, Any]:
    """Split an answer into claims and score each against its best citation."""
    if not NLI_ENABLED or not citations:
        return {
            "enabled": NLI_ENABLED,
            "claims": [],
            "verified_ratio": None,
            "decision": "skipped",
        }
    claims = _split_claims(answer)
    if not claims:
        return {
            "enabled": True,
            "claims": [],
            "verified_ratio": None,
            "decision": "empty",
        }

    results: list[dict[str, Any]] = []
    verified = 0
    for claim in claims:
        best_score, best_chunk = 0.0, None
        for citation in citations:
            score = _lexical_entailment(citation.get("excerpt") or "", claim)
            if score > best_score:
                best_score, best_chunk = score, citation.get("chunk_id")
        supported = best_score >= NLI_THRESHOLD
        verified += int(supported)
        results.append(
            {
                "claim": claim,
                "entailment": round(best_score, 4),
                "supported": supported,
                "citation_chunk_id": best_chunk,
            }
        )

    ratio = verified / len(claims)
    decision = (
        "verified"
        if ratio >= 0.75
        else "partial"
        if ratio >= 0.4
        else "unsupported"
    )
    return {
        "enabled": True,
        "model": "lexical",
        "claims": results,
        "verified_ratio": round(ratio, 4),
        "decision": decision,
    }
