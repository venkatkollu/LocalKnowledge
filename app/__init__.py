"""Local KnowledgeOS. Preserve the original `uvicorn app:app` public entry point."""
def __getattr__(name):
    # Components can be imported for tooling without starting API globals or
    # loading a reranker. uvicorn resolves the FastAPI instance lazily.
    if name not in {"app", "init_db", "scan", "index_file", "SETTINGS", "ROOT", "QueryRequest", "search", "chat"}:
        raise AttributeError(name)
    from importlib import import_module
    return getattr(import_module("app.api"), name)
