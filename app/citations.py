from __future__ import annotations

import re

from app.reranking import query_terms

CITATION_RE = re.compile(r"\[(\d+)\]")
BOILERPLATE = {"based", "indexed", "evidence", "available", "limited", "according", "answer", "supported"}


def claims(answer: str) -> list[str]:
    # Normalize citations placed after punctuation back into their sentence.
    answer = re.sub(r"([.!?])\s*((?:\[\d+\]\s*)+)", lambda match: " " + match[2].strip() + match[1] + " ", answer)
    return [text.strip() for text in re.split(r"(?<=[.!?])\s+|\n+", answer) if query_terms(CITATION_RE.sub("", text)) - BOILERPLATE]


def supported(claim: str, source: str, threshold: float = 0.8) -> tuple[bool, float]:
    terms = query_terms(CITATION_RE.sub("", claim)) - BOILERPLATE
    source_terms = query_terms(source)
    overlap = len(terms & source_terms) / max(1, len(terms))
    numbers = set(re.findall(r"\b\d+(?:\.\d+)?\b", CITATION_RE.sub("", claim)))
    missing_numbers = numbers - set(re.findall(r"\b\d+(?:\.\d+)?\b", source))
    negation = bool(terms & {"not", "never", "no", "cannot"}) != bool(source_terms & {"not", "never", "no", "cannot"})
    return overlap >= threshold and not missing_numbers and not negation, overlap


def validate_answer(answer: str, evidence: list[dict], threshold: float = 0.8) -> dict:
    all_claims = claims(answer)
    references = [int(value) for value in CITATION_RE.findall(answer)]
    invalid = [number for number in references if not 1 <= number <= len(evidence)]
    checked, unsupported, supported_citations, cited_claims = [], [], 0, 0
    for claim in all_claims:
        refs = [int(value) for value in CITATION_RE.findall(claim)]
        details, supports = [], []
        if refs:
            cited_claims += 1
        for number in refs:
            if not 1 <= number <= len(evidence):
                details.append({"citation": number, "supported": False, "reason": "incorrect_citation"})
                supports.append(False)
                continue
            item = evidence[number - 1]
            # Validate against exactly what the generator was given, never
            # contextual descriptions (which may be LLM generated).
            text = item.get("context_content", item.get("raw_content", item.get("content", "")))
            valid, overlap = supported(claim, text, threshold)
            supported_citations += int(valid)
            supports.append(valid)
            details.append({"citation": number, "supported": valid, "lexical_support": overlap})
        valid_claim = bool(supports) and all(supports)
        row = {"claim": claim, "supported": valid_claim, "citations": details,
               "reason": "supported" if valid_claim else "missing_citation" if not refs else "unsupported_or_weak_evidence"}
        checked.append(row)
        if not valid_claim:
            unsupported.append(row)
    count = len(all_claims)
    return {"method": "conservative-lexical-numeric-negation; not semantic entailment",
            "claim_count": count, "claims": checked, "unsupported_claims": unsupported, "incorrect_citations": invalid,
            "citation_precision": supported_citations / len(references) if references else None,
            "citation_recall": sum(row["supported"] for row in checked) / count if count else None,
            "coverage": cited_claims / count if count else None,
            "faithfulness_proxy": (count - len(unsupported)) / count if count else None,
            "unsupported_claim_rate": len(unsupported) / count if count else None,
            "valid": bool(count) and not unsupported and not invalid,
            "references": references}


def citation_records(evidence: list[dict], references: list[int] | None = None) -> list[dict]:
    result = []
    for index, item in enumerate(evidence, 1):
        if references is not None and index not in references:
            continue
        meta = item.get("context_metadata", item.get("metadata", {}))
        result.append({"index": index, "filename": item["filename"], "path": item["path"], "section": meta.get("section", "Document"),
                       "subsection": meta.get("subsection"), "page": meta.get("page"), "start_line": meta.get("start_line"), "end_line": meta.get("end_line"),
                       "symbol": meta.get("symbol"), "version": item["version"], "chunk_id": item["id"], "parent_id": item.get("parent_id"),
                       "excerpt": item.get("context_content", item["raw_content"])[:500]})
    return result
