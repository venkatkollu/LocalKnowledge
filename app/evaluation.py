from __future__ import annotations

import json
from pathlib import Path
import time

from app.citations import validate_answer
from eval.metrics import answer_relevance, percentile, retrieval_metrics, current_rss_mb


def load_questions(root: Path, categories: list[str] | None = None) -> list[dict]:
    questions = []
    for category in categories or ["golden"]:
        path = root / "eval" / category / "questions.json"
        questions.extend(json.loads(path.read_text()))
    return questions


def mean(values):
    values = [value for value in values if value is not None]
    return sum(values) / len(values) if values else None


def summarize_cases(cases: list[dict]) -> dict:
    """Shared scorer for original and upgraded runs; no LLM judge dependency."""
    retrieval, generated, answerable, abstention = [], [], [], []
    stage_times = {name: [] for name in ("retrieval_ms", "reranking_ms", "generation_ms")}
    for case in cases:
        expected = case.get("expected_sources", [case["expected_source"]] if case.get("expected_source") else [])
        metric = retrieval_metrics(case["results"], expected)
        case["metrics"] = metric
        if metric:
            retrieval.append(metric)
        response = case["response"]
        stopped = response.get("abstained", response.get("model") == "abstention")
        expected_abstention = bool(case.get("unanswerable", False))
        abstention.append(stopped == expected_abstention)
        relevance = answer_relevance(response["answer"], case.get("answer_terms", []))
        if not expected_abstention:
            answerable.append(relevance)
        if not stopped:
            # Independently score the returned text against its cited evidence.
            # This lexical proxy cannot establish semantic entailment.
            citations = response.get("citations", [])
            by_id = {item["id"]: item for item in case["results"]}
            count = max([citation["index"] for citation in citations] or [0])
            evidence = [{} for _ in range(count)]
            for citation in citations:
                source = by_id.get(citation["chunk_id"], {})
                evidence[citation["index"] - 1] = {"raw_content": citation.get("excerpt", source.get("content", ""))}
            check = validate_answer(response["answer"], evidence)
            if not check["references"] and check["claim_count"]:
                check["citation_precision"] = 0.0
            generated.append(check)
        case["generation_metrics"] = {"answer_relevance": relevance, "abstention_correct": stopped == expected_abstention}
        for name in stage_times:
            if name in response.get("stats", {}):
                stage_times[name].append(response["stats"][name])
    output = {key: mean([item[key] for item in retrieval]) for key in
              ("recall_at_5", "recall_at_10", "recall_at_20", "mrr", "ndcg_at_10", "precision_at_5", "precision_at_10", "precision_at_20")}
    for key in ("citation_precision", "citation_recall", "coverage", "unsupported_claim_rate", "faithfulness_proxy"):
        output[key] = mean([item.get(key) for item in generated])
    output.update(answer_relevance=mean(answerable), context_relevance_proxy=output["precision_at_5"],
                  faithfulness=None, faithfulness_note="Semantic entailment/human labels unavailable; lexical faithfulness_proxy is reported separately",
                  citation_accuracy=output["citation_precision"], abstention_accuracy=mean(abstention),
                  questions=len(cases), retrieval_questions=len(retrieval), answered_questions=len(generated),
                  abstention_true_positives=sum(case["response"].get("abstained", case["response"].get("model") == "abstention") for case in cases if case.get("unanswerable")),
                  unanswerable_questions=sum(bool(case.get("unanswerable")) for case in cases),
                  details=cases)
    latencies = [case["latency_ms"] for case in cases]
    output["latency_ms"] = {f"p{int(p * 100)}": percentile(latencies, p) for p in (.50, .95, .99)}
    output["stage_latency_ms"] = {key: {"p50": percentile(values, .5), "p95": percentile(values, .95)} for key, values in stage_times.items()}
    token_counts = [sum(case["response"].get("stats", {}).get("usage", {}).values()) for case in cases]
    output["tokens_per_request"] = mean(token_counts) if token_counts else None
    output["token_note"] = "Provider counts only; hash embeddings and extractive generation consume no LLM tokens"
    return output


def run_benchmark(search, chat, questions: list[dict]) -> dict:
    cases = []
    for question in questions:
        if not isinstance(question.get("question"), str):
            raise ValueError("Every evaluation case needs a question string")
        search_result = search(question["question"])
        started = time.perf_counter()
        response = chat(question["question"])
        cases.append({**question, "response": response, "results": search_result["results"],
                      "latency_ms": (time.perf_counter() - started) * 1000, "rss_mb": current_rss_mb()})
    return summarize_cases(cases)
