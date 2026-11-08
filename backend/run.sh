#!/usr/bin/env sh
set -eu
PYTHON_BIN="${KNOWLEDGEOS_PYTHON:-python3}"
# nomic-embed-text is the default local embedding model.
export KNOWLEDGEOS_OLLAMA_EMBEDDING_MODEL="${KNOWLEDGEOS_OLLAMA_EMBEDDING_MODEL:-nomic-embed-text}"
exec "$PYTHON_BIN" -m uvicorn backend.main:app --host "${KNOWLEDGEOS_HOST:-127.0.0.1}" --port "${KNOWLEDGEOS_PORT:-8000}" --reload
