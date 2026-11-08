# Backend architecture

The backend is a FastAPI application assembled in `main.py`. `main.py` only
creates the app, installs CORS and the lifespan, and mounts the routers. All
request logic and domain behavior lives in the modules below it, so a feature
can be changed without editing the entry point.

## Layout

```
backend/
├── main.py          # Thin app assembler: CORS, lifespan, include_router only
├── config.py        # Environment constants + validated Settings (one instance)
├── runtime.py       # Thread pool and shared embedding/Ollama runtime state
├── security.py      # Private file modes, secret lifecycle, Fernet helpers
├── db.py            # SQLite connection, schema, migrations, backups
├── auth.py          # Principal and workspace/bearer authentication
├── utils.py         # Text, hashing, chunk splitting, vectors, query planning
├── chunking.py      # Structure-aware ChunkInfo adapter over utils.split_chunks
├── providers.py     # Provider profiles + OpenAI/Ollama embedding transport
├── parsing.py       # PDF/DOCX/XLSX/PPTX/CSV/HTML/image extraction
├── documents.py     # Document catalog rows and API serialization
├── ingestion.py     # Upload storage, job queue, ingestion pipeline
├── retrieval.py     # SQL catalog filters + hybrid FTS5/dense retrieval
├── routing.py       # Three-tier SQL/VECTOR/HYBRID query router
├── verification.py  # Claim splitting and deterministic entailment
├── cache.py         # Answer cache identity, lookup, store, eval guard
├── indexes.py       # Build/validate/evaluate/activate/rollback index lifecycle
├── answering.py     # Metadata answers, small talk, retrieval-augmented answers
└── api/             # Thin HTTP routers grouped by resource
    ├── chat.py
    ├── documents.py
    ├── evaluations.py
    ├── indexes.py
    ├── models.py
    └── system.py
```

## Dependency direction

Configuration and security sit at the bottom:

`config` → `security` → `utils` → `db` → `providers` → `retrieval` →
`routing` / `indexes` → `ingestion` → `answering` → `api` → `main`.

A module may import from a lower layer, never from a higher one. The two
intentional lazy imports are `indexes.refresh_index_membership` inside
`db.init_db()` and `config.SETTINGS` inside the encryption helpers.

`main.py` must stay an assembler. Route handlers belong in `api/`; reusable
logic belongs in the domain modules. If a route needs behavior, call a module
function instead of copying it into the router.

## Request flow

`POST /api/chat` enters `api.chat`, which calls `answering.answer_question`:

1. `utils.route_query` extracts intent, filenames and document IDs.
2. Greetings short-circuit to a conversational response (no embedding call).
3. `routing.decide_route` classifies the question as `SQL`, `VECTOR` or
   `HYBRID`. The decision is logged to `routing_log` for later inspection.
4. Catalog questions are answered by the metadata SQL branch, which returns
   before retrieval and finalizes the routing outcome as `metadata_answer`.
5. Otherwise the query is embedded through `providers.embed_text`, the answer
   cache is checked, and `retrieval.retrieve` fuses FTS5/BM25 with cosine
   similarity scoped to the active index membership.
6. The evidence gate abstains below `SETTINGS.abstain_threshold`; a provider
   failure returns the retrieved evidence with an uncertain decision.
7. `verification.verify_claims` scores each claim against its best citation.
8. A trace is written, the answer is cached when eligible, and the response is
   returned. `/api/chat/stream` emits citations, then the answer text as SSE
   events.

## Ingestion flow

`POST /api/documents` stores the original under `data/files/<workspace>/` and
queues a job. `ingestion.process_job` extracts text with `parsing.py`, splits
it with `chunking.StructureAwareChunker` (which delegates to
`utils.split_chunks`), embeds each chunk through `providers.embed_text`, and
writes chunks, FTS5 rows, document versions and index membership in one short
transaction per phase. Provider calls never hold a SQLite transaction open.

Chunks keep character offsets, line numbers, page spans, heading breadcrumbs
and a content type (`text`, `heading`, `table`, `figure`, `list`, `code`,
`equation`). The API and retrieval read the same metadata, so the splitter has
exactly one implementation.

## Storage and index lifecycle

One SQLite database in WAL mode holds workspaces, documents/versions, chunks,
FTS5 rows, embeddings, jobs, traces, cache entries, golden sets and index
revisions. Every row carries a workspace ID.

Index revisions move `building → ready → active → retired`. Candidate indexes
are snapshots; the active index is refreshed after ingestion and activation so
new documents stay searchable without mixing embedding spaces. Index IDs
include a UUID suffix (`index-v<revision>-<suffix>`) because `index_versions.id`
is globally unique across workspaces.

## Tests

```bash
python3 -m pytest                          # API + behavior suite (fake providers)
python3 tests/smoke_runner.py              # isolated routing + index-build smoke test
```

The pytest fixtures fake `backend.providers.embed_text`,
`backend.providers.provider_request` and `backend.runtime.EXECUTOR`, which are
the real call sites. They do not patch `backend.main` aliases.

`tests/retrieval_and_cache_checks.py` and `tests/test_secret_management.py`
are subprocess characterization suites and run standalone.
