#!/usr/bin/env bash
# Local development launcher: Ollama (if installed) + backend + frontend.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PYTHON_BIN="${KNOWLEDGEOS_PYTHON:-python3}"
BACKEND_PORT="${KNOWLEDGEOS_PORT:-8000}"

if [ ! -d frontend/node_modules ]; then
    echo "frontend/node_modules is missing; run: cd frontend && npm install" >&2
    exit 1
fi

OLLAMA_PID=""
BACKEND_PID=""
FRONTEND_PID=""

cleanup() {
    trap - INT TERM EXIT
    for pid in "$FRONTEND_PID" "$BACKEND_PID" "$OLLAMA_PID"; do
        [ -n "$pid" ] && kill "$pid" 2>/dev/null || true
    done
}
trap cleanup INT TERM EXIT

if command -v ollama >/dev/null 2>&1; then
    if ! curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
        echo "Starting Ollama..."
        ollama serve >/dev/null 2>&1 &
        OLLAMA_PID=$!
    fi
else
    echo "Ollama not found; using the configured embedding provider or fallback." >&2
fi

echo "Starting backend on http://127.0.0.1:${BACKEND_PORT} ..."
"$PYTHON_BIN" -m uvicorn backend.main:app \
    --host 127.0.0.1 --port "$BACKEND_PORT" &
BACKEND_PID=$!

echo "Starting frontend on http://127.0.0.1:5173 ..."
(
    cd frontend
    npm run dev -- --host 127.0.0.1
) &
FRONTEND_PID=$!

echo
echo "Backend:  http://127.0.0.1:${BACKEND_PORT}"
echo "Frontend: http://127.0.0.1:5173"
echo "Press Ctrl+C to stop."
echo

wait
