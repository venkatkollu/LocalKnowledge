from __future__ import annotations



def summarize(app, categories: list[str], expansion=None, hyde=None) -> dict:
    from app.evaluation import load_questions, run_benchmark
    questions = load_questions(app.ROOT, categories)
    headers = {"x-tenant-id": "local", "x-owner-id": "local"}
    def retrieve(question):
        return app.search(app.QueryRequest(query=question, top_k=20, query_expansion=expansion, hyde=hyde), headers)
    def answer(question):
        return app.chat(app.QueryRequest(query=question, top_k=6, query_expansion=expansion, hyde=hyde), headers)
    result = run_benchmark(retrieve, answer, questions)
    result["mode"] = "offline" if app.SETTINGS.generation.provider == "extractive" else "configured-local:" + app.SETTINGS.generation.provider
    from collections import Counter
    result["models_used"] = dict(Counter(case["response"]["model"] for case in result["details"]))
    result["local_model_calls_succeeded"] = sum(
        not case["response"].get("provider_error") and bool(
            case["response"]["model"] not in {"abstention", "local-extractive-v2"}
            or case["response"].get("verification", {}).get("rejected_generation")
        ) for case in result["details"]
    )
    result["categories"] = categories
    return result
