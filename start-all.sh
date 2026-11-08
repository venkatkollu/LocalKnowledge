#!/usr/bin/env bash
# Comprehensive local launcher with dependency checks and readiness polling.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

BACKEND_PORT="${KNOWLEDGEOS_PORT:-8000}"
FRONTEND_PORT=5173
OLLAMA_PID=""
BACKEND_PID=""
FRONTEND_PID=""

cleanup() {
    trap - INT TERM EXIT
    echo -e "\n${YELLOW}Stopping services...${NC}"
    for pid in "$FRONTEND_PID" "$BACKEND_PID" "$OLLAMA_PID"; do
        [ -n "$pid" ] && kill "$pid" 2>/dev/null || true
    done
    echo -e "${GREEN}All services stopped${NC}"
}

wait_for() {
    local url="$1" label="$2" attempts="${3:-30}"
    for _ in $(seq 1 "$attempts"); do
        if curl -fsS "$url" >/dev/null 2>&1; then
            echo -e "${GREEN}${label} is ready${NC}"
            return 0
        fi
        sleep 1
    done
    echo -e "${RED}${label} did not become ready at ${url}${NC}"
    return 1
}

check_dependencies() {
    echo -e "${YELLOW}Checking dependencies...${NC}"
    for command in python3 node npm; do
        if ! command -v "$command" >/dev/null 2>&1; then
            echo -e "${RED}$command not found${NC}"
            exit 1
        fi
        echo -e "${GREEN}$command found${NC}"
    done
    if [ ! -f backend/requirements.txt ]; then
        echo -e "${RED}backend/requirements.txt not found${NC}"
        exit 1
    fi
    if [ ! -d frontend/node_modules ]; then
        echo -e "${YELLOW}Installing frontend dependencies...${NC}"
        (cd frontend && npm install)
    fi
}

start_ollama() {
    if ! command -v ollama >/dev/null 2>&1; then
        echo -e "${YELLOW}Ollama not installed; skipping local embeddings${NC}"
        return
    fi
    if curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
        echo -e "${GREEN}Ollama already running${NC}"
        return
    fi
    echo -e "${YELLOW}Starting Ollama...${NC}"
    ollama serve >/dev/null 2>&1 &
    OLLAMA_PID=$!
    if wait_for http://127.0.0.1:11434/api/tags "Ollama" 30; then
        timeout 120 ollama pull "${KNOWLEDGEOS_OLLAMA_EMBEDDING_MODEL:-nomic-embed-text}" \
            || echo -e "${YELLOW}Embedding model pull skipped${NC}"
    fi
}

start_backend() {
    echo -e "${YELLOW}Starting backend...${NC}"
    export KNOWLEDGEOS_DATA_DIR="${KNOWLEDGEOS_DATA_DIR:-${ROOT}/data}"
    export KNOWLEDGEOS_OLLAMA_BASE_URL="${KNOWLEDGEOS_OLLAMA_BASE_URL:-http://127.0.0.1:11434}"
    export KNOWLEDGEOS_OLLAMA_EMBEDDING_MODEL="${KNOWLEDGEOS_OLLAMA_EMBEDDING_MODEL:-nomic-embed-text}"
    export KNOWLEDGEOS_CORS_ORIGINS="${KNOWLEDGEOS_CORS_ORIGINS:-http://localhost:${FRONTEND_PORT},http://127.0.0.1:${FRONTEND_PORT}}"
    python3 -m uvicorn backend.main:app --host 127.0.0.1 --port "$BACKEND_PORT" &
    BACKEND_PID=$!
    wait_for "http://127.0.0.1:${BACKEND_PORT}/api/health" "Backend" 30
}

start_frontend() {
    echo -e "${YELLOW}Starting frontend...${NC}"
    (cd frontend && npm run dev -- --host 127.0.0.1) &
    FRONTEND_PID=$!
    wait_for "http://127.0.0.1:${FRONTEND_PORT}" "Frontend" 30
}

trap cleanup INT TERM EXIT

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  Local KnowledgeOS - Easy Start${NC}"
echo -e "${BLUE}========================================${NC}"

check_dependencies
start_ollama
start_backend
start_frontend

echo
echo -e "${GREEN}Backend:  http://127.0.0.1:${BACKEND_PORT}${NC}"
echo -e "${GREEN}Frontend: http://127.0.0.1:${FRONTEND_PORT}${NC}"
echo -e "${YELLOW}Press Ctrl+C to stop all services${NC}"

wait
