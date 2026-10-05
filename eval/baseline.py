"""Run the original implementation without mutating the checkout or user data."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import shutil
import tempfile
import time

from eval.metrics import retrieval_metrics


def run(output: Path, commit: str = "360d5de", repeats: int = 1) -> dict:
    root = Path(__file__).resolve().parents[1]
    source = subprocess.check_output(["git", "show", f"{commit}:app.py"], cwd=root, text=True)
    questions = []
    for category in ("golden", "regression", "unanswerable", "injection", "adversarial"):
        questions.extend(json.loads((root / "eval" / category / "questions.json").read_text()))
    with tempfile.TemporaryDirectory(prefix="baseline-", dir=os.getenv("KNOWLEDGEOS_TMP")) as tmp:
        module_path = Path(tmp) / "original.py"
        # StaticFiles requires the original static directory at module load.
        module_path.write_text(source.replace('ROOT = Path(__file__).parent.resolve()', f'ROOT = Path({str(root)!r})'))
        corpus = Path(tmp) / "knowledge"
        shutil.copytree(root / "eval" / "corpus", corpus, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".git"))
        os.environ.update(KNOWLEDGEOS_DATA=tmp, KNOWLEDGEOS_DB=str(Path(tmp) / "baseline.db"),
                          KNOWLEDGEOS_KNOWLEDGE=str(corpus), KNOWLEDGEOS_AUTO_SYNC="0")
        spec = importlib.util.spec_from_file_location("baseline_original", module_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.embed_texts = lambda texts: ([module.hash_embedding(t) for t in texts], "local-hash-fallback")
        def offline(*args, **kwargs):
            raise RuntimeError("explicit offline baseline")
        module.httpx.post = offline
        module.init_db()
        ingestion = module.scan()
        rows = []
        for question in questions * repeats:
            results, stats = module.hybrid(question["question"], 20)
            started = time.perf_counter()
            response = module.chat(module.ChatRequest(query=question["question"], top_k=12))
            rows.append({**question, "results": results, "response": response,
                         "metrics": retrieval_metrics(results, question["expected_sources"]),
                         "latency_ms": (time.perf_counter() - started) * 1000})
        result = {"mode": "original-offline", "commit": commit, "ingestion": ingestion, "details": rows}
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2))
        module.executor.shutdown(wait=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("eval/reports/baseline.json"))
    parser.add_argument("--commit", default="360d5de")
    parser.add_argument("--repeats", type=int, default=1)
    args = parser.parse_args()
    result = run(args.output, args.commit, args.repeats)
    print(f"Saved {len(result['details'])} original implementation measurements to {args.output}")
