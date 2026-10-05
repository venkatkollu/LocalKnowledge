# Local setup and operations

1. Install Python 3.11+ and Ollama. Python 3.11/3.12 is recommended for optional
   sentence-transformers/PyTorch reranking.
2. Create `.venv`, activate it, and install `requirements.txt`.
3. Pull `nomic-embed-text` and `qwen3:4b`; start `ollama serve`.
4. Review `config.yaml`. Keep model endpoints on loopback and use one API worker.
5. Start `uvicorn app:app --host 127.0.0.1 --port 8000`, or `python run_local.py`.
6. Add files to `data/knowledge/`, queue `POST /documents/sync`, and poll the job.
7. Ask with `POST /chat` or the browser/terminal client. Inspect citations,
   decisions and traces, then run `python -m eval.run` against the fixture corpus.

For a no-model installation, set `KNOWLEDGEOS_OFFLINE=1` before startup. This
explicitly selects hash embeddings and extractive generation. A hash index stays
hash-based even after a model server starts; migrate the index to switch models.

For LM Studio, select its provider and exact model IDs in YAML or the supported
environment overrides. Automatic provider switching is intentionally unavailable
because it could mix embedding spaces. For token authentication, set
`KNOWLEDGEOS_API_TOKEN` for the terminal client and see [docs/API.md](docs/API.md).

## Migrating an existing database

Stop the original server and back up the database using SQLite's backup API or
an offline copy of the DB and its WAL. Set `KNOWLEDGEOS_DB` to the existing
database. Startup performs additive schema migration, retaining original tables.
Queue a sync to build the upgraded first index from source files. Legacy chunk
rows are retained for audit; retrieval uses the new `rag_members`/`rag_chunks`
tables. Do not delete the DB to change models.

For later model/chunk migrations use create → build → validate → evaluate →
activate. Keep the previous index for rollback. API examples and fields:
[docs/API.md](docs/API.md).

## Troubleshooting

| Symptom | Action |
|---|---|
| Hash embeddings despite running Ollama | Inspect `/indexes`; the initial fallback is pinned. Build/activate a new Ollama index. |
| Pinned embedding model unavailable (503) | Start the configured model server and ensure the original model/digest is present. Existing indexes never switch providers mid-query. |
| Parser/chunker runtime changed | Create/build a fresh index with the new registry fingerprint. Old indexes remain readable. |
| Empty or scanned PDF | Text extraction produced no content; preprocess with an OCR adapter outside this pipeline. |
| Job fails after restart | Inspect its error and resubmit. Completed document commits remain intact and are reused. |
| Queue is full (429) | Wait for jobs or increase the bounded queue only after measuring local resource use. |
| Answer abstains despite similar vectors | Inspect evidence decisions and citation verification; thresholds are conservative and require calibration on your corpus. |
| Cross-encoder cannot load | Use supported Python/PyTorch versions, install the optional requirements and provide a local model directory. |
| Uploaded document does not appear for another user | Private is the default. Its owner must grant same-tenant access or tenant visibility. |

## Verification

```bash
python -m pytest -q
KNOWLEDGEOS_OFFLINE=1 python -m eval.run
python -m eval.baseline --repeats 3
KNOWLEDGEOS_OFFLINE=1 python -m eval.run --repeats 3 \
  --baseline eval/reports/baseline.json --variants
```

See [README.md](README.md) for architecture/configuration and
[docs/BENCHMARKS.md](docs/BENCHMARKS.md) for measured results and limitations.
