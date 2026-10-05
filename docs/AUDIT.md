# Source audit — original commit `360d5de`

Inspected every tracked file, including the 522-line `app.py`, tests, terminal
client, UI, dependencies and sample corpus. README statements were checked
against executable paths. Original checks: **3 tests passed** (Python 3.14.4).
Neither local model server was available. No original golden benchmark exists.

| Feature | Exists | Partial | Missing | Verified quality / weakness |
|---|:---:|:---:|:---:|---|
| SHA-256 ingestion | ✓ | | | Document skip and chunk reuse exist; pipeline/model changes do not invalidate reuse |
| Async jobs | | ✓ | | Thread-pool scan, persisted counters; upload blocks, no stage states/restart recovery, failed batch marked completed |
| BM25 | ✓ | | | SQLite FTS5; current FTS entries only, no metadata/ACL filtering |
| Dense retrieval | | ✓ | | JSON cosine scan; queries **all historical versions**, ignores model identity/dimension; zip silently truncates dimensions |
| Hybrid retrieval | ✓ | | | Real RRF (k=60), fixed 40/30 pools, no filters or tuning |
| Reranking | | ✓ | | Token overlap/cosine heuristic, **not** a cross-encoder; fixed weights |
| Versioning | | ✓ | | Version rows and old chunks retained; parser/chunker hard-coded 1.0; no reproducible index snapshot or rollback |
| Citations | | ✓ | | Prompt requests [n], API returns all retrieved sources whether cited or sent; no validation; fallback has no inline citations |
| Abstention | | ✓ | | Only empty evidence; dense top-k normally returns unrelated evidence |
| Prompt injection defense | | ✓ | | One system sentence and delimiters; no isolation checks, malicious-content screening, ACL or adversarial tests |
| Evaluation | | ✓ | | Hit-rate called recall, substring filename matching, MRR truncated at 5; one-question smoke test |
| Observability | | ✓ | | Query text stored by default, basic timing/count aggregates; no stage spans, tokens, evidence/error decisions |

## Additional findings

- Paragraph heading attribution can incorrectly label the preceding chunk with
  the next section. PDFs lose page boundaries. Code has no AST/symbol metadata.
- `UNIQUE(version_id, chunk_hash)` rejects repeated identical chunks.
- Embedding HTTP calls happen inside a long database transaction; runtime
  fallback can create mixed embedding spaces within a version.
- File scan deletion is global: documents outside the scan root can be removed.
- Unauthenticated filenames and excerpts reach UI `innerHTML` (stored XSS).
- Upload buffers the entire file, overwrites same-named files, and has no limit.
- Legacy schema handling copies then drops tables; no non-destructive migration.
- Jobs are not durable workers; process exit leaves running jobs unrecovered.
- Everything resides in one module. There is no duplicate retrieval framework;
  retain SQLite, FTS5, hashing, RRF and the two local HTTP adapters.
- `sample.md` contains personal notes and copied instructions; preserve it and
  use a separate synthetic corpus for reproducible evaluation.

## Implementation decisions

Retain the existing API/terminal/UI entry points and local storage. Extract
replaceable components, add additive schema migrations and index memberships,
pin embedding spaces, then add structured/contextual chunks, configurable RRF
and reranking, bounded parents, optional expansion/HyDE, Python AST parsing,
fail-closed citation/evidence decisions, ACL filtering in SQL, stage traces,
index validation/activation/rollback and staged asynchronous ingestion.

Use a checked-in synthetic benchmark, including unanswerable, adversarial,
injection and regression examples. Run the **original commit** against the same
corpus for the before/after comparison. Offline results are explicitly labelled
hash embeddings + extractive generation; they are not Qwen quality estimates.
Optional graph, image and agentic systems are deferred until real-model
evaluation supports their cost.
