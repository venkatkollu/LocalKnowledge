# How to run Local KnowledgeOS — production-local profile

This profile is optimized for an Intel i5 11th Gen laptop with 24 GB RAM and a 2 GB MX450. Run inference on CPU/RAM. Do not make the MX450 a hard dependency.

## 1. Install

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Windows PowerShell activation is `.venv\\Scripts\\Activate.ps1`.

## 2. Prepare your corpus

Put private files under:

```text
data/knowledge/
```

Supported extensions include Markdown, text, code, JSON, YAML, CSV, HTML, CSS, SQL, and text-based PDFs. The application only indexes this explicitly configured directory.

## 3. Install local models (recommended)

Install [Ollama](https://ollama.com), then run:

```bash
ollama pull qwen3:4b
ollama pull nomic-embed-text
ollama serve
```

`qwen3:4b` is the default generation model. Use the larger model only when latency is acceptable:

```bash
ollama pull qwen3:8b
export OLLAMA_MODEL=qwen3:8b
```

The application still starts if Ollama is absent. It uses deterministic local hash embeddings and an extractive fallback response, which makes testing and offline operation possible.

## 4. Start the server

Development mode:

```bash
source .venv/bin/activate
uvicorn app:app --host 127.0.0.1 --port 8000 --reload
```

Production-like single-user mode:

```bash
uvicorn app:app --host 127.0.0.1 --port 8000
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000).

Startup indexing is asynchronous. The UI can be opened immediately while the corpus is being processed.

## 5. Monitor ingestion

Check health:

```bash
curl http://127.0.0.1:8000/health
```

Queue a sync:

```bash
curl -X POST http://127.0.0.1:8000/documents/sync
```

The response contains a `job_id`. Check progress:

```bash
curl http://127.0.0.1:8000/jobs/JOB_ID_HERE
```

View current documents and versions:

```bash
curl http://127.0.0.1:8000/documents
curl http://127.0.0.1:8000/documents/1/versions
```

View metrics:

```bash
curl http://127.0.0.1:8000/metrics
```

## 6. Query the RAG pipeline

Retrieve evidence only:

```bash
curl -X POST http://127.0.0.1:8000/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"How did I implement caching?","top_k":6}'
```

Generate a grounded cited answer:

```bash
curl -X POST http://127.0.0.1:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"query":"How did I implement caching?","top_k":6}'
```

Upload a single file:

```bash
curl -X POST http://127.0.0.1:8000/documents/index -F 'file=@README.md'
```

## 7. Run evaluation

Create a small golden set using your own filenames and facts:

```bash
curl -X POST http://127.0.0.1:8000/evaluation/run \
  -H 'Content-Type: application/json' \
  -d '{"questions":[{"question":"What is used for caching?","expected_source":"sample.md"}]}'
```

The response reports `recall_at_5`, `mrr`, retrieved filenames, and per-question ranks. Run this before and after retrieval changes instead of claiming unmeasured quality improvements.

## 8. Configuration

| Variable | Default | Purpose |
|---|---|---|
| `KNOWLEDGEOS_KNOWLEDGE` | `data/knowledge` | Explicit corpus directory |
| `KNOWLEDGEOS_DATA` | `data` | Application data directory |
| `KNOWLEDGEOS_DB` | `data/knowledgeos.db` | SQLite database |
| `OLLAMA_URL` | `http://127.0.0.1:11434` | Local Ollama URL |
| `OLLAMA_MODEL` | `qwen3:4b` | Generation model |
| `EMBED_MODEL` | `nomic-embed-text` | Embedding model |
| `EMBED_DIM` | `384` | Offline hash-vector dimension |
| `MAX_CONTEXT_CHARS` | `10000` | Context budget before generation |
| `INDEX_WORKERS` | `2` | Background worker count |
| `KNOWLEDGEOS_AUTO_SYNC` | `1` | Queue a startup scan |

## 9. Troubleshooting

**`ollama_available` is false:** start Ollama and verify `ollama list`. The app remains operational in fallback mode.

**Embedding model changed:** delete `data/knowledgeos.db` and re-index the corpus, or use a migration script before changing `EMBED_MODEL`. Embeddings are model-specific.

**Scanned PDFs return empty text:** the current parser handles text PDFs. Add OCR preprocessing for image-only PDFs in a future ingestion adapter.

**Slow answers:** use `qwen3:4b`, lower `top_k`, keep `MAX_CONTEXT_CHARS` around 8,000–10,000, and avoid running multiple local models simultaneously.

**Do not expose this directly to the Internet:** this single-user local profile has no authentication layer. Bind to `127.0.0.1` as shown unless you add authentication and a reverse proxy.

## 10. Tests

```bash
pytest -q
```
