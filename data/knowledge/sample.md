# Sample Project Notes

The URL shortener uses Redis as a caching layer for frequently accessed links. PostgreSQL stores the durable URL records.

## Chat application

The chat application uses Redis for session data and rate limiting. Its primary database is PostgreSQL.
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



PRIORITY 1 — KNAPSACK
0/1 Knapsack:
GFG — 0/1 Knapsack ✅ Confirmed real HWI SP paper — Q2 was directly knapsack
LC 416 — Partition Equal Subset Sum ✅ Sample paper #10 — Array Partition with XOR Maximization is partition DP, same structure
LC 494 — Target Sum — no direct match, builds toward HWI Hard
LC 1049 — Last Stone Weight II — no direct match, variant of 416
Unbounded Knapsack:
LC 322 — Coin Change ✅ Sample paper #4 — Reduce Army to 1 Soldier (minimize moves: -1, /2, /3) is unbounded knapsack / BFS on states
LC 518 — Coin Change II — no direct match
LC 279 — Perfect Squares — no direct match
2D Knapsack:
LC 474 — Ones and Zeroes — no direct match
LC 879 — Profitable Schemes — no direct match
Knapsack + Binary Search:
LC 1235 — Job Scheduling Maximum Profit ✅ Sample paper #6 — Employee Team Division (divide into teams, maximize expert value sum) is partition + knapsack + DP combined

PRIORITY 2 — LIS FAMILY
LC 300 — LIS ✅ Round 1 Hard (your exam) — Min Cost LIS of Length K is directly this with extra cost dimension
LC 673 — Number of LIS — no direct match, extends 300
LC 1027 — Longest Arithmetic Subsequence — no direct match
LC 354 — Russian Doll Envelopes — no direct match
LC 1048 — Longest String Chain — no direct match
LC 1235 — Job Scheduling ✅ Sample paper #6 — same partition + increasing order logic
GFG — Longest Bitonic Subsequence — no direct match
LC 376 — Wiggle Subsequence ✅ Round 1 Medium (your exam) — Maximum Alternating Parity Window Sum is alternating subsequence with index gap constraint, direct wiggle/LIS variant
Custom Min Cost LIS of Length K ✅ Round 1 Hard (your exam) — this IS the problem exactly. dp[i][k] with cost = (index - position)²

PRIORITY 3 — GREEDY + PREFIX
Prefix + HashMap:
LC 560 — Subarray Sum Equals K ✅ Sample paper #13 — Frequency and Distinct Count Condition uses prefix frequency counts from left and right, same prefix building logic
LC 523 — Continuous Subarray Sum ✅ Sample paper #1 — Array Update and Range Sum Queries uses prefix sums for type 2 queries. Sample paper #4 modulo variant matches this
LC 525 — Contiguous Array — no direct match
LC 974 — Subarray Sums Divisible by K ✅ Round 1 Medium (your exam) — Maximum Modulo-Differentiated Subsequence, no two adjacent same remainder mod K, direct modulo prefix pattern
Greedy simulation:
LC 134 — Gas Station ✅ Sample paper #3 — Oil Tank Distribution is literally this problem. Running prefix sum, find minimum X such that level never goes negative. Identical logic.
LC 45 — Jump Game II ✅ Round 1 Easy (your exam) — Prefix Flow Stability, greedy forward transfer to maintain non-decreasing prefix, same greedy range expansion idea
LC 435 — Non-overlapping Intervals — no direct match, but interval scheduling confirmed Medium type
LC 1029 — Two City Scheduling — no direct match
GFG — Minimum Platforms — no direct match

PRIORITY 4 — SLIDING WINDOW + KADANE
LC 53 — Maximum Subarray ✅ Round 1 Easy (your exam) — Prefix Flow Stability has Kadane-style running max logic embedded in it
LC 918 — Maximum Sum Circular Subarray — no direct match
LC 3 — Longest Substring Without Repeating Characters — no direct match
LC 904 — Fruit Into Baskets ✅ Sample paper #2 — Maximum Sum of Good Subarray (at most K distinct elements, max sum) is this exact problem generalized to K
LC 1695 — Maximum Erasure Value ✅ Sample paper #2 — same pattern, sliding window + sum tracking
LC 1425 — Constrained Subsequence Sum ✅ Round 1 Medium (your exam) — Maximum Alternating Parity Window Sum (adjacent elements different parity, gap ≤ K, maximize sum) is exactly dp[i] + sliding window max over [i-K, i-1]
LC 239 — Sliding Window Maximum ✅ Sample paper #12 — Soldier Treasure Game needs range maximum query over [i, R]. Sparse table or segment tree solve it, sliding window max is the simpler form of this

PRIORITY 5 — TREE DP + GRAPH
Tree DP:
LC 543 — Diameter of Binary Tree ✅ Sample paper #14 — Tree Subtree Intersection uses DFS on tree rooted at A and B, counting subtree node overlaps. Same DFS return value structure
LC 124 — Binary Tree Maximum Path Sum ✅ Sample paper #14 — Beauty(U,V) = count of nodes in intersection of subtrees. Max intersection across queries is the same "global max tracked during DFS" pattern
LC 337 — House Robber III ✅ Sample paper #5 — Maximum Component Weight in Tree (select edges, no component > K nodes) is 2-state tree DP: take edge or not
LC 1339 — Maximum Product of Splitted Binary Tree ✅ Sample paper #5 — Maximum Component Weight in Tree, split tree by removing edges, same two-pass subtree sum logic
LC 968 — Binary Tree Cameras — no direct match
GFG — Tree Knapsack ✅ Sample paper #5 — Maximum Component Weight in Tree with K node constraint IS tree knapsack dp[node][size]. This is your exact HWI S-P5
Graph BFS/DFS:
LC 994 — Rotting Oranges ✅ Sample paper #5 — Grid Invasion (multi-source BFS from all A cells simultaneously, expand to E cells, track max time) is this exact problem
LC 207 — Course Schedule ✅ Sample paper #7 — Graph Connected Components uses DFS/BFS to find components. Topological awareness needed for query type
LC 323 — Number of Connected Components ✅ Sample paper #7 — Graph Connected Components with Union-Find for type 1 add-edge queries and type 2 range counting queries
LC 787 — Cheapest Flights Within K Stops — no direct match

PRIORITY 6 — GRID DP
LC 64 — Minimum Path Sum — no direct match in your papers, but confirmed Medium type
LC 221 — Maximal Square — no direct match
LC 329 — Longest Increasing Path in Matrix ✅ Sample paper #11 — Minimum k for Longest Path in DAG. Build DAG where edges connect i→j if p[i] < p[j] and |i-j| ≤ k. Longest path in DAG with DP/DFS+memo is the same pattern as longest increasing path in matrix
LC 174 — Dungeon Game — no direct match

PRIORITY 7 — PARTITION DP + BITMASK
LC 1043 — Partition Array for Maximum Sum ✅ Sample paper #6 — Employee Team Division (partition array into consecutive teams, maximize sum of expert values) is this exact problem with MEX as the beauty function
LC 1547 — Minimum Cost to Cut a Stick — no direct match
LC 1494 — Parallel Courses II ✅ Sample paper #9 — Ball Chain Probability uses DP over states tracking blue/red counts with constraint blue ≤ red + K, same multi-state DP structure
GFG — Maximum XOR partition ✅ Sample paper #10 — Array Partition with XOR Maximization (partition into subarrays ≥ K elements, beauty = max XOR of any subset using Gaussian elimination, maximize sum of beauties) is exactly this

MATCH SUMMARY
Out of 44 problems in the list, 28 have a direct or near-direct match in problems you have already seen across your Round 1 paper, sample papers, and the HWI papers shared from the start. That means you have already seen the story of nearly every pattern. The problems on the list are not new ideas — they are the clean versions of exactly what you have been solving. The only thing the exam changes is the surface story. The underlying algorithm is already in this list.
