from __future__ import annotations

from app.embeddings import tokenize

STOP_WORDS = set("a an the what which who how does do is are was were for to of in on and or can it use uses used".split())


def query_terms(query: str) -> set[str]:
    return set(tokenize(query)) - STOP_WORDS


class HeuristicReranker:
    """Dependency-free baseline. Scores are signals, not calibrated probabilities."""
    model = "cross-signal-v2"

    def rerank(self, query: str, documents: list[dict], limit: int) -> list[dict]:
        terms = query_terms(query)
        output = []
        for document in documents:
            words = set(tokenize(document["raw_content"]))
            overlap = len(terms & words) / max(1, len(terms))
            semantic = max(0, document.get("vector_score", 0))
            symbol = document.get("metadata", {}).get("symbol", "")
            bonus = 0.15 if symbol and symbol.lower() in query.lower() else 0
            output.append({**document, "lexical_coverage": overlap,
                           "rerank_score": 0.60 * overlap + 0.35 * semantic + bonus})
        return sorted(output, key=lambda item: (-item["rerank_score"], -item["rrf_score"], item["id"]))[:limit]


class CrossEncoderReranker:
    def __init__(self, config):
        if not config.model_path:
            raise ValueError("cross_encoder requires model_path with pre-downloaded local weights")
        from sentence_transformers import CrossEncoder
        self.encoder = CrossEncoder(config.model_path, device=config.device, local_files_only=True)
        self.model = config.model

    def rerank(self, query: str, documents: list[dict], limit: int) -> list[dict]:
        if not documents:
            return []
        scores = self.encoder.predict([(query, item["contextual_content"]) for item in documents])
        coverage = HeuristicReranker().rerank(query, documents, len(documents))
        values = {item["id"]: item["lexical_coverage"] for item in coverage}
        output = [{**item, "rerank_score": float(score), "lexical_coverage": values[item["id"]]}
                  for item, score in zip(documents, scores)]
        return sorted(output, key=lambda item: item["rerank_score"], reverse=True)[:limit]


def make_reranker(config):
    return HeuristicReranker() if config.provider == "heuristic" else CrossEncoderReranker(config)
