#!/usr/bin/env sh
set -eu
PYTHON_BIN="${KNOWLEDGEOS_PYTHON:-python3}"
# all-minilm is the smallest embedding model and is pulled locally by default.
export KNOWLEDGEOS_OLLAMA_EMBEDDING_MODEL="${KNOWLEDGEOS_OLLAMA_EMBEDDING_MODEL:-all-minilm}"
exec "$PYTHON_BIN" -m uvicorn backend.main:app --host "${KNOWLEDGEOS_HOST:-127.0.0.1}" --port "${KNOWLEDGEOS_PORT:-8000}" --reload
