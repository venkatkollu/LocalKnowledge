# Local KnowledgeOS

Local-first RAG workspace for indexing private documents and asking grounded
questions with citations. The repository contains a Vite/React frontend and a
FastAPI backend. The backend is intentionally self-contained for local use:
SQLite provides transactional metadata and FTS5 sparse retrieval, while the
uploaded originals and derived vectors live under the local data directory.

Everything runs on your machine by default. Remote OpenAI-compatible providers
are optional, and provider credentials are encrypted at rest.

## Highlights

- **Local ingestion** for Markdown, text, PDF, source code, JSON, YAML, CSV,
  SQL, HTML, CSS, XML, and log files, plus local folders and shallow HTTPS Git
  clones.
- **Hybrid retrieval**: FTS5/BM25 lexical search plus dense cosine similarity,
  reciprocal-rank fusion, a local reranking heuristic, and an evidence gate
  that abstains when the retrieved context is too weak.
- **Local embeddings** through Ollama (`all-minilm` by default), with optional
  OpenAI-compatible embedding or generation provider profiles.
- **Streaming answers** with citations, evidence-quality metadata, trace IDs,
  and thumbs-up/down feedback.
- **Semantic answer cache** scoped by workspace, active index, provider,
  prompt version, and query, with a similarity threshold and TTL.
- **Document lifecycle**: SHA-256 deduplication, version history, incremental
  sync, chunk clearing, soft deletion, and per-stage job progress.
- **Blue-green indexes**: create, build, validate, evaluate, activate, and
  roll back without interrupting the active revision.
- **Evaluation**: golden-set Recall@100, nDCG@10, and MRR@10 with regression
  gates before activation.
- **Observability**: traces, latency percentiles, stage timings, query
  outcomes, activity events, and storage statistics.
- **Workspace isolation** on every row, header-driven principal resolution,
  optional bearer authentication, and encrypted provider keys.
- **Docker Compose** bundle with the API, web UI, and Ollama, plus a normal
  local-development workflow.

## Architecture

```text
Browser (React + Vite)
      │  /api requests, multipart uploads, fetch-based SSE
      ▼
Vite dev proxy (local) or nginx reverse proxy (Docker)
      ▼
FastAPI API
  ├─ Principal dependency: workspace/user headers and optional bearer auth
  ├─ Provider profiles: Fernet-encrypted keys, circuit-breaker health state
  ├─ Ingestion executor: parse → chunk → embed → index → validate
  ├─ Query pipeline: route → embed → semantic cache → FTS5 + dense scan
  │                  → RRF/rerank heuristic → evidence gate → answer
  └─ Traces, feedback, metrics, index/evaluation lifecycle
      ├─ SQLite (WAL): metadata, jobs, chunks, FTS5, vectors, traces, cache
      └─ data/files/<workspace>: immutable uploaded/local copies
```

The storage adapter is deliberately replaceable. SQLite/FTS5 is the local
baseline; a production deployment can move metadata to PostgreSQL, vectors to
pgvector/Qdrant, originals to S3/MinIO, and queue/cache work to Redis without
changing the frontend API contract.

## Quick start with Docker (recommended)

Requirements: Docker Engine with the Compose plugin. Ollama runs inside the
Compose stack, so you do not need Ollama installed on the host.

```sh
cp .env.docker.example .env
docker compose up --build -d
```

Open <http://localhost:8080>. The first start pulls the embedding model
(`all-minilm` by default) into the `ollama-models` volume. Watch progress with:

```sh
docker compose logs -f ollama-pull backend
```

Useful Docker commands:

```sh
docker compose ps                       # service health
docker compose logs -f frontend backend # follow logs
docker compose up --build -d            # rebuild after code changes
docker compose down                     # stop, keep data and models
docker compose down -v                  # stop and delete data + model volumes
```

The UI is served by nginx and proxies `/api` to the backend inside the Compose
network. The backend is not published to the host by default. Change the host
port with `KNOWLEDGEOS_HTTP_PORT` in `.env`.

### Optional GPU acceleration

The default Ollama service runs on CPU. With the NVIDIA Container Toolkit
installed, enable GPU inference for faster embeddings:

```sh
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up --build -d
```

### Use an existing Ollama installation

To reuse Ollama on the host, remove the `ollama` and `ollama-pull` services from
Compose (or stop them) and set:

```sh
KNOWLEDGEOS_OLLAMA_BASE_URL=http://host.docker.internal:11434
```

On Linux, add `extra_hosts: ["host.docker.internal:host-gateway"]` to the
backend service if that hostname is unavailable.

### Docker secrets

The backend container generates a strong auth secret and Fernet encryption key
on first boot and persists them in the `knowledgeos-data` volume under
`/data/secrets` with mode `0600`. They survive restarts and are never written to
the repository.

You can instead provide secrets explicitly through `.env`, Docker secrets, or
your orchestrator:

```sh
KNOWLEDGEOS_AUTH_SECRET=<64+ random characters>
KNOWLEDGEOS_ENCRYPTION_KEY=<base64 Fernet key>
```

The backend also accepts file-based secret variables for Docker/Kubernetes
secrets:

```sh
KNOWLEDGEOS_AUTH_SECRET_FILE=/run/secrets/auth_secret
KNOWLEDGEOS_ENCRYPTION_KEY_FILE=/run/secrets/encryption_key
```

Generate values with:

```sh
python3 -c "import secrets; print(secrets.token_hex(32))"
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

## Run locally without Docker

Requirements: Node.js 22+, npm, Python 3.11+, and Git if repository ingestion
is used. Ollama is required for local embeddings unless you configure a remote
embeddings provider.

### 1. Backend

```sh
python3 -m pip install -r backend/requirements.txt
./backend/check_dependencies.py
sh backend/setup_ollama.sh        # installs Ollama if needed and pulls all-minilm
./backend/run.sh
```

When using a virtual environment, point the launcher at that interpreter:

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r backend/requirements.txt
KNOWLEDGEOS_PYTHON=.venv/bin/python ./backend/run.sh
```

### 2. Frontend

```sh
npm install
npm run dev
```

Open <http://localhost:5173>. Vite serves the UI and proxies `/api` to
`http://127.0.0.1:8000`. If the API is hosted elsewhere, set
`VITE_KNOWLEDGEOS_API_URL` (see `.env.example`).

Useful checks:

```sh
npm run build
npm run lint
python3 -m py_compile backend/main.py
```

## Configuration

Backend environment variables are read directly from the process environment
(or a `_FILE` variant for secrets). Docker Compose reads the untracked `.env`
file for interpolation. The frontend exposes only `VITE_*` variables at build
time.

### Storage and runtime

| Variable | Default | Purpose |
| --- | --- | --- |
| `KNOWLEDGEOS_DATA_DIR` | `data` | SQLite database, originals, and generated secrets |
| `KNOWLEDGEOS_WORKERS` | `4` | Thread-pool workers for ingestion |
| `KNOWLEDGEOS_SQLITE_BUSY_TIMEOUT_MS` | `60000` | SQLite busy timeout |
| `KNOWLEDGEOS_HOST` | `127.0.0.1` | Bind host used by `backend/run.sh` |
| `KNOWLEDGEOS_PORT` | `8000` | Bind port used by `backend/run.sh` |
| `KNOWLEDGEOS_PYTHON` | `python3` | Interpreter used by `backend/run.sh` |

### Authentication and secrets

| Variable | Default | Purpose |
| --- | --- | --- |
| `KNOWLEDGEOS_ALLOW_ANONYMOUS` | `true` | Accept requests without a bearer token |
| `KNOWLEDGEOS_AUTH_SECRET` | local dev secret | HMAC key for bearer-token validation |
| `KNOWLEDGEOS_ENCRYPTION_KEY` | derived from auth secret | Fernet key for provider API keys |
| `KNOWLEDGEOS_CORS_ORIGINS` | local Vite origins | Comma-separated allowed browser origins |

Bearer tokens are `hex(HMAC-SHA256(auth_secret, "<workspace>:<user>"))`.
The frontend sends `X-Workspace-ID` and `X-User-ID`, plus
`Authorization: Bearer …` when a token is configured. Use the `/auth` page to
save the workspace, user, and token in browser local storage, or inject the
header at your reverse proxy.

### Ollama and embeddings

| Variable | Default | Purpose |
| --- | --- | --- |
| `KNOWLEDGEOS_OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Ollama API endpoint |
| `KNOWLEDGEOS_OLLAMA_EMBEDDING_MODEL` | `all-minilm` | Embedding model |
| `KNOWLEDGEOS_ALLOW_HASH_EMBEDDING_FALLBACK` | `false` | Explicit test-only deterministic vectors |

Use `bge-m3` or `nomic-embed-text` for higher retrieval quality at the cost of
memory and speed. A provider profile with the `Embeddings` or `Both` role
overrides Ollama. The deterministic hash fallback is disabled by default and
should only be enabled for isolated offline tests.

After changing the embedding model in an existing workspace, run **Sync** on
previously indexed documents so their vectors are regenerated with the same
model used for queries.

### Ingestion limits

| Variable | Default | Purpose |
| --- | --- | --- |
| `KNOWLEDGEOS_MAX_UPLOAD_BYTES` | `536870912` (512 MiB) | Per-file upload limit |
| `KNOWLEDGEOS_MAX_BATCH_FILES` | `10000` | Files per upload/folder/repository |
| `KNOWLEDGEOS_MAX_EXTRACTED_BYTES` | `67108864` (64 MiB) | Text extracted per document |
| `KNOWLEDGEOS_CHUNK_SIZE` | `1200` | Target characters per chunk |
| `KNOWLEDGEOS_CHUNK_OVERLAP` | `180` | Overlap characters between chunks |

### Retrieval and cache

| Variable | Default | Purpose |
| --- | --- | --- |
| `KNOWLEDGEOS_DENSE_SCAN_LIMIT` | `50000` | Maximum vectors scanned per query |
| `KNOWLEDGEOS_CACHE_TTL_SECONDS` | `604800` (7 days) | Semantic cache lifetime |
| `KNOWLEDGEOS_CACHE_SIMILARITY` | `0.92` | Minimum cosine similarity for cache hits |

## Ingestion flow

1. The Documents page uploads one or many files, submits a local folder path,
   or requests a shallow HTTPS Git clone.
2. The backend streams each file to workspace storage while computing SHA-256.
3. Content hashes deduplicate identical files. Folder sources retain the
   original absolute directory so a later Sync can detect changed bytes.
4. A background job moves through `queued → running → completed|failed` and
   exposes its stage/progress through `/api/sync` and `/api/jobs/{id}`.
5. Text/PDF content is chunked, embedded with local Ollama or the configured
   embeddings provider, inserted into FTS5, and recorded as a document version.
   Old chunks are superseded only after the new chunks are prepared.
6. Re-uploading a changed file updates the existing source document instead of
   creating a duplicate. Deletion removes it from retrieval and invalidates
   workspace cache entries.

PDF text is extracted with `pypdf`. Image-only/scanned PDFs produce no chunks;
OCR is not included.

## Query flow

`POST /api/chat` and `POST /api/chat/stream` use the same answer pipeline:

1. Resolve the active index and generation profile.
2. Perform lightweight query understanding: compound-question splitting and
   text/table/figure routing, then embed the query with the same model used for
   ingestion.
3. Check the semantic cache, scoped by workspace, index version, model profile,
   prompt version, and query hash/embedding. Low-confidence answers are never
   cached; activating an index removes entries from older index versions.
4. On a miss, retrieve with both FTS5 lexical search and dense cosine
   similarity, with workspace/document filters pushed into the queries.
5. Fuse/rank candidates, apply the evidence gate, and either call the selected
   OpenAI-compatible provider or return grounded local evidence.
6. Persist a trace containing route, cache status, model, stage timings, token
   counts, prompt version, outcome, and trace ID.

The streaming endpoint sends `citations` before `token`, then `done` or
`error`. The React client uses `fetch()` and a `ReadableStream` so workspace
headers can be sent; this avoids the `EventSource` authorization-header
limitation.

## Index lifecycle and evaluation

Indexes are blue-green revisions:

```text
create → build → validate → evaluate → activate
                                  └── failed gate: remain inactive
active → rollback → previous validated revision
```

Every workspace has its own index versions. A golden set can be populated with
`/api/evaluations/golden`; evaluation records Recall@100, nDCG@10, and MRR@10.
Activation requires validation and, when a golden set exists, a completed
evaluation. Regression gates block activation when Recall@100 drops by more
than 3 points or nDCG@10 drops by more than 5 points. Answer thumbs-up/down
feedback is stored through `/api/feedback` against the same trace ID.

## Provider profiles and API-key security

The Models page supports FreeLLM API, OmniRouter, OpenRouter, NVIDIA NIM, and
any custom OpenAI-compatible endpoint. A profile contains a display name, base
URL, model ID, role (`Generation`, `Embeddings`, or `Both`), and API key.

- Keys are accepted once by the backend and encrypted with Fernet before being
  stored in SQLite.
- The API never returns key material; list responses only expose
  `has_api_key: true`.
- The browser never persists provider keys in `localStorage`.
- Repeated provider failures mark a provider unhealthy for 60 seconds so
  another eligible profile can be selected.
- The provider test endpoint performs a `GET /models` probe.

Set a stable `KNOWLEDGEOS_ENCRYPTION_KEY` in deployments. If it is omitted, a
local development key is derived from `KNOWLEDGEOS_AUTH_SECRET`; changing that
secret makes previously stored provider keys undecryptable. The Docker entry
point generates and persists both values in the data volume.

## Security checklist for non-local deployments

- Set `KNOWLEDGEOS_ALLOW_ANONYMOUS=false` and a long random
  `KNOWLEDGEOS_AUTH_SECRET`.
- Set an explicit `KNOWLEDGEOS_ENCRYPTION_KEY` and back it up; losing it makes
  stored provider keys unrecoverable.
- Terminate TLS at a reverse proxy or load balancer and keep the API on a
  private network.
- Restrict `KNOWLEDGEOS_CORS_ORIGINS` to your real frontend origin.
- Do not commit `.env`, `data/`, SQLite files, generated secrets, or provider
  keys. These paths are covered by `.gitignore` and `.dockerignore`.
- Keep `KNOWLEDGEOS_ALLOW_HASH_EMBEDDING_FALLBACK=false`.
- Back up `data/knowledgeos.sqlite3`, `data/files/`, and the secrets directory
  together.
- Use Docker secrets, Kubernetes secrets, or an external secret manager instead
  of plaintext environment variables when available.

## API surface

| Area | Endpoints |
| --- | --- |
| Health/config | `GET /health`, `GET /api/health`, `GET /api/config`, `GET /api/storage` |
| Providers | `GET/POST /api/models/profiles`, `PATCH/DELETE /api/models/profiles/{id}`, `POST /api/models/profiles/{id}/test` |
| Documents | `GET/POST /api/documents`, `GET/DELETE /api/documents/{id}`, `DELETE /api/documents/{id}/chunks`, `POST /api/documents/sync`, `POST /api/documents/index`, `GET /api/changes/latest` |
| Jobs/activity | `GET /api/sync`, `GET/DELETE /api/jobs/{id}`, `GET /api/activity`, `GET /api/metrics` |
| Query | `POST /api/chat`, `POST /api/chat/stream`, `POST /api/feedback` |
| Indexes | `GET/POST /api/indexes`, `POST /api/indexes/{id}/{build,validate,evaluate,activate,rollback}` |
| Evaluation | `GET/POST /api/evaluations/golden` |
| Repository | `POST /api/repositories/git` (HTTPS clone, shallow depth) |

Every endpoint uses the `principal` dependency. The default local mode accepts
anonymous requests and assigns the `default` workspace.

## Data and backups

By default, the backend creates `data/knowledgeos.sqlite3` and
`data/files/<workspace>/`. In Docker these live in the `knowledgeos-data` named
volume. Back up the database, originals, and `/data/secrets` together.

```sh
# Example local backup
tar -czf knowledgeos-backup-$(date +%F).tgz data/
```

To reset a Docker workspace completely:

```sh
docker compose down -v
```

## Frontend routes

| Route | Purpose |
| --- | --- |
| `/` | Streaming chat with citations, evidence, and feedback |
| `/documents` | Upload, folder/Git ingestion, search/filter, sync, clear, remove |
| `/collections` | Documents grouped by source path |
| `/sync` | Documents needing sync/index plus active job progress |
| `/activity` | Document, sync, query, and error event timeline |
| `/performance` | Latency percentiles, stage timings, query outcomes |
| `/evaluations` | Evidence-gate and retrieval-quality summary |
| `/models` | Provider profiles and connection tests |
| `/indexes` | Create and manage blue-green index revisions |
| `/settings` | Read-only runtime configuration |
| `/storage` | Original and chunk storage statistics |
| `/dashboard` | Workspace overview |
| `/auth` | Save workspace, user, and optional bearer token |

## Project layout

```text
backend/
  main.py                 FastAPI app, SQLite schema, ingestion, retrieval, traces
  requirements.txt        Python runtime dependencies
  run.sh                  Local uvicorn launcher
  setup_ollama.sh         Install/start Ollama and pull the embedding model
  check_dependencies.py   Import check for the selected interpreter
docker/
  backend-entrypoint.sh   Persistent Docker secret bootstrap
  nginx.conf              Static UI, /api proxy, SSE-friendly settings
src/
  api/                    Typed API clients, SSE parsing, error handling
  components/             Chat, shell, document UI, shared design system
  hooks/                  Documents, telemetry, backend health, auth, media
  pages/                  Route-level workspaces
  lib/                    Formatting, file kinds, navigation metadata
Dockerfile                Multi-stage frontend build + nginx runtime
backend/Dockerfile        Python API image
docker-compose.yml        Frontend, backend, Ollama, model bootstrap
docker-compose.gpu.yml    Optional NVIDIA GPU override for Ollama
```

## Troubleshooting

**The UI says "Could not load documents".**
Confirm the backend is reachable at `/api/health`. In Docker, run
`docker compose ps` and `docker compose logs backend`. In local development,
ensure `./backend/run.sh` is running on port 8000 and Vite proxies `/api`.

**Ingestion finishes but a PDF has zero chunks.**
`pypdf` could not extract text. The PDF is probably scanned or image-only;
OCR is not part of this phase.

**Embedding errors mention Ollama.**
Run `sh backend/setup_ollama.sh`, or in Docker check
`docker compose logs ollama-pull ollama`. Confirm the configured model exists:

```sh
ollama list
curl http://127.0.0.1:11434/api/tags
```

**Retrieval quality drops after changing the embedding model.**
Run Sync on all documents. Vectors from different embedding models are not
comparable.

**Provider keys stop decrypting.**
The `KNOWLEDGEOS_ENCRYPTION_KEY` changed. Restore the original key (or the auth
secret it was derived from) and re-enter provider keys if necessary.

## Dependency notes

Backend packages are declared in `backend/requirements.txt`:

| Package | Used for |
| --- | --- |
| FastAPI | HTTP API, request validation, dependency injection, SSE responses |
| Uvicorn | ASGI server |
| python-multipart | Browser file-upload parsing |
| cryptography | Fernet encryption for provider API keys |
| pypdf | PDF text extraction |

Embeddings use the local [Ollama](https://ollama.com) runtime by default. Ollama
is a separate application, not a Python package. `all-minilm` is small and fast;
`bge-m3` and `nomic-embed-text` trade speed for retrieval quality.

Check the interpreter you plan to run:

```sh
python3 backend/check_dependencies.py
```

## Current scope and roadmap

The implementation covers text RAG, provider profiles, ingestion, semantic
cache, indexes, evaluation, feedback, and observability. Table extraction into a
SQL-queryable store, figure visual indexing, VLM captions, OCR for scanned
documents, and modality-aware multimodal answer generation remain future work.
