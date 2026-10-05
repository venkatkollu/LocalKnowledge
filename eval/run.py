"""Run the checked-in local regression benchmark.

Usage: ``python -m eval.run``. The command uses the configured local models;
set KNOWLEDGEOS_OFFLINE=1 for a deterministic no-server smoke benchmark.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import tempfile
import resource
import time
import platform

from eval.e2e import summarize
from eval.metrics import current_rss_mb


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark Local KnowledgeOS against checked-in QA sets")
    parser.add_argument("--categories", nargs="+", default=["golden", "regression", "unanswerable", "injection", "adversarial"])
    parser.add_argument("--output", type=Path, default=Path("eval/reports/after.json"))
    parser.add_argument("--corpus", type=Path, default=Path("eval/corpus"))
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--variants", action="store_true", help="Compare baseline, expansion, HyDE, and both (requires a local generator)")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--fail-on-regression", action="store_true")
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be positive")

    # Import only after offline environment choices are visible to app.Settings.
    os.environ.setdefault("KNOWLEDGEOS_AUTO_SYNC", "0")
    with tempfile.TemporaryDirectory(prefix="knowledgeos-eval-", dir=os.getenv("KNOWLEDGEOS_TMP")) as temp:
        os.environ.update(KNOWLEDGEOS_DATA=temp, KNOWLEDGEOS_DB=str(Path(temp) / "eval.db"), KNOWLEDGEOS_KNOWLEDGE=str(Path(temp) / "knowledge"))
        knowledge = Path(temp) / "knowledge"
        shutil.copytree(args.corpus, knowledge, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".git"))
        import app
        app.init_db()
        started, cpu = time.perf_counter(), time.process_time()
        ingestion = app.scan()
        ingestion_wall = (time.perf_counter() - started) * 1000
        result = summarize(app, args.categories)
        for repeat in range(1, args.repeats):
            another = summarize(app, args.categories)
            result["details"].extend(another["details"])
            for model, count in another["models_used"].items():
                result["models_used"][model] = result["models_used"].get(model, 0) + count
            result["local_model_calls_succeeded"] += another["local_model_calls_succeeded"]
        if args.repeats > 1:
            from app.evaluation import summarize_cases
            result = {**result, **summarize_cases(result["details"])}
        rss_samples = [case["rss_mb"] for case in result["details"] if case.get("rss_mb") is not None]
        result["resources"] = {"os_reported_high_water_rss_mb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024 if platform.system() == "Darwin" else 1024),
                               "sampled_peak_rss_mb": max(rss_samples) if rss_samples else None,
                               "current_process_rss_mb": current_rss_mb(),
                               "process_cpu_seconds": time.process_time() - cpu,
                               "sqlite_bytes": app.SETTINGS.db_path.stat().st_size,
                               "corpus_bytes": sum(path.stat().st_size for path in knowledge.rglob("*") if path.is_file()),
                               "ingestion_ms": ingestion_wall, "gpu": "not measured; offline benchmark uses CPU"}
        result["environment"] = {"python": platform.python_version(), "platform": platform.platform(), "logical_cpus": os.cpu_count(),
                                 "repeats": args.repeats, "unique_cases": result["questions"] // args.repeats,
                                 "corpus_hash": app.api.sha256(b"".join(path.name.encode() + path.read_bytes() for path in sorted(knowledge.rglob("*")) if path.is_file()))}
        result["ingestion_summary"] = ingestion["summary"]
        if args.variants:
            if app.SETTINGS.generation.provider == "extractive" or not result["local_model_calls_succeeded"]:
                result["variants"] = {"status": "unmeasured", "reason": "Expansion and HyDE need a working local generator; none was used successfully in this run"}
            else:
                result["variants"] = {}
                for label, expansion, hyde in (("baseline", False, False), ("expansion", True, False), ("hyde", False, True), ("both", True, True)):
                    variant = summarize(app, args.categories, expansion, hyde)
                    result["variants"][label] = {key: value for key, value in variant.items() if key != "details"}
        if args.baseline:
            from app.evaluation import summarize_cases
            before = summarize_cases(json.loads(args.baseline.read_text())["details"])
            result["comparison"] = {key: {"before": before[key], "after": result[key]} for key in
                                    ("recall_at_5", "recall_at_10", "mrr", "ndcg_at_10", "answer_relevance", "citation_accuracy", "abstention_accuracy", "latency_ms")}
            warnings = []
            if result["latency_ms"]["p95"] > before["latency_ms"]["p95"] * 1.5:
                warnings.append("p95 latency increased by more than 50%")
            if result["answer_relevance"] < before["answer_relevance"]:
                warnings.append("Answer relevance regressed")
            for metric in ("recall_at_5", "recall_at_10", "mrr", "ndcg_at_10", "citation_accuracy", "abstention_accuracy"):
                if before[metric] is not None and result[metric] is not None and result[metric] < before[metric] - .01:
                    warnings.append(f"{metric} declined by more than one percentage point")
            result["regression_warnings"] = warnings
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2))
    print(json.dumps({key: value for key, value in result.items() if key not in {"details", "generation_details"}}, indent=2))
    print(f"Saved detailed report to {args.output}")
    return 1 if args.fail_on_regression and result.get("regression_warnings") else 0


if __name__ == "__main__":
    raise SystemExit(main())
