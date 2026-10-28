#!/usr/bin/env sh
set -eu

MODEL="${KNOWLEDGEOS_OLLAMA_EMBEDDING_MODEL:-all-minilm}"
OLLAMA_HOST="${OLLAMA_HOST:-127.0.0.1:11434}"
API_URL="http://${OLLAMA_HOST}"
LOG_DIR="${KNOWLEDGEOS_DATA_DIR:-data}/ollama"

if ! command -v curl >/dev/null 2>&1; then
  echo "curl is required to install Ollama and download the model." >&2
  exit 1
fi

if ! command -v ollama >/dev/null 2>&1; then
  echo "Installing Ollama with the official installer..."
  curl -fsSL https://ollama.com/install.sh | sh
fi

if ! command -v ollama >/dev/null 2>&1; then
  echo "Ollama installation did not provide an 'ollama' command." >&2
  exit 1
fi

if ! curl -fsS --max-time 2 "${API_URL}/api/tags" >/dev/null 2>&1; then
  mkdir -p "$LOG_DIR"
  echo "Starting Ollama at ${API_URL}..."
  OLLAMA_HOST="$OLLAMA_HOST" nohup ollama serve >"${LOG_DIR}/server.log" 2>&1 </dev/null &
fi

attempt=0
until curl -fsS --max-time 2 "${API_URL}/api/tags" >/dev/null 2>&1; do
  attempt=$((attempt + 1))
  if [ "$attempt" -ge 30 ]; then
    echo "Ollama did not become ready at ${API_URL}. See ${LOG_DIR}/server.log." >&2
    exit 1
  fi
  sleep 1
done

echo "Downloading embedding model ${MODEL}..."
OLLAMA_HOST="$OLLAMA_HOST" ollama pull "$MODEL"
echo "Ready. Backend embedding model: ${MODEL}"
