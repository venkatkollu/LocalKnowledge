# API and operations

OpenAPI schemas are served at `/docs` and `/openapi.json`.
Default base URL: `http://127.0.0.1:8000`.

## Identity and ACL

`local` mode accepts only loopback clients with loopback Host headers and
same-origin browser requests. It uses the `local/local` principal with admin
rights. `token` mode requires `Authorization: Bearer TOKEN` on all data/API
endpoints (the static page contains no knowledge data).

The local credentials file is a JSON object keyed by SHA-256 token digest:

```json
{
  "REPLACE_WITH_64_CHARACTER_SHA256_HEX_DIGEST": {
    "tenant_id": "team-a",
    "owner_id": "alice",
    "permissions": ["admin"]
  },
  "REPLACE_WITH_BOBS_TOKEN_DIGEST": {
    "tenant_id": "team-a",
    "owner_id": "bob",
    "permissions": []
  }
}
```

Generate high-entropy tokens with `python -c 'import secrets; print(secrets.token_urlsafe(32))'`
and compute their digests using Python `hashlib.sha256(token.encode()).hexdigest()`.
Store the mapping outside tracked code, protect it with filesystem permissions,
then configure:

```yaml
security:
  auth_mode: token
  credentials_file: /absolute/private/path/credentials.json
```

Restart to load changed credentials. All tenant/owner identities come from the
token, not `X-Tenant-ID`, `X-Owner-ID`, or query JSON. Optional identity fields
in query JSON are assertions; a mismatch is rejected (403).

Visibility is `private`, `tenant` or `public`; all modes remain tenant-bound.
Private access requires the owner or a user ID in the document's `permissions`
list. These document grants differ from principal role permissions (`admin`).
An administrator can manage global index operations and local/Git source
ingestion; it does not bypass retrieval's tenant/owner ACL. Token mode does not
automatically ingest the local folder as an anonymous startup principal.

The terminal client reads `KNOWLEDGEOS_API_TOKEN`. In the browser, set
`sessionStorage.setItem('knowledgeos-token', 'YOUR_TOKEN')` and reload. TLS/
identity-provider integration is not included; loopback deployment is the default.

## Endpoints

| Method/path | Access | Behavior |
|---|---|---|
| `GET /health` | principal | Scoped document/chunk/job counts and configured model/index identity |
| `GET /documents` | principal | Authorized document metadata |
| `GET /documents/{id}/versions` | document reader | Retained version and pipeline history |
| `PATCH /documents/{id}/acl` | owner / same-tenant authorized admin | Update visibility and explicit user grants |
| `POST /documents` | principal | Multipart streamed upload; **202 + job ID** |
| `POST /documents/index` | principal | Compatibility upload path; now **202 + job ID**, not a blocking index result |
| `POST /documents/sync` | admin | Queue local configured-folder sync |
| `GET /jobs/{id}` | job owner | State, stage history, counts, summary and errors |
| `GET /changes/latest` | principal | Latest owned job summary |
| `POST /search` | principal | Filtered dense/BM25 → RRF → reranking, with trace ID |
| `POST /chat` | principal | Evidence-gated answer, verification, decision, citations, registry and trace |
| `GET /traces/{id}` | trace owner | Content-free stage spans |
| `GET /metrics` | principal | Scoped latest-1000 trace percentiles, errors/abstentions and job totals |
| `GET /indexes` | admin | Full index registry/configuration snapshots |
| `POST /indexes` | admin | Create independent migration index, **201** |
| `POST /indexes/{id}/build` | admin | Queue build of all registered non-deleted documents, **202** |
| `POST /indexes/{id}/validate` | admin | Model/dimension/parser/FTS/membership/completeness integrity checks |
| `POST /indexes/{id}/activate` | admin | Validate then atomically switch active index |
| `POST /indexes/{id}/rollback` | admin | Reactivate preserved prior index |
| `POST /repositories/git` | admin | Incremental tracked local checkout / explicit HTTPS repository ingestion, **202** |
| `POST /evaluation/run` | principal | Evaluate supplied QA cases against authorized data/index |
| `GET /evaluation/results` | evaluation owner | Persisted evaluation payloads |

Unauthorized resource IDs return 404. Missing/invalid tokens return 401, role or
identity violations 403, oversized uploads 413, full queues 429, and unavailable
pinned embedding models or rapidly changing index membership 503.

## Upload and job states

```bash
curl -X POST http://127.0.0.1:8000/documents \
  -H "Authorization: Bearer $TOKEN" -F 'file=@notes.md'
curl http://127.0.0.1:8000/jobs/JOB_ID -H "Authorization: Bearer $TOKEN"
```

```text
queued → processing → parsing → structure_extraction → chunking
       → contextualizing → embedding → indexing → validating → completed
       └────────────────────────────────────────────────────────→ failed
```

Stages are persisted with timestamps, plus `total`, `completed`, `failed`,
`started_at`, `finished_at`, `error` and a change/embedding-reuse summary. Files
commit atomically; a failed update preserves previously searchable evidence.
Batch failure does not stop remaining files and causes a failed final job state.
Unclean restarts mark unfinished jobs failed for explicit resubmission. Uploads
are limited to 20 MiB by default and stored in principal-isolated unique paths.

## Queries

```json
{
  "query": "How does JWTService.validate reject empty tokens?",
  "top_k": 6,
  "filters": {"language": "python", "symbol": "JWTService.validate"},
  "index_id": null,
  "query_expansion": false,
  "hyde": false
}
```

`top_k`: 1–20 (also bounded by configured `rerank_k`). Supported exact filters:
`filename`, `repository`, `language`, `symbol`, `section`. `index_id` optionally
targets a preserved/building index for evaluation; ACL always applies.
Null expansion/HyDE fields use YAML defaults. Expansion is word-count gated;
HyDE is an explicit option. Alternatives/hypotheticals are search inputs, never
citable evidence.

Chat returns `answer`, `model`, `abstained`, `decision`, `verification`,
`citations`, `stats`, `trace_id`, `request_id`, `index_version` and `registry`.
Citations include real chunk/parent/document-version provenance, PDF pages or
line ranges, section, symbol, path and an excerpt. Only references actually used
in a checked answer are returned. Abstentions have no citations.

`verification.method` states the lexical/numeric/negation limitation. Rejected
LLM claims are available under `verification.rejected_generation`; their text
is replaced by checked extraction or abstention before the final answer.

## Migration and rollback example

```bash
curl -X POST http://127.0.0.1:8000/indexes \
  -H 'Content-Type: application/json' \
  -d '{"name":"nomic-v2","embeddings":{"provider":"ollama","model":"nomic-embed-text","allow_initial_hash_fallback":false},"chunk_size":1000,"chunk_overlap":120}'
# Record id from the response as NEW_INDEX and existing active id as OLD_INDEX.
curl -X POST http://127.0.0.1:8000/indexes/NEW_INDEX/build
curl http://127.0.0.1:8000/jobs/JOB_ID
curl -X POST http://127.0.0.1:8000/indexes/NEW_INDEX/validate
curl -X POST http://127.0.0.1:8000/evaluation/run \
  -H 'Content-Type: application/json' \
  -d '{"index_id":"NEW_INDEX","questions":[{"question":"What caches responses?","expected_sources":["notes.md"],"answer_terms":["Redis"]}]}'
curl -X POST http://127.0.0.1:8000/indexes/NEW_INDEX/activate
curl -X POST http://127.0.0.1:8000/indexes/OLD_INDEX/rollback
```

Add bearer headers in token mode. Building reads uploaded/Git files as well as
registered local-folder documents. Incomplete or running builds cannot pass
validation; retired indexes cannot ingest until explicitly reactivated. Integrity
validation is not a quality benchmark: inspect retrieval/grounding/latency results
before activation. Old indexes and chunks remain in SQLite. ACL updates are live
across all index versions, so rollback does not restore revoked permissions.

Registry fields include parser/chunker/contextualizer versions, embedding
provider/model/dimension/revision, reranker/generator identity, index revision,
configuration hash and exact evidence manifests. Mutable active memberships
increment the revision; querying retries once if dense/sparse reads straddle a
document commit. Stored manifests support audit/replay of the specific evidence.
