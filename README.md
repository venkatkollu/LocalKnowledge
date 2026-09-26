# Local KnowledgeOS — Production-Local RAG

Local KnowledgeOS is a **privacy-first, production-oriented RAG system** for personal documents, notes, source code, and research. It is designed for an i5 11th Gen laptop with 24 GB RAM and a 2 GB MX450: ingestion, embeddings, retrieval, reranking, evaluation, and generation all run locally, with CPU/RAM as the default execution target.

The project now goes beyond a demo chatbot. It includes incremental and versioned ingestion, persisted embeddings, hybrid retrieval, reciprocal-rank fusion, reranking, asynchronous jobs, citation metadata, structured latency metrics, evaluation endpoints, prompt-injection defenses, and a grounded abstention path.

## Production capabilities

| Area | Implementation |
|---|---|
| Ingestion | Background sync jobs with job IDs and progress state |
| Change detection | SHA-256 document hashing; unchanged files are skipped |
| Versioning | `document_versions` preserves content hash, parser/chunker versions, and embedding model |
| Chunking | Paragraph-aware chunks with overlap and section metadata |
| Embeddings | LM Studio `/v1/embeddings` using `text-embedding-nomic-embed-text-v1.5`; deterministic local fallback otherwise |
| Vector retrieval | Persisted JSON vectors with cosine similarity; isolated behind `vector_search()` |
| Lexical retrieval | SQLite FTS5 BM25 retrieval for exact identifiers and terminology |
| Fusion | Reciprocal-rank fusion of dense and lexical candidates |
| Reranking | Lightweight local cross-signal reranker over the top 30 candidates |
| Context engineering | Ranked, bounded, source-labelled context with document version information |
| Generation | LM Studio OpenAI-compatible `/v1/chat/completions` using Qwen3 0.6B |
| Grounding | Inline citation instructions, abstention, untrusted-evidence delimiters, no-instruction document policy |
| Observability | `/metrics`, per-query latency logs, retrieval/generation timings, request IDs |
| Evaluation | `/evaluation/run` with Recall@5 and MRR, plus persisted results |
| Usability | `python run_local.py` starts the service, accepts terminal prompts, and prints retrieval evaluation under each answer |
| Privacy | No cloud API; only configured local filesystem paths are indexed |
| Reliability | Failed files do not stop the batch; job and document errors are recorded |

## Architecture

```text
                 ┌───────────────────────────────┐
                 │ Browser UI / REST API          │
                 └──────────────┬────────────────┘
                                │
                       ┌────────▼────────┐
                       │ FastAPI service │
                       └──────┬─────┬────┘
                              │     │
                 background  │     │ query trace
                 sync jobs   │     │
                       ┌──────▼─┐ ┌─▼─────────────────────┐
                       │SQLite  │ │ Query pipeline          │
                       │versions│ │ embed → vector + BM25  │
                       │chunks  │ │ → RRF → rerank → context│
                       │jobs    │ └───────────┬────────────┘
                       └──────┬─┘             │
                              │        ┌──────▼──────┐
                       ┌──────▼──────┐ │ LM Studio  │
                       │ local files │ │ Qwen/embed │
                       └─────────────┘ └─────────────┘
```

## Recommended models for your laptop

Do not build around the 2 GB MX450. Use CPU/RAM inference and keep model context bounded.

| Role | Recommended default | Alternative | Notes |
|---|---|---|---|
| Generation | `qwen/qwen3-0.6b` in LM Studio | `qwen3:4b` through Ollama | Small and responsive for terminal use |
| Embeddings | `text-embedding-nomic-embed-text-v1.5` in LM Studio | `nomic-embed-text` through Ollama | Use the exact ID returned by `/v1/models` |
| Fastest generation | Qwen 2.5 3B | — | Use when latency matters more than reasoning quality |
| Reranking later | `bge-reranker-base` | — | The current reranker is dependency-light; add a cross-encoder after benchmarking |

LM Studio is the default provider. If it is unavailable, the project still runs with deterministic local hash embeddings and extractive grounded responses. Set `LLM_PROVIDER=ollama` for Ollama or `LLM_PROVIDER=auto` for LM Studio-then-Ollama fallback.

## Simplest terminal workflow

After loading `qwen/qwen3-0.6b` and starting the LM Studio Developer server:

```bash
python run_local.py
```

This starts the API automatically, checks `http://127.0.0.1:1234/v1/models`, accepts questions interactively, and prints the answer followed by dense/BM25/RRF/reranking counts, stage latency, and citations. Use `/sync`, `/health`, `/help`, and `/quit` inside the prompt.

## API surface

| Endpoint | Purpose |
|---|---|
| `GET /health` | Service, corpus, embedding, LM Studio, and Ollama status |
| `GET /metrics` | Query latency and ingestion-job aggregates |
| `GET /documents` | Current indexed documents and statuses |
| `GET /documents/{id}/versions` | Version history and embedding metadata |
| `POST /documents/sync` | Queue a background full sync; returns `job_id` |
| `GET /jobs/{job_id}` | Poll a sync job |
| `POST /documents/index` | Upload and index one supported file |
| `POST /search` | Hybrid retrieval without generation |
| `POST /chat` | Retrieval, reranking, grounded generation, and citations |
| `POST /evaluation/run` | Run Recall@5/MRR against a question set |
| `GET /evaluation/results` | View stored evaluation results |

## Evaluation example

```json
{
  "questions": [
    {
      "question": "Which database stores durable data?",
      "expected_sources": ["sample.md"]
    }
  ]
}
```

Send it to `POST /evaluation/run`. Do not put invented benchmark numbers in a portfolio README; use the endpoint to generate measurements from your own corpus.

## Project layout

```text
local-knowledgeos/
├── app.py                 # FastAPI service and production-local RAG pipeline
├── run_local.py           # One-command terminal prompt interface
├── requirements.txt       # Runtime and test dependencies
├── README.md              # Architecture and design notes
├── HOW_TO_RUN.md          # Setup, operations, API, and troubleshooting
├── data/knowledge/        # Explicitly indexed local files
├── static/                # Browser UI
└── tests/                 # API and pipeline tests
```

## Honest scope

This is production-oriented for a **single-user local deployment**, not a multi-tenant cloud service. SQLite is intentional: it is reliable, zero-operations, and appropriate for a personal laptop. When the corpus or concurrency grows beyond that boundary, the seams are ready for PostgreSQL + pgvector, Redis-backed job queues, a real cross-encoder reranker, and a process supervisor. The project does not claim zero hallucinations; it provides evidence constraints, citations, abstention, and measurable retrieval/generation traces.
