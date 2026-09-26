# How to run Local KnowledgeOS — production-local mode

These instructions target Ubuntu/Linux, macOS, and Windows through WSL. The project is designed for CPU/RAM inference on an i5 11th Gen, 24 GB RAM laptop with a 2 GB MX450.

## 1. Install prerequisites

Install Python 3.11 or newer:

```bash
python3 --version
```

Install [LM Studio](https://lmstudio.ai). It provides the local OpenAI-compatible server used by the default configuration.

## 2. Create the environment

From the project directory:

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows PowerShell: .venv\\Scripts\\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## 3. Configure LM Studio

In LM Studio:

1. Download/load `qwen/qwen3-0.6b`.
2. Open **Developer**.
3. Start the local server.
4. Confirm the server URL is `http://127.0.0.1:1234/v1`.

Verify the exact model ID:

```bash
curl http://127.0.0.1:1234/v1/models
```

The response should contain `qwen/qwen3-0.6b`. If your ID is different, set it before starting KnowledgeOS:

```bash
export LMSTUDIO_MODEL='your-exact-model-id'
```

The embedding model is configured as `text-embedding-nomic-embed-text-v1.5`. If your LM Studio model list shows another embedding ID, set:

```bash
export LMSTUDIO_EMBED_MODEL='your-exact-embedding-model-id'
```

Ollama remains an optional fallback provider:

```bash
ollama pull qwen3:4b
ollama pull nomic-embed-text
ollama serve
```

Use `qwen3:8b` only as a slower quality mode:

```bash
ollama pull qwen3:8b
export OLLAMA_MODEL=qwen3:8b
```

The MX450 is not required. Do not expect the 2 GB GPU to hold a 4B/8B model reliably; CPU/RAM inference is the supported baseline.

Without Ollama, the application still works using a deterministic local hash embedding fallback and extractive grounded answers. This is useful for smoke tests, but Ollama embeddings will give substantially better semantic retrieval.

## 4. Add documents

Put Markdown, text, source code, JSON/YAML/CSV, HTML/CSS/SQL, or text-based PDFs under:

```text
data/knowledge/
```

Subdirectories are supported. Only this explicitly configured directory is indexed.

## 5. Easiest option: terminal prompt mode

This is the recommended workflow. It starts the API automatically, checks the LM Studio connection, accepts prompts in the terminal, and prints the answer, retrieval evaluation, timings, and citations beneath each prompt:

```bash
source .venv/bin/activate
python run_local.py
```

Example:

```text
KnowledgeOS is ready
  LM Studio: connected at http://127.0.0.1:1234/v1

You> How did I implement caching?

ANSWER
...

RETRIEVAL EVALUATION
Dense candidates       40
BM25 candidates        40
RRF candidates         30
Reranked               30
Final context          6
Retrieval latency      42.1 ms
Generation latency     1840.2 ms
Total latency          1882.9 ms
```

Available terminal commands:

```text
/sync     Queue a background document sync
/health   Check LM Studio and corpus status
/help     Show commands
/quit     Exit
```

## 6. Chunk-level incremental indexing

KnowledgeOS does **not** re-embed the whole database when a document changes.

For every file, it compares:

```text
SHA-256(document)
        ↓
changed document only
        ↓
SHA-256(each chunk)
        ↓
reuse existing embedding for matching chunk hashes
embed only new or modified chunks
```

Example: if a document has 20 chunks and only 2 changed, the sync reuses 18 embeddings and creates only 2 new embeddings. The previous document version remains available in SQLite metadata.

When you run `/sync`, the terminal prints:

```text
documents_added
documents_changed
documents_deleted
chunks_before
chunks_after
added_chunks
removed_chunks
reused_embeddings
new_embeddings
```

You can also inspect the latest report without the terminal client:

```bash
curl http://127.0.0.1:8000/changes/latest
```

The job endpoint also includes the report:

```bash
curl http://127.0.0.1:8000/jobs/YOUR_JOB_ID
```

## 7. Start the web service manually

Development mode:

```bash
source .venv/bin/activate
uvicorn app:app --host 127.0.0.1 --port 8000 --reload
```

Production-like local mode:

```bash
source .venv/bin/activate
uvicorn app:app --host 127.0.0.1 --port 8000
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000).

At startup, a background sync job is queued. The UI's **Queue full sync** button also returns a job ID and does not block the API request.

## 8. Verify health and monitor jobs

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/metrics
curl http://127.0.0.1:8000/documents
```

Queue a sync:

```bash
curl -X POST http://127.0.0.1:8000/documents/sync
```

Copy the returned `job_id` and inspect it:

```bash
curl http://127.0.0.1:8000/jobs/YOUR_JOB_ID
```

A job moves through `queued`, `running`, and `completed`. A failed document is recorded as `failed`; the remaining files continue indexing.

## 9. Ask questions and inspect retrieval

Hybrid retrieval without generation:

```bash
curl -X POST http://127.0.0.1:8000/search \\
  -H 'Content-Type: application/json' \\
  -d '{"query":"How did I implement caching?","top_k":6}'
```

Grounded RAG answer with citations and timings:

```bash
curl -X POST http://127.0.0.1:8000/chat \\
  -H 'Content-Type: application/json' \\
  -d '{"query":"How did I implement caching?","top_k":6}'
```

The response contains `citations`, document versions, `retrieval_ms`, `generation_ms`, `request_id`, and the selected model. Retrieved documents are treated as untrusted data, not instructions.

## 10. Run an evaluation

Create a JSON payload:

```json
{
  "questions": [
    {"question": "Which database stores durable data?", "expected_sources": ["sample.md"]},
    {"question": "What is used for caching?", "expected_source": "sample.md"}
  ]
}
```

Run it:

```bash
curl -X POST http://127.0.0.1:8000/evaluation/run \\
  -H 'Content-Type: application/json' \\
  --data @evaluation.json
curl http://127.0.0.1:8000/evaluation/results
```

The current benchmark reports **Recall@5** and **MRR** for source retrieval. Expand the dataset with factual, multi-document, temporal, and negative questions before presenting results.

## 11. Configuration

| Variable | Default | Purpose |
|---|---|---|
| `KNOWLEDGEOS_KNOWLEDGE` | `data/knowledge` | Explicit directory to index |
| `KNOWLEDGEOS_DATA` | `data` | SQLite database directory |
| `KNOWLEDGEOS_DB` | `data/knowledgeos.db` | Database path |
| `LLM_PROVIDER` | `lmstudio` | `lmstudio`, `ollama`, or `auto` |
| `LMSTUDIO_URL` | `http://127.0.0.1:1234/v1` | LM Studio OpenAI-compatible base URL |
| `LMSTUDIO_MODEL` | `qwen/qwen3-0.6b` | Exact model ID from `/v1/models` |
| `LMSTUDIO_EMBED_MODEL` | `text-embedding-nomic-embed-text-v1.5` | Exact embedding model ID in LM Studio |
| `OLLAMA_URL` | `http://127.0.0.1:11434` | Optional Ollama fallback endpoint |
| `OLLAMA_MODEL` | `qwen3:4b` | Optional Ollama fallback model |
| `EMBED_MODEL` | `nomic-embed-text` | Embedding model requested from Ollama |
| `EMBED_DIM` | `384` | Local fallback vector dimension |
| `INDEX_WORKERS` | `2` | Background executor worker count |
| `MAX_CONTEXT_CHARS` | `10000` | Context bound sent to the LLM |
| `KNOWLEDGEOS_AUTO_SYNC` | `1` | Queue a startup sync when enabled |

## 12. Run tests

```bash
.venv/bin/python -m pytest -q
```

Use `python -m pytest`, not a globally installed `pytest`, so the project virtual environment is used.

## Troubleshooting

**LM Studio is not connected.** Open LM Studio, load `qwen/qwen3-0.6b`, start the Developer server, then run `curl http://127.0.0.1:1234/v1/models`. If the model ID differs, export `LMSTUDIO_MODEL` to the exact returned ID.

**The terminal client reports an empty LM Studio response.** Make sure the model is loaded, not merely downloaded, and that the server is running at `http://127.0.0.1:1234/v1`.

**`ollama_available` is false.** This is expected when using LM Studio. Ollama is only an optional fallback.

**Embeddings use `local-hash-fallback`.** LM Studio's embedding endpoint or configured embedding model is unavailable. Check `/v1/models`, correct `LMSTUDIO_EMBED_MODEL`, and run `/sync` so chunks are embedded again.

**A PDF produces little text.** The MVP extracts text PDFs with `pypdf`; scanned/image-only PDFs require OCR, which should be added as a separate ingestion adapter.

**Old content appears after editing a file.** Queue a sync and inspect the job. Changed files receive a new `document_versions` row; unchanged files are skipped by SHA-256.

**Responses are slow.** Prefer `qwen3:4b`, reduce `top_k` to 4, keep `MAX_CONTEXT_CHARS` bounded, and avoid running multiple model services simultaneously.
