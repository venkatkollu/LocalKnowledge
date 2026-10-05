from __future__ import annotations

from contextlib import asynccontextmanager
import json
from pathlib import Path
import time
import uuid

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import httpx

from app.auth import Authenticator
from app.citations import citation_records
from app.chunking import sha256
from app.config import ROOT, Settings
from app.evaluation import run_benchmark
from app.evidence import AnswerPipeline
from app.generation import LocalGenerator
from app.ingestion import Ingestor
from app.jobs import JobManager, QueueFull
from app.observability import Trace
from app.parsing import SUPPORTED
from app.retrieval import QueryPipeline
from app.security import Principal, acl_clause
from app.storage import SQLiteStorage

SETTINGS = Settings.load()
storage = SQLiteStorage(SETTINGS)
ingestor = Ingestor(SETTINGS, storage)
jobs = JobManager(SETTINGS, storage)
authenticator = Authenticator(SETTINGS)
generator = LocalGenerator(SETTINGS)
pipeline = QueryPipeline(SETTINGS, storage, generator)
answers = AnswerPipeline(SETTINGS, generator)


def init_db():
    storage.initialize()


def active_index():
    # Read an established index without waiting on long-running ingestion.
    index = storage.active_index()
    if index:
        return index
    with ingestor.lock:
        index = storage.active_index()
        if index:
            return index
        if storage.indexes():
            raise HTTPException(503, "No active index; validate and activate an index")
        index = storage.create_index("index-v1")
        # Bootstrap the first empty index only. Migration activation requires
        # non-empty structural validation and an explicit operator action.
        with storage.connect() as con:
            con.execute("UPDATE rag_indexes SET status='active' WHERE id=?", (index["id"],))
            con.execute("INSERT INTO rag_state VALUES('active_index',?)", (index["id"],))
        return storage.get_index(index["id"])


def index_file(path: Path):
    return ingestor.index_file(path, active_index())


def scan():
    return ingestor.scan(active_index())


@asynccontextmanager
async def lifespan(application):
    init_db()
    jobs.recover()
    if SETTINGS.auto_sync:
        index = active_index()
        if SETTINGS.security.auth_mode == "local":
            jobs.submit("startup-sync", Principal(), {}, lambda stage, progress: ingestor.scan(index, stage=stage, progress=progress))
    yield
    # In-flight ingestion finishes before process shutdown. Queued jobs are
    # persisted and are marked interrupted on unclean restart.
    jobs.executor.shutdown(wait=True)
    # TestClient can enter lifespan repeatedly; construct a fresh worker pool.
    from concurrent.futures import ThreadPoolExecutor
    jobs.executor = ThreadPoolExecutor(max_workers=SETTINGS.workers, thread_name_prefix="ingestion")


app = FastAPI(title="Local KnowledgeOS", version="2.0.0", lifespan=lifespan)


@app.exception_handler(QueueFull)
async def queue_full(request, exc):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=429, content={"detail": str(exc)})


@app.exception_handler(KeyError)
async def missing_resource(request, exc):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=404, content={"detail": "Resource not found"})


@app.exception_handler(ValueError)
async def invalid_request(request, exc):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(httpx.HTTPError)
async def unavailable_model(request, exc):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=503, content={"detail": "Pinned local embedding model unavailable; start the configured server or build a new index"})


def principal(request: Request) -> Principal:
    return authenticator.authenticate(request)


def admin(identity: Principal = Depends(principal)) -> Principal:
    if not identity.admin:
        raise HTTPException(403, "Administrator permission required")
    return identity


class QueryRequest(BaseModel):
    query: str = Field(min_length=2, max_length=2000)
    top_k: int = Field(6, ge=1, le=20)
    filters: dict[str, str] = Field(default_factory=dict)
    index_id: str | None = None
    query_expansion: bool | None = None
    hyde: bool | None = None
    # Compatibility: identities are asserted, never trusted from a body/header.
    tenant_id: str | None = None
    owner_id: str | None = None


class IndexRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    embeddings: dict = Field(default_factory=dict)
    chunk_size: int | None = None
    chunk_overlap: int | None = None
    contextual_chunking: dict | None = None


class ACLRequest(BaseModel):
    visibility: str = "private"
    permissions: list[str] = Field(default_factory=list, max_length=100)


class EvaluationRequest(BaseModel):
    questions: list[dict] = Field(min_length=1, max_length=1000)
    index_id: str | None = None


def internal_identity(value) -> Principal:
    # Direct Python calls have the same single-user identity as local mode.
    return value if isinstance(value, Principal) else Principal(permissions=frozenset({"admin"}))


def retrieve(request, identity, trace):
    if request.tenant_id and request.tenant_id != identity.tenant_id or request.owner_id and request.owner_id != identity.owner_id:
        raise HTTPException(403, "Identity override rejected")
    if set(request.filters) - {"filename", "repository", "language", "symbol", "section"}:
        raise ValueError("Unsupported metadata filter")
    index = storage.get_index(request.index_id) if request.index_id else active_index()
    evidence, stats = pipeline.retrieve(request.query, identity, request.top_k, request.filters, trace, index, request.query_expansion, request.hyde)
    latest = storage.get_index(index["id"])
    if latest["revision"] != index["revision"]:
        # A document commit can occur between the dense and sparse reads.
        # Retry once against the updated membership instead of fusing versions.
        index = latest
        evidence, stats = pipeline.retrieve(request.query, identity, request.top_k, request.filters, trace, index, request.query_expansion, request.hyde)
        if storage.get_index(index["id"])["revision"] != index["revision"]:
            raise HTTPException(503, "Index is changing rapidly; retry the query")
    return evidence, stats, index


@app.get("/")
def home():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/health")
def health(identity: Principal = Depends(principal)):
    clause, params = acl_clause("d", identity)
    with storage.connect() as con:
        docs = con.execute(f"SELECT count(*) FROM documents d WHERE {clause} AND d.status='indexed'", params).fetchone()[0]
        index = storage.active_index()
        chunks = con.execute(f"SELECT count(*) FROM rag_members m JOIN rag_chunks c ON c.id=m.chunk_id JOIN documents d ON d.id=c.document_id WHERE {clause} AND m.index_id=?", [*params, index["id"] if index else ""]).fetchone()[0]
        active_jobs = con.execute("SELECT count(*) FROM ingestion_jobs WHERE tenant_id=? AND owner_id=? AND status NOT IN ('completed','failed')", (identity.tenant_id, identity.owner_id)).fetchone()[0]
    return {"status": "ok", "documents": docs, "embedded_chunks": chunks, "active_jobs": active_jobs,
            "llm_provider": SETTINGS.generation.provider, "generation_model": SETTINGS.generation.model,
            "embedding_model": index["embedding_model"] if index else None, "index_version": index["id"] if index else None,
            "auth_mode": SETTINGS.security.auth_mode, "model_endpoints_loopback": True}


@app.get("/documents")
def documents(identity: Principal = Depends(principal)):
    clause, params = acl_clause("d", identity)
    with storage.connect() as con:
        return [dict(row) for row in con.execute(f"SELECT d.* FROM documents d WHERE {clause} ORDER BY updated_at DESC", params)]


def allowed_document(document_id, identity, owner=False):
    clause, params = acl_clause("d", identity)
    with storage.connect() as con:
        row = con.execute(f"SELECT d.* FROM documents d WHERE d.id=? AND {clause}", [document_id, *params]).fetchone()
    if not row or owner and row["owner_id"] != identity.owner_id and not identity.admin:
        raise HTTPException(404, "Document not found")
    return row


@app.get("/documents/{document_id}/versions")
def versions(document_id: int, identity: Principal = Depends(principal)):
    allowed_document(document_id, identity)
    with storage.connect() as con:
        return [dict(row) for row in con.execute("SELECT * FROM document_versions WHERE document_id=? ORDER BY version DESC", (document_id,))]


@app.patch("/documents/{document_id}/acl")
def update_acl(document_id: int, request: ACLRequest, identity: Principal = Depends(principal)):
    allowed_document(document_id, identity, owner=True)
    if request.visibility not in {"private", "tenant", "public"}:
        raise ValueError("Visibility must be private, tenant or public")
    with storage.connect() as con:
        con.execute("UPDATE documents SET visibility=?,permissions=? WHERE id=?", (request.visibility, json.dumps(request.permissions), document_id))
    return {"document_id": document_id, **request.model_dump()}


async def save_upload(file, identity):
    name = Path((file.filename or "upload.txt").replace("\\", "/")).name
    if not name or Path(name).suffix.lower() not in SUPPORTED:
        raise HTTPException(400, "Unsupported file type")
    namespace = sha256(f"{identity.tenant_id}\0{identity.owner_id}".encode())[:24]
    directory = SETTINGS.data_dir / "uploads" / namespace / uuid.uuid4().hex
    directory.mkdir(parents=True)
    target = directory / name
    try:
        with target.open("xb") as output:
            total = 0
            while block := await file.read(1024 * 1024):
                total += len(block)
                if total > SETTINGS.security.max_upload_bytes:
                    raise HTTPException(413, "Upload exceeds configured size limit")
                output.write(block)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    finally:
        await file.close()
    return target


@app.post("/documents", status_code=202)
@app.post("/documents/index", status_code=202)
async def upload(file: UploadFile = File(...), identity: Principal = Depends(principal)):
    target = await save_upload(file, identity)
    index = active_index()
    def operation(stage, progress):
        result = ingestor.index_file(target, index, identity, stage=stage)
        progress(int(result["status"] != "failed"), int(result["status"] == "failed"), 1)
        return result
    return jobs.submit("upload", identity, {"path": str(target), "index_id": index["id"]}, operation)


@app.post("/documents/sync")
def sync(identity: Principal = Depends(admin)):
    index = active_index()
    return jobs.submit("sync", identity, {"index_id": index["id"]}, lambda stage, progress: ingestor.scan(index, identity, stage, progress))


@app.get("/jobs/{job_id}")
def job_status(job_id: str, identity: Principal = Depends(principal)):
    with storage.connect() as con:
        row = con.execute("SELECT * FROM ingestion_jobs WHERE id=? AND tenant_id=? AND owner_id=?", (job_id, identity.tenant_id, identity.owner_id)).fetchone()
    if not row:
        raise HTTPException(404, "Job not found")
    result = dict(row)
    for key in ("summary", "payload", "stage_history"):
        result[key] = json.loads(result[key]) if result.get(key) else None
    return result


@app.get("/changes/latest")
def latest_changes(identity: Principal = Depends(principal)):
    with storage.connect() as con:
        row = con.execute("SELECT id FROM ingestion_jobs WHERE tenant_id=? AND owner_id=? AND summary IS NOT NULL ORDER BY finished_at DESC LIMIT 1", (identity.tenant_id, identity.owner_id)).fetchone()
    return job_status(row[0], identity) if row else {"status": "no_sync_yet", "summary": None}


@app.post("/search")
def search(request: QueryRequest, identity: Principal = Depends(principal)):
    identity = internal_identity(identity)
    trace = Trace()
    index_id = ""
    try:
        evidence, stats, index = retrieve(request, identity, trace)
        index_id = index["id"]
        trace.attributes.update(result_count=len(evidence), index_version=index_id, usage=stats["usage"])
        return {"query": request.query, "results": evidence, "stats": stats, "trace_id": trace.trace_id, "index_version": index_id}
    except Exception as exc:
        trace.attributes["error_type"] = type(exc).__name__
        raise
    finally:
        trace.persist(storage, identity, index_id)


@app.post("/chat")
def chat(request: QueryRequest, identity: Principal = Depends(principal)):
    identity = internal_identity(identity)
    trace, index_id = Trace(), ""
    try:
        evidence, stats, index = retrieve(request, identity, trace)
        index_id = index["id"]
        context = pipeline.context(request.query, evidence, identity, index, trace)
        result = answers.answer(request.query, context, trace)
        stats.update(generation_ms=result["generation_ms"], abstention=result["abstained"], final_context=len(context), latency_ms=trace.as_dict()["latency_ms"])
        usage = {key: stats["usage"].get(key, 0) + result["usage"].get(key, 0) for key in ("prompt_tokens", "completion_tokens")}
        stats["usage"] = usage
        trace.attributes.update(abstention=result["abstained"], result_count=len(evidence), final_context_chars=sum(len(item.get("context_content", "")) for item in context),
                                generation_length=len(result["answer"]), usage=usage, provider_error=result["provider_error"])
        registry = {**index["config"]["registry"], "index_version": index_id, "index_revision": index["revision"], "embedding_model": index["embedding_model"],
                    "embedding_dimension": index["embedding_dimension"], "embedding_provider": index["embedding_provider"],
                    "generation_model": result["model"], "reranker_model": pipeline.reranker.model,
                    "query_configuration": SETTINGS.query.model_dump(), "effective_query_options": {"expansion": stats.get("query_variants", 1) > 1, "hyde": stats.get("hyde_used", False)},
                    "configuration_hash": sha256(json.dumps(SETTINGS.model_dump(mode="json"), sort_keys=True).encode()), "retrieval_configuration": SETTINGS.retrieval.model_dump(),
                    "evidence_manifest": [{"chunk_id": item["id"], "version_id": item["version_id"], "document_id": item["document_id"],
                                           "chunk_hash": item["chunk_hash"], "context_hash": sha256(item["context_content"].encode()), "pipeline_hash": item["pipeline_hash"]} for item in context]}
        citations = [] if result["abstained"] else citation_records(context, result["verification"]["references"])
        return {**result, "citations": citations, "stats": stats, "request_id": trace.trace_id, "trace_id": trace.trace_id,
                "index_version": index_id, "registry": registry}
    except Exception as exc:
        trace.attributes["error_type"] = type(exc).__name__
        raise
    finally:
        trace.persist(storage, identity, index_id)


@app.get("/traces/{trace_id}")
def trace_detail(trace_id: str, identity: Principal = Depends(principal)):
    with storage.connect() as con:
        row = con.execute("SELECT payload FROM rag_traces WHERE trace_id=? AND tenant_id=? AND owner_id=?", (trace_id, identity.tenant_id, identity.owner_id)).fetchone()
    if not row:
        raise HTTPException(404, "Trace not found")
    return json.loads(row[0])


@app.get("/metrics")
def metrics(identity: Principal = Depends(principal)):
    from eval.metrics import percentile
    with storage.connect() as con:
        rows = con.execute("SELECT payload FROM rag_traces WHERE tenant_id=? AND owner_id=? ORDER BY created_at DESC LIMIT 1000", (identity.tenant_id, identity.owner_id)).fetchall()
        states = con.execute("SELECT status,count(*) n FROM ingestion_jobs WHERE tenant_id=? AND owner_id=? GROUP BY status", (identity.tenant_id, identity.owner_id)).fetchall()
    traces = [json.loads(row[0]) for row in rows]
    latencies = [item["latency_ms"] for item in traces]
    return {"queries": {"n": len(rows)}, "ingestion_jobs": {row["status"]: row["n"] for row in states},
            "latency_ms": {"p50": percentile(latencies, .5), "p95": percentile(latencies, .95), "p99": percentile(latencies, .99)},
            "abstentions": sum(item["attributes"].get("abstention", False) for item in traces),
            "errors": sum(bool(item["attributes"].get("error_type")) or any(span["status"] == "error" for span in item["spans"]) for item in traces)}


@app.get("/indexes")
def indexes(identity: Principal = Depends(admin)):
    return storage.indexes()


@app.post("/indexes", status_code=201)
def create_index(request: IndexRequest, identity: Principal = Depends(admin)):
    values = SETTINGS.model_dump(mode="json")
    values["embeddings"].update(request.embeddings)
    for key in ("chunk_size", "chunk_overlap"):
        if getattr(request, key) is not None:
            values[key] = getattr(request, key)
    if request.contextual_chunking:
        values["retrieval"]["contextual_chunking"].update(request.contextual_chunking)
    return storage.create_index(request.name, Settings.model_validate(values))


@app.post("/indexes/{index_id}/build", status_code=202)
def build_index(index_id: str, identity: Principal = Depends(admin)):
    index = storage.get_index(index_id)
    if index["status"] == "retired":
        raise ValueError("Retired indexes are read-only")
    def operation(stage, progress):
        # Include uploaded/Git documents, not just the original scan directory.
        with storage.connect() as con:
            rows = con.execute("SELECT path,tenant_id,owner_id,repository FROM documents WHERE status != 'deleted'").fetchall()
        results = []
        for row in rows:
            results.append(ingestor.index_file(Path(row["path"]), index, Principal(row["tenant_id"], row["owner_id"]), row["repository"], stage))
            progress(len(results), sum(item["status"] == "failed" for item in results), len(rows))
        return {"summary": {"documents_failed": [item["filename"] for item in results if item["status"] == "failed"], "documents_scanned": len(rows)}, "results": results}
    return jobs.submit("index-build", identity, {"index_id": index["id"]}, operation)


@app.post("/indexes/{index_id}/validate")
def validate_index(index_id: str, identity: Principal = Depends(admin)):
    with ingestor.lock:
        return storage.validate_index(index_id)


@app.post("/indexes/{index_id}/activate")
@app.post("/indexes/{index_id}/rollback")
def activate_index(index_id: str, identity: Principal = Depends(admin)):
    with ingestor.lock:
        return storage.activate(index_id)


@app.post("/evaluation/run")
def evaluation(request: EvaluationRequest, identity: Principal = Depends(principal)):
    result = run_benchmark(lambda question: search(QueryRequest(query=question, top_k=20, index_id=request.index_id), identity),
                           lambda question: chat(QueryRequest(query=question, top_k=6, index_id=request.index_id), identity), request.questions)
    with storage.connect() as con:
        con.execute("INSERT INTO rag_evaluations(tenant_id,owner_id,payload,created_at) VALUES(?,?,?,?)", (identity.tenant_id, identity.owner_id, json.dumps(result), time.time()))
    return result


@app.get("/evaluation/results")
def evaluation_results(identity: Principal = Depends(principal)):
    with storage.connect() as con:
        return [{**dict(row), "payload": json.loads(row["payload"])} for row in con.execute("SELECT * FROM rag_evaluations WHERE tenant_id=? AND owner_id=? ORDER BY created_at DESC", (identity.tenant_id, identity.owner_id))]


class GitRequest(BaseModel):
    repository: str = Field(min_length=1, max_length=2000)
    branch: str | None = Field(None, max_length=200)


@app.post("/repositories/git", status_code=202)
def git_ingest(request: GitRequest, identity: Principal = Depends(admin)):
    from app.repositories import GitIngestor
    git = GitIngestor(SETTINGS, storage, ingestor)
    index = active_index()
    return jobs.submit("git-sync", identity, request.model_dump(), lambda stage, progress: git.ingest(request.repository, request.branch, index, identity, stage, progress))


app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
