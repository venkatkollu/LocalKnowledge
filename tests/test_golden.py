from pathlib import Path

from app.citations import validate_answer
from app.config import Settings
from app.embeddings import HashEmbedding
from app.evaluation import load_questions, run_benchmark
from app.evidence import AnswerPipeline
from app.generation import LocalGenerator
from app.ingestion import Ingestor
from app.observability import Trace
from app.retrieval import QueryPipeline
from app.security import Principal
from app.storage import SQLiteStorage


def test_golden_qa_and_unanswerable_regression(tmp_path):
    root = Path(__file__).resolve().parents[1]
    cfg = Settings(data_dir=tmp_path, db_path=tmp_path / "eval.db", knowledge_dir=root / "eval" / "corpus", auto_sync=False,
                   embeddings={"provider": "hash"}, generation={"provider": "extractive"})
    storage = SQLiteStorage(cfg)
    storage.initialize()
    index = storage.create_index("golden")
    Ingestor(cfg, storage).scan(index)
    generator = LocalGenerator(cfg)
    retrieval = QueryPipeline(cfg, storage, generator)
    answers = AnswerPipeline(cfg, generator)
    def search(question):
        evidence, stats = retrieval.retrieve(question, Principal(), 20, {}, Trace(), index)
        return {"results": evidence, "stats": stats}
    def answer(question):
        trace = Trace()
        evidence, stats = retrieval.retrieve(question, Principal(), 6, {}, trace, index)
        context = retrieval.context(question, evidence, Principal(), index, trace)
        result = answers.answer(question, context, trace)
        from app.citations import citation_records
        result["citations"] = citation_records(context, result.get("verification", {}).get("references", [])) if not result["abstained"] else []
        result["stats"] = stats
        return result
    report = run_benchmark(search, answer, load_questions(root, ["golden", "regression", "unanswerable", "injection", "adversarial"]))
    assert report["recall_at_5"] == 1
    assert report["answer_relevance"] == 1
    assert report["abstention_accuracy"] == 1
    assert report["citation_accuracy"] == 1
    assert report["faithfulness"] is None
