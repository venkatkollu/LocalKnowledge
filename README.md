# Local KnowledgeOS — Production-Local RAG

Local KnowledgeOS is a privacy-first, production-oriented RAG service for personal documents, notes, research, and source code. It runs locally, keeps the corpus on disk, incrementally indexes changed files, stores document versions, creates local embeddings, combines vector and BM25 retrieval, reranks candidates, builds a bounded context, and returns grounded answers with citations.

It is designed for an **11th-generation Intel i5, 24 GB RAM, and 2 GB MX450**. The safe deployment assumption is CPU/RAM inference. The MX450 is not treated as a required accelerator.

## What changed from the MVP

| Production concern | Current implementation |
|---|---|
| Real semantic retrieval | Ollama `nomic-embed-text` embeddings persisted per chunk |
| No-model resilience | Deterministic local hash embeddings keep the system runnable offline |
| Hybrid search | Vector candidates + SQLite FTS5 BM25 candidates + reciprocal-rank fusion |
| Reranking | Lightweight semantic/lexical reranker over the top 30 candidates |
| Incremental ingestion | SHA-256 document change detection; unchanged files are skipped |
| Versioning | `document_versions` retains historical metadata and version numbers |
| Background work | Thread-pool ingestion jobs with job status, progress, and failure counts |
| Grounding | Evidence-only prompt, untrusted-document boundary, citations, abstention |
| Context engineering | Deduplicated ranked context with a configurable character budget |
| Observability | Query latency, retrieval latency, generation latency, model, and metrics endpoints |
| Evaluation | `/evaluation/run` calculates Recall@5 and MRR against expected source files |
| Operational endpoints | Health, metrics, documents, versions, jobs, search, chat, evaluation |

## Architecture

```text
                         Local browser UI
                                │
                                ▼
                             FastAPI
                                │
        ┌───────────────────────┼────────────────────────┐
        ▼                       ▼                        ▼
 Background ingestion      Query pipeline             Operations
        │                       │                        │
 parser → chunker        query embedding             /health
 SHA-256 → version       vector top-40                /metrics
 batch embeddings        BM25 top-40                  /jobs/{id}
 SQLite + FTS5           RRF top-30                   /evaluation
        │                 rerank → context
        ▼                       │
   SQLite database             ▼
                         Ollama Qwen
                         or extractive fallback
                                │
                                ▼
                         Answer + citations
```

## Local models for this laptop

| Role | Recommended model | Guidance |
|---|---|---|
| Generation default | `qwen3:4b` | Best practical quality/speed balance |
| Generation quality mode | `qwen3:8b` | Better reasoning but slower and more RAM-intensive |
| Embeddings | `nomic-embed-text` | Recommended local embedding model; persisted by chunk |
| Lightweight embedding alternative | `all-minilm` | Lower resource use if supported by your local runtime |
| Reranker later | `bge-reranker-base` | Add a cross-encoder only after benchmarking this reranker |

The application calls Ollama locally for Qwen generation and embeddings. If Ollama is unavailable, generation falls back to extractive grounded responses and embeddings fall back to deterministic local vectors. No document is sent to a cloud service.

## Project structure

```text
local-knowledgeos/
├── app.py                 # API, ingestion, retrieval, generation, evaluation
├── requirements.txt
├── README.md
├── HOW_TO_RUN.md
├── data/knowledge/        # Your local corpus
├── static/                # Browser UI
└── tests/                 # API and pipeline tests
```

## API surface

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/health` | Component and corpus health |
| GET | `/metrics` | Query and ingestion metrics |
| GET | `/documents` | Current document inventory |
| GET | `/documents/{id}/versions` | Version history metadata |
| POST | `/documents/sync` | Queue an asynchronous corpus sync |
| GET | `/jobs/{id}` | Poll a sync job |
| POST | `/documents/index` | Upload and index one supported file |
| POST | `/search` | Retrieve ranked evidence without generation |
| POST | `/chat` | Generate a cited grounded answer |
| POST | `/evaluation/run` | Run Recall@5 and MRR over supplied questions |
| GET | `/evaluation/results` | View saved evaluation runs |

## Evaluation example

```bash
curl -X POST http://127.0.0.1:8000/evaluation/run \
  -H 'Content-Type: application/json' \
  -d '{"questions":[{"question":"What is used for caching?","expected_source":"sample.md"}]}'
```

Do not put invented benchmark numbers in a portfolio README. Run this endpoint against your own corpus and record the measured results.

## Production boundaries

This is production-oriented for a single-user local deployment, not a multi-tenant Internet service. It deliberately does not expose the server publicly, implement user authentication, or claim zero hallucinations. For a team or Internet deployment, add authentication, authorization, encrypted storage, rate limiting, a real task queue, PostgreSQL/pgvector, a cross-encoder reranker, structured tracing, and backup/restore procedures.

The code keeps clear seams for those upgrades: `embed_texts`, `vector_search`, `rerank`, `scan`, and the SQLite persistence layer.
