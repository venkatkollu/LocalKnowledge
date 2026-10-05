# Measured benchmark and verification results

## Run and environment

```bash
KNOWLEDGEOS_TMP=/tmp/omnirush python -m pytest -q --basetemp=/tmp/omnirush/pytest
python -m eval.baseline --repeats 3
KNOWLEDGEOS_OFFLINE=1 python -m eval.run \
  --baseline eval/reports/baseline.json --variants --repeats 3
```

Development environment: Python **3.14.4**, Linux/WSL2 x86-64, 8 logical CPUs.
Measured reports are checked in as `eval/reports/baseline.json` and
`eval/reports/after.json`. The baseline executes source from original commit
`360d5de` using deterministic original hash embeddings and extractive fallback;
the upgrade uses `local-hash-v2`, structure contextualization, heuristic reranking
and `local-extractive-v2`. Neither Ollama nor LM Studio was available.

Corpus: **6 source files, 1,423 bytes, 16 upgraded chunks**. Python bytecode/cache
artifacts are excluded. Corpus SHA-256:
`7494ab1cfd3b0af7c8ad4f899cf6f1f8f5a8bc50771990de3d31e9696c1c9670`.

There are **15 unique cases**: 8 golden, 2 regression, 2 unanswerable,
2 injection and 1 adversarial. Three repeats produce 45 observations, including
30 answerable retrieval/generation observations and 15 negative observations.
Repeats measure latency variability, not additional independent QA examples.

## Before / after

| Metric | Original | Upgraded |
|---|---:|---:|
| Recall@5 | 100% | 100% |
| Recall@10 | 100% | 100% |
| Recall@20 | 100% | 100% |
| MRR | 1.000 | 1.000 |
| NDCG@10 | 1.000 | 1.000 |
| Answer-term relevance | 100% | 100% |
| Citation accuracy (lexical support proxy) | 0% | 100% |
| Abstention accuracy (all cases) | 66.7% | 100% |
| Semantic faithfulness | **Not measured** | **Not measured** |
| p50 chat pipeline latency | 2.99 ms | 8.80 ms |
| p95 chat pipeline latency | 4.12 ms | 13.71 ms |
| p99 chat pipeline latency | 4.72 ms | 15.46 ms |

**Latency regression:** p95 increased by about 3.33×, or 9.59 ms absolute. The
runner records `p95 latency increased by more than 50%`; it is not hidden or
presented as a performance improvement. ACL-scoped reads, structured evidence,
parent reads, verification, registry metadata and persisted traces add work.
The earlier offline code-excerpt relevance regression was fixed by retaining
the bounded function body on symbol-specific queries and excluding unrelated
code contexts. Its final relevance score matches the baseline.

Retrieval was already saturated on this extremely small corpus. Perfect metrics
here **do not demonstrate semantic-retrieval improvement**, general QA quality,
multi-hop capability or resistance to novel attacks. Original retrieval and
generation were not tested with neural models; no Qwen quality comparison is
claimed.

## Additional upgraded metrics

| Metric | Measured value |
|---|---:|
| Precision@5 | 22% |
| Precision@10 | 11% |
| Precision@20 | 5.5% |
| Citation recall (supported cited claims / final claims) | 100% |
| Citation coverage | 100% |
| Unsupported final claim rate (lexical/numeric/negation proxy) | 0% |
| Lexical faithfulness proxy | 100% |
| Unanswerable/injection/adversarial cases correctly abstained | 15 / 15 observations (5 / 5 unique cases) |
| Retrieval p50 / p95 | 4.82 / 7.20 ms |
| Reranking p50 / p95 | 0.57 / 0.80 ms |
| Generation + final verification p50 / p95 | 0.17 / 0.44 ms |
| LLM tokens per request | 0 (offline extraction) |

### Definitions and boundaries

- Retrieval is **document-level**: exact filename identity, deduplicated
  rankings, recall against the full labelled relevant-source set, full-ranking
  MRR and binary-relevance NDCG. Precision@K uses K as denominator even if fewer
  than K distinct documents exist. Retrieval averages exclude unanswerable
  cases, which have no relevant-source labels.
- Answer relevance is coverage of annotated expected answer terms, not an LLM
  judge. It cannot penalize every irrelevant but grounded sentence.
- Citation accuracy verifies actual returned references against cited source
  text using the shared lexical/numeric/negation checker. Missing inline
  references in factual answers count as zero. Generation support metrics are
  computed only for non-abstained final answers; abstention accuracy separately
  catches false abstention and false answering.
- `faithfulness` is **null** because semantic entailment/human review was not
  measured. `faithfulness_proxy` is separately labelled. No model-quality
  number is substituted for missing semantic evaluation.
- Context relevance is available as a retrieval Precision@5 proxy, not a
  semantic judgment of actual generation context.
- Latency measures the direct chat pipeline call including trace persistence;
  the separate retrieval-metric call is outside its timer. It excludes network
  transport, HTTP serialization, model loading and real inference. Percentiles
  over 45 tiny observations are not a deployment SLA.
- The original chat used its existing top-12 cap; the upgrade uses top-6,
  filtered/expanded generation context. Each retained answer is scored against
  its own supplied sources. Retrieval measurement uses top-20 for both.

## Resources

| Measurement | Value |
|---|---:|
| Sampled peak process RSS (one sample after each request) | 54.51 MiB |
| Final process RSS | 54.53 MiB |
| Process CPU time for ingestion + benchmark | 0.752 s |
| Ingestion wall time | 26.91 ms |
| SQLite DB size after run | 364,544 bytes |
| Source corpus size | 1,423 bytes |
| GPU memory/utilization | Not measured; CPU-only offline pipeline |

The OS-reported `ru_maxrss` was 659.66 MiB in this harness. A separate fresh
Python process reported the same high-water value before app imports while its
current RSS was 11.57 MiB. Accordingly the inherited/reported high-water value
is retained as raw metadata, **not interpreted as application peak allocation**.
Sampled RSS can miss short-lived peaks. SQLite size includes retained chunks,
versions and traces, and grows with history; this tiny fixture is not a disk
scaling estimate. Model-server RAM/VRAM and energy use were not measured.

## Tests and live API smoke check

**27 tests passed**. The original suite had 3 passing smoke tests. Current tests
cover hashing, heading attribution/raw retention, PDF page provenance, Python
symbols/locations, RRF, vector validation, citations, abstention/conflicts,
incremental reuse, schema preservation, registry, migrations and rollback,
staged jobs/restart recovery, Git incremental/deletion behavior and golden QA.

Security checks passed for:

- Missing/invalid identity handling and rejected identity overrides.
- Unauthorized documents excluded before vector loading/scoring and BM25 limits.
- Same user name in a different tenant unable to retrieve private evidence.
- Scoped document versions, jobs, traces and ACL mutation.
- Same-tenant explicit grants and cross-tenant grant rejection.
- Direct injection abstention and indirect malicious-document quarantine.
- Generated citation `[999]` rejected and unsupported text replaced before output.
- Wrong numeric claims, missing citations, negation and weak support rejected.
- Remote local-mode peers, cross-origin browser requests and DNS-rebinding Host
  patterns rejected.
- No query/document content in new trace payloads.

A live Uvicorn HTTP run also passed: six fixture documents were indexed,
`/chat` returned `The cache expiry is 300 seconds [1].`, the trace endpoint was
readable by the local principal, and an attacker Origin received 403.
Python compilation and `git diff --check` passed. Existing FastAPI/Starlette
dependencies emit Python 3.14 deprecation warnings; no test failures resulted.
Cross-encoder inference and live Qwen attack behavior were not exercised.

## Expansion / HyDE ablations

The runner supports baseline, expansion, HyDE and expansion+HyDE comparison.
Functional tests prove variant fusion, trace accounting and that hypothetical
text cannot become evidence. **Quality/latency ablations are unmeasured** here:
offline mode records that a running local generator is required. Neither
variant is enabled by default or assumed to improve quality.

## Final classification

**Production-Oriented Research System.** The system has local deployability,
replaceable components, source-aware indexing, security boundaries, explicit
index lifecycle, tests and reproducible measurements. Production-ready status
would require larger independent benchmarks, real-model/scale/concurrency
testing, stronger semantic verification, operational retention/backup policy
and deeper adversarial coverage. This upgrade makes those gaps measurable
rather than concealing them behind feature claims.
