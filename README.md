# Local KnowledgeOS — Privacy-Preserving RAG

A local-first, versioned, citation-checked retrieval system for documents, notes,
PDF text and Python code. FastAPI, SQLite/FTS5 and Ollama remain the default
stack. No hosted API, cloud database or orchestration platform is required.

**Assessment: Production-Oriented Research System.** The core pipeline has
integration, security and regression coverage, but its small synthetic benchmark
and conservative lexical verifier do not establish production readiness or
neural-model quality. See [measured results](docs/BENCHMARKS.md) and
[source audit](docs/AUDIT.md).

## Architecture

```text
 Files / upload / optional Git checkout
          │
          ▼
 Bounded ingestion queue → parse → structure → child chunks
          │                         │              │
          │                    parent sections     ▼
          │                           contextual description (optional LLM)
          │                                        │
          └──────────→ SQLite versions + raw/contextual chunks + vectors + FTS5
                                                   │
 FastAPI → authenticated principal → query analysis │
                 │                                 │
                 ├── optional query expansion / HyDE (search input ONLY)
                 ▼
      ACL + metadata WHERE predicates in both retrievers
                 │
        dense top 50 + BM25 top 50
                 │
       weighted RRF → up to 100 candidates
                 │
     local heuristic / optional cross-encoder → up to 20
                 │
       bounded parent expansion + extractive compression
                 │
     evidence decision → Qwen/Ollama or extractive fallback
                 │
      claim / citation / number / negation validation
                 │
          checked answer / uncertainty / abstain

 Every query: scoped trace + stage timing + model/index/evidence manifest
 Index lifecycle: create → build → validate → evaluate → activate ↔ rollback
```

The original monolithic `app.py` is now an `app/` package; the existing
`uvicorn app:app` and `python run_local.py` commands still work. Interfaces in
`app/interfaces.py` define `EmbeddingModel`, `Reranker`, `VectorStore`,
`SparseRetriever`, `Generator`, `Parser` and `Chunker`. SQLite is the implemented
storage adapter; Qdrant/pgvector are future adapters.

## Existing versus improved

| Feature | Verified original implementation | Upgrade |
|---|---|---|
| Ingestion | SHA-256 skips/reuse, thread-pool scan | Pipeline-aware embedding reuse, bounded staged jobs, atomic commits, streamed size-limited uploads, incremental Git |
| Chunking | Paragraph/character chunks, imperfect headings | Structure boundaries, Python AST symbols/imports/lines, PDF pages, raw + contextual text, parents |
| Retrieval | FTS5 BM25, linear cosine, fixed RRF | Current-index memberships, model/dimension/digest pinning, SQL ACL/metadata filters, configurable weighted RRF, expansion/HyDE options |
| Reranking | Fixed token/cosine heuristic | Replaceable local heuristic and optional local-only cross-encoder adapter |
| Generation | LM Studio/Ollama + uncited extraction | Ollama default, retained LM Studio adapter, checked cited extraction, evidence-gated generation |
| Citations | Prompt instruction, all retrieved sources returned | Claim-level real-ID checks, numeric/negation checks, only used verified citations, parent/page/line provenance |
| Abstention | Empty results only | Query coverage, dense/reranker signals, independent support, agreement, explicit conflicts, citation/claim validation |
| Evaluation | One smoke question, hit-rate labelled recall, truncated MRR | Exact deduplicated source metrics, Recall@5/10/20, full MRR, NDCG@10, Precision@K, generation proxies, percentiles, before/after reports |
| Security | System prompt sentence | Authenticated identity, pre-scoring ACL, tenant-bound grants, instruction screening, untrusted JSON evidence, XSS-safe UI, scoped jobs/traces/history |
| Observability | Query text and two timing fields | Content-free request traces, stage spans, token counts, scores, context size, errors, abstentions, scoped aggregates |
| Version/index lifecycle | Hard-coded parser/chunker labels | Config snapshots, model registry, embedding digest where available, revisions/evidence manifests, additive migration, validate/activate/rollback |

## Install and start

Python **3.11+**. Python 3.11/3.12 is recommended for optional PyTorch-based
cross-encoders. Core tests were also run on Python 3.14.4.

```bash
git clone https://github.com/venkatkollu/LocalKnowledge.git
cd LocalKnowledge
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt

ollama pull nomic-embed-text
ollama pull qwen3:4b
ollama serve
```

In another terminal:

```bash
source .venv/bin/activate
uvicorn app:app --host 127.0.0.1 --port 8000
# Or use the terminal client:
python run_local.py
```

Use one API process/worker. Open `http://127.0.0.1:8000`, with OpenAPI at `/docs`.
CPU/RAM inference works; a GPU is optional. A 4B generation model and its context
cache require several GB of RAM; actual model memory/latency must be measured on
your machine. Larger Qwen models can be configured if resources permit.

To run entirely offline without model servers:

```bash
KNOWLEDGEOS_OFFLINE=1 uvicorn app:app --host 127.0.0.1 --port 8000
```

This selects **hash embeddings + cited extractive answers**, not neural semantic
retrieval or Qwen. On first-index creation a missing embedding server may select
the same fallback if allowed. The index then stays pinned to hash embeddings.
Starting Ollama later requires creating/building/activating a new index; provider
failures never silently mix vector spaces in an existing index.

LM Studio remains supported: configure its loopback URL, generation model and
embedding model in YAML, or set `LLM_PROVIDER=lmstudio` and the matching
`LMSTUDIO_MODEL` / `LMSTUDIO_EMBED_MODEL`. Cross-provider `auto` mode was removed
in favor of explicit, reproducible provider selection.

## Ingest and query

Place trusted-to-index files in `data/knowledge/`, or set
`KNOWLEDGEOS_KNOWLEDGE`. The checked-in personal sample is preserved. Startup
sync is asynchronous in single-user local mode.

```bash
curl -X POST http://127.0.0.1:8000/documents/sync
curl -X POST http://127.0.0.1:8000/documents -F 'file=@notes.md'
curl http://127.0.0.1:8000/jobs/JOB_ID

curl -X POST http://127.0.0.1:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"query":"What is used for caching?","top_k":6}'

curl -X POST http://127.0.0.1:8000/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"JWTService.validate","filters":{"language":"python","symbol":"JWTService.validate"}}'
```

Each upload creates an isolated file/document rather than overwriting another
user's same-named file. Local filesystem sync detects changed bytes and creates
a new document version, reusing matching contextual embeddings only when the
pipeline/model fingerprint agrees. Empty/scanned PDFs fail with an actionable
error; PDF text pages retain page provenance. Python is parsed using `ast`;
other languages currently use the generic text parser.

Optional Git ingestion accepts an existing local checkout or an explicit HTTPS
URL. It reads tracked files, rejects symlinks, hashes changed content, records
the commit, and removes deleted files from the selected index. HTTPS cloning is
the only feature here that deliberately contacts a remote Git server.

```bash
curl -X POST http://127.0.0.1:8000/repositories/git \
  -H 'Content-Type: application/json' \
  -d '{"repository":"/absolute/path/to/local/checkout"}'
```

## Configuration

The complete configuration is [config.yaml](config.yaml). Set
`KNOWLEDGEOS_CONFIG=/path/to/config.local.yaml` to use a different file.

```yaml
embeddings:
  provider: ollama
  model: nomic-embed-text
  allow_initial_hash_fallback: true
retrieval:
  contextual_chunking:
    enabled: true
    mode: structure # llm is an optional local-model contextualizer
    model: qwen3:4b
  dense_k: 50
  sparse_k: 50
  candidate_k: 100
  rerank_k: 20
  rrf_k: 60
  dense_weight: 1.0
  sparse_weight: 1.0
  parent_expansion: true
  parent_max_chars: 2400
  max_context_chars: 10000
reranker:
  provider: heuristic
query:
  expansion: {enabled: false, num_queries: 3, min_query_words: 6}
  hyde: false
generation:
  provider: ollama
  model: qwen3:4b
security:
  auth_mode: local
  credentials_file: null
evidence:
  min_query_coverage: 0.25
  min_dense_score: 0.2
  min_claim_support: 0.8
```

Optional cross-encoder: install `requirements-reranker.txt`, provision weights
on disk, then set `reranker.provider: cross_encoder`, `model_path` to that local
directory, and `model` to the recorded model identity. Runtime uses
`local_files_only=True`; no automatic model download occurs. Its scores are
model-specific, not calibrated confidence probabilities.

Environment paths: `KNOWLEDGEOS_DATA`, `KNOWLEDGEOS_DB`,
`KNOWLEDGEOS_KNOWLEDGE`. Model overrides: `OLLAMA_URL`, `OLLAMA_MODEL`,
`EMBED_MODEL`, `EMBED_DIM`, `LMSTUDIO_URL`, `LLM_PROVIDER`. Startup sync:
`KNOWLEDGEOS_AUTO_SYNC=0`. Model URLs must be loopback HTTP URLs.

## Access control and security

Default `local` mode is one loopback-only principal with administrator rights.
It rejects non-loopback clients, suspicious Host headers, and cross-origin
browser requests. This is not a multi-user identity mode.

For multiple users, choose `security.auth_mode: token` and configure a local
credentials file mapping **SHA-256 bearer-token digests** to tenant/user/role
records. Tenant/user headers and body fields cannot impersonate a credential.
Private documents require owner or explicit same-tenant grants; `tenant` and
`public` visibility are both confined to the authenticated tenant. See the full
[authentication and API guide](docs/API.md).

Authorization runs inside both retrievers' SQL predicates before candidate
limits, vector loading/scoring and reranking. Parent expansion and metadata,
versions, job, trace and evaluation endpoints are also scoped. Documents are
JSON-encoded **untrusted data**, not instructions. Known instruction attacks are
quarantined; generated claims are checked against actual supplied evidence.
There are no generated tool calls or exfiltration actions.

**Boundaries:** instruction screening is heuristic; the verifier is lexical,
numeric and negation-aware, not semantic entailment. Explicit subject/value
conflict detection is limited. Paraphrases can be rejected and sophisticated
injections can evade pattern screening. These limitations are why the project
does not claim general hallucination prevention or attack-proof operation.

## Evaluation and regression

```bash
python -m pytest -q
python -m eval.run                       # configured local model stack
KNOWLEDGEOS_OFFLINE=1 python -m eval.run  # deterministic offline benchmark

python -m eval.baseline --repeats 3       # execute original commit 360d5de
KNOWLEDGEOS_OFFLINE=1 python -m eval.run \
  --baseline eval/reports/baseline.json --variants --repeats 3
```

`--variants` compares baseline, expansion, HyDE and both when a local generator
is configured. Offline mode explicitly records those variants as unmeasured.
`--fail-on-regression` exits nonzero for reported quality declines or a >50%
p95 latency increase. Compare against a previous report from the same corpus
and machine; latency percentiles from 15 cases are smoke measurements, not an
SLA. Benchmarks use an isolated temporary database and leave your index intact.

Datasets live in `eval/{golden,regression,unanswerable,injection,adversarial}/`.
The benchmark reports exact source Recall@5/10/20, full MRR, NDCG@10,
Precision@K, annotated answer-term relevance, lexical grounding/citation
proxies, abstention accuracy, p50/p95/p99, stage timings, tokens, CPU, RSS and
disk. Semantic faithfulness is `null` until a human/entailment evaluator is
supplied; it is never replaced by a fabricated model-quality percentage.

Latest measured results and all methodology details are in
[docs/BENCHMARKS.md](docs/BENCHMARKS.md) and `eval/reports/after.json`.

| Offline fixture metric | Original | Upgraded |
|---|---:|---:|
| Recall@5 / Recall@10 | 100% / 100% | 100% / 100% |
| MRR / NDCG@10 | 1.00 / 1.00 | 1.00 / 1.00 |
| Citation accuracy (lexical proxy) | 0% | 100% |
| Abstention accuracy | 66.7% | 100% |
| Semantic faithfulness | Not measured | Not measured |
| p50 / p95 pipeline latency | 2.99 / 4.12 ms | 8.80 / 13.71 ms |

This is **6 files and 15 unique synthetic cases**, repeated three times, using
hash embeddings and extractive generation. Retrieval is saturated; no semantic
retrieval gain is demonstrated. The p95 latency regression is explicitly
reported. Sampled process RSS was approximately 54.5 MiB; Qwen/model-server
resources were not measured.

## Index migrations and observability

Create a new index with explicit embedding/chunk settings, queue its build,
validate completeness/dimensions/parser/sparse consistency, evaluate with its
`index_id`, then activate it. Rollback reactivates a preserved prior index.
Active indexes have membership revisions; responses also record exact chunk,
version, pipeline and context hashes. Ollama embedding digests are pinned when
available; LM Studio does not expose equivalent revision information here.
Registry/configuration tracking does not promise bit-identical model inference.

The schema migration is additive: original document/version/chunk tables remain
intact. A new index rebuilds original files into the upgraded pipeline; no
database deletion is required. Archived chunks/indexes currently require a
manual retention policy and can grow over time.

`GET /traces/{trace_id}` exposes stage spans and `GET /metrics` exposes scoped
latency/error/abstention aggregates. Traces use OTel-shaped identifiers and
attributes; an OpenTelemetry exporter is not installed. Queries, document text
and generated answers are not persisted in new trace logs. Old query logs in
an existing database are retained by migration.

## Project files

```text
app/
  api.py              FastAPI routes, authentication dependencies and wiring
  config.py           validated YAML/environment settings
  interfaces.py       component protocols
  parsing.py          headings, PDF pages, Python AST adapter
  chunking.py         bounded structure chunks + contextualization
  ingestion.py        atomic ingestion and model-safe reuse
  embeddings.py       pinned Ollama/LM Studio/hash adapters
  retrieval.py        RRF, optional query variants, bounded context
  reranking.py        heuristic and optional local cross-encoder
  generation.py       local model HTTP adapter
  citations.py        claim/citation support checking and provenance
  evidence.py         evidence decisions, conflicts, safe answer pipeline
  auth.py / security.py  identity, ACL SQL and attack screening
  storage.py          additive SQLite schema and index lifecycle
  jobs.py             bounded worker queue, persisted stages/restart recovery
  repositories.py     incremental local/HTTPS Git ingestion
  evaluation.py       shared before/after benchmark scorer
  observability.py    content-free request spans
eval/                  synthetic corpus, QA sets, runner and measured reports
tests/                 unit, integration, security, migration and golden QA
docs/                  audit, API/operations, benchmark results
```

## Limitations and future work

- Linear JSON-vector search is appropriate for small local corpora; large
  corpora need a benchmarked ANN storage adapter.
- One process is the supported deployment. Jobs have bounded in-process workers
  and persisted progress; interrupted jobs are marked failed and resubmitted,
  not automatically replayed by a distributed queue.
- A lexical verifier and a tiny synthetic dataset cannot establish general
  reasoning, temporal correctness, multi-hop grounding or deployment security.
- Real Ollama/Qwen, local cross-encoder, expensive contextualization and
  expansion/HyDE quality/latency were not measured in the development environment.
- UTF-8 text/code and text PDFs are supported; OCR/images/tables and Java AST
  parsing remain future parser adapters.
- Filesystem changes during reads, model runtime versions, and mutable model
  tags without revision metadata constrain exact reproduction.
- Next steps: larger independently labelled corpus, semantic entailment or
  human faithfulness review, real-model ablations, corpus-scale load tests,
  retention/backup tooling and a tested ANN adapter. Graph, multimodal and
  agentic retrieval should be added only after those evaluations justify them.
