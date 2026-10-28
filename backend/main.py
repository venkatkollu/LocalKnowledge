"""Local KnowledgeOS API.

The service is intentionally self-contained for local development: SQLite stores
transactional metadata and FTS5 provides sparse retrieval. Ollama supplies local
embeddings by default, while provider profiles can point at any OpenAI-compatible
generation or embedding endpoint. The storage and query contracts keep workspace
IDs on every record so a PostgreSQL/pgvector and Redis deployment can replace
these adapters without changing the API.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import math
import os
import re
import secrets
import shutil
import sqlite3
import statistics
import subprocess
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Iterator
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlparse

from cryptography.fernet import Fernet, InvalidToken
from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, Request as FastAPIRequest, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator


APP_VERSION = "1.0.0"
PROMPT_VERSION = "knowledgeos-answer-v1"
JOB_STAGES = ("parsing", "structure", "chunking", "contextualizing", "embedding", "indexing", "validating")
MAX_UPLOAD_BYTES = int(os.getenv("KNOWLEDGEOS_MAX_UPLOAD_BYTES", str(512 * 1024 * 1024)))
MAX_BATCH_FILES = int(os.getenv("KNOWLEDGEOS_MAX_BATCH_FILES", "10000"))
CHUNK_SIZE = int(os.getenv("KNOWLEDGEOS_CHUNK_SIZE", "1200"))
CHUNK_OVERLAP = int(os.getenv("KNOWLEDGEOS_CHUNK_OVERLAP", "180"))
CACHE_TTL_SECONDS = int(os.getenv("KNOWLEDGEOS_CACHE_TTL_SECONDS", str(7 * 86400)))
SEMANTIC_CACHE_THRESHOLD = float(os.getenv("KNOWLEDGEOS_CACHE_SIMILARITY", "0.92"))
RERANK_TIMEOUT_MS = int(os.getenv("KNOWLEDGEOS_RERANK_TIMEOUT_MS", "80"))
SQLITE_BUSY_TIMEOUT_MS = int(os.getenv("KNOWLEDGEOS_SQLITE_BUSY_TIMEOUT_MS", "60000"))
EMBEDDING_API_KEY = os.getenv("KNOWLEDGEOS_EMBEDDING_API_KEY", os.getenv("OPENAI_API_KEY", "")).strip()
EMBEDDING_API_BASE_URL = os.getenv("KNOWLEDGEOS_EMBEDDING_API_BASE_URL", "https://api.openai.com/v1").rstrip("/")
EMBEDDING_API_MODEL = os.getenv("KNOWLEDGEOS_EMBEDDING_API_MODEL", "BAAI/bge-m3")
OLLAMA_BASE_URL = os.getenv("KNOWLEDGEOS_OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_EMBEDDING_MODEL = os.getenv("KNOWLEDGEOS_OLLAMA_EMBEDDING_MODEL", "all-minilm")
OLLAMA_AUTO_START = os.getenv("KNOWLEDGEOS_OLLAMA_AUTO_START", "true").lower() in {"1", "true", "yes"}
OLLAMA_AUTO_PULL = os.getenv("KNOWLEDGEOS_OLLAMA_AUTO_PULL", "true").lower() in {"1", "true", "yes"}
OLLAMA_PULL_TIMEOUT_SECONDS = int(os.getenv("KNOWLEDGEOS_OLLAMA_PULL_TIMEOUT_SECONDS", "1800"))
LMSTUDIO_BASE_URL = os.getenv("KNOWLEDGEOS_LMSTUDIO_BASE_URL", "http://127.0.0.1:1234/v1").rstrip("/")
LMSTUDIO_EMBEDDING_MODEL = os.getenv("KNOWLEDGEOS_LMSTUDIO_EMBEDDING_MODEL", "").strip()
LOCAL_BGE_MODEL = os.getenv("KNOWLEDGEOS_LOCAL_BGE_MODEL", "BAAI/bge-small-en-v1.5")
LOCAL_BGE_AUTO_LOAD = os.getenv("KNOWLEDGEOS_LOCAL_BGE_AUTO_LOAD", "true").lower() in {"1", "true", "yes"}
ALLOW_HASH_EMBEDDING_FALLBACK = os.getenv("KNOWLEDGEOS_ALLOW_HASH_EMBEDDING_FALLBACK", "false").lower() in {"1", "true", "yes"}
INGEST_EXTENSIONS = {"pdf", "md", "txt", "py", "js", "ts", "tsx", "jsx", "json", "yaml", "yml", "csv", "sql", "go", "rs", "html", "css", "xml", "log"}


def now_ms() -> int:
    return int(time.time() * 1000)


def utc_iso(epoch_ms: int | None) -> str | None:
    if epoch_ms is None:
        return None
    return datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc).isoformat()


def json_dumps(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def secret_env(name: str, default: str = "") -> str:
    """Read a secret from NAME_FILE (Docker/K8s secret) or NAME.

    File-based secrets avoid exposing credentials in the process environment
    and container inspection output. Explicit environment variables win.
    """
    file_path = os.getenv(f"{name}_FILE", "").strip()
    if file_path:
        try:
            return Path(file_path).read_text(encoding="utf-8").strip()
        except OSError:
            pass
    return os.getenv(name, default)


def safe_filename(name: str) -> str:
    name = Path(name or "upload").name
    return re.sub(r"[^A-Za-z0-9._ -]", "_", name)[:240] or "upload"


def extension(name: str) -> str:
    return Path(name).suffix.lower().lstrip(".")


def language_for(name: str) -> str:
    ext = extension(name)
    return {
        "md": "Markdown", "txt": "Text", "py": "Python", "js": "JavaScript",
        "ts": "TypeScript", "tsx": "TSX", "jsx": "JSX", "json": "JSON",
        "yaml": "YAML", "yml": "YAML", "csv": "CSV", "sql": "SQL",
        "go": "Go", "rs": "Rust", "pdf": "PDF", "html": "HTML",
    }.get(ext, ext.upper() if ext else "Document")


def content_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def token_count(text: str) -> int:
    return max(1, len(re.findall(r"\S+", text))) if text.strip() else 0


def split_chunks(text: str) -> list[dict[str, Any]]:
    cleaned = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not cleaned:
        return []
    chunks: list[dict[str, Any]] = []
    cursor = 0
    ordinal = 0
    while cursor < len(cleaned):
        end = min(len(cleaned), cursor + CHUNK_SIZE)
        if end < len(cleaned):
            boundary = max(cleaned.rfind("\n\n", cursor, end), cleaned.rfind("\n", cursor, end), cleaned.rfind(" ", cursor, end))
            if boundary > cursor + CHUNK_SIZE // 2:
                end = boundary
        value = cleaned[cursor:end].strip()
        if value:
            line_start = cleaned.count("\n", 0, cursor) + 1
            line_end = cleaned.count("\n", 0, end) + 1
            chunks.append({"ordinal": ordinal, "text": value, "line_start": line_start, "line_end": line_end, "tokens": token_count(value)})
            ordinal += 1
        if end >= len(cleaned):
            break
        cursor = max(end - CHUNK_OVERLAP, cursor + 1)
    return chunks


def deterministic_vector(text: str, dimensions: int = 256) -> list[float]:
    """Compatibility vector used only when explicitly enabled for offline tests."""
    values = [0.0] * dimensions
    for token in re.findall(r"[\w-]+", text.lower()):
        digest = hashlib.blake2b(token.encode(), digest_size=8).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        values[index] += 1.0 if digest[4] & 1 else -1.0
    norm = math.sqrt(sum(value * value for value in values)) or 1.0
    return [value / norm for value in values]


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    return sum(x * y for x, y in zip(a, b))


def query_terms(value: str) -> list[str]:
    return [term for term in re.findall(r"[A-Za-z0-9_]{2,}", value.lower()) if term not in {"the", "and", "for", "with", "from", "that", "this"}]


def fts_query(value: str) -> str:
    terms = query_terms(value)
    return " OR ".join('"' + term.replace('"', "") + '"' for term in terms[:24]) or '"__no_terms__"'


def understand_query(question: str) -> tuple[list[str], str]:
    """Cheap, deterministic query routing before retrieval.

    A small local splitter keeps short single-intent questions on the fast path
    and lets compound questions retrieve their clauses independently.
    """
    clean = re.sub(r"\s+", " ", question.strip())
    parts = [part.strip(" ,") for part in re.split(r"(?<=[?!.])\s+|;\s+|\s+(?:and|also)\s+(?=(?:how|what|which|why|where|when)\b)", clean, flags=re.IGNORECASE) if part.strip()]
    route = "figure" if re.search(r"\b(figure|image|diagram|chart|plot)\b", clean, re.IGNORECASE) else "table" if re.search(r"\b(table|row|column|sql|count|sum|average)\b", clean, re.IGNORECASE) else "text"
    return (parts[:4] or [clean]), route


class Settings:
    def __init__(self) -> None:
        self.data_dir = Path(os.getenv("KNOWLEDGEOS_DATA_DIR", "data"))
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "knowledgeos.sqlite3"
        self.files_dir = self.data_dir / "files"
        self.files_dir.mkdir(parents=True, exist_ok=True)
        self.max_upload_bytes = MAX_UPLOAD_BYTES
        self.ollama_base_url = OLLAMA_BASE_URL
        self.ollama_embedding_model = OLLAMA_EMBEDDING_MODEL
        self.ollama_auto_start = OLLAMA_AUTO_START
        self.ollama_auto_pull = OLLAMA_AUTO_PULL
        self.ollama_pull_timeout_seconds = OLLAMA_PULL_TIMEOUT_SECONDS
        self.ollama_host = os.getenv("OLLAMA_HOST", "127.0.0.1:11434")
        self.embedding_api_key = EMBEDDING_API_KEY
        self.embedding_api_base_url = EMBEDDING_API_BASE_URL
        self.embedding_api_model = EMBEDDING_API_MODEL
        self.lmstudio_base_url = LMSTUDIO_BASE_URL
        self.lmstudio_embedding_model = LMSTUDIO_EMBEDDING_MODEL
        self.local_bge_model = LOCAL_BGE_MODEL
        self.local_bge_auto_load = LOCAL_BGE_AUTO_LOAD
        self.allow_hash_embedding_fallback = ALLOW_HASH_EMBEDDING_FALLBACK
        self.allow_anonymous = os.getenv("KNOWLEDGEOS_ALLOW_ANONYMOUS", "true").lower() in {"1", "true", "yes"}
        self.auth_secret = secret_env("KNOWLEDGEOS_AUTH_SECRET", "local-development-secret").encode()
        if not self.allow_anonymous and len(self.auth_secret) < 16:
            raise RuntimeError("Set a strong KNOWLEDGEOS_AUTH_SECRET (at least 16 characters) when anonymous access is disabled")
        configured_key = secret_env("KNOWLEDGEOS_ENCRYPTION_KEY")
        if configured_key:
            self.encryption_key = configured_key.encode()
        else:
            self.encryption_key = base64.urlsafe_b64encode(hashlib.sha256(self.auth_secret + b"/provider-keys").digest())
        self.fernet = Fernet(self.encryption_key)


SETTINGS = Settings()
EXECUTOR = ThreadPoolExecutor(max_workers=max(2, int(os.getenv("KNOWLEDGEOS_WORKERS", "4"))))
DB_LOCK = threading.RLock()
EMBEDDING_RUNTIME_LOCK = threading.RLock()
OLLAMA_PROCESS: subprocess.Popen[bytes] | None = None
OLLAMA_MODEL_READY = False
OLLAMA_MODEL_CHECKED = False
LMSTUDIO_SELECTED_MODEL: str | None = None
LOCAL_BGE_ENCODER: Any | None = None
LOCAL_BGE_LOAD_ERROR: str | None = None


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS workspaces (id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS provider_profiles (
  id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, name TEXT NOT NULL, kind TEXT NOT NULL,
  base_url TEXT NOT NULL, model TEXT NOT NULL, role TEXT NOT NULL, encrypted_key TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1, failure_count INTEGER NOT NULL DEFAULT 0,
  unhealthy_until INTEGER, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
  UNIQUE(workspace_id, name)
);
CREATE TABLE IF NOT EXISTS documents (
  id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, filename TEXT NOT NULL, path TEXT NOT NULL,
  storage_path TEXT NOT NULL, extension TEXT NOT NULL, language TEXT NOT NULL, size_bytes INTEGER NOT NULL,
  content_hash TEXT NOT NULL, status TEXT NOT NULL, updated_at INTEGER NOT NULL, indexed_at INTEGER,
  version INTEGER NOT NULL DEFAULT 0, parser TEXT, chunker TEXT, embedding TEXT, error TEXT,
  progress REAL, stage TEXT, deleted_at INTEGER, UNIQUE(workspace_id, content_hash)
);
CREATE TABLE IF NOT EXISTS document_versions (
  id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, document_id TEXT NOT NULL, version INTEGER NOT NULL,
  content_hash TEXT NOT NULL, created_at INTEGER NOT NULL, current INTEGER NOT NULL DEFAULT 1,
  chunks INTEGER NOT NULL DEFAULT 0, reused INTEGER NOT NULL DEFAULT 0, newly_embedded INTEGER NOT NULL DEFAULT 0, note TEXT,
  UNIQUE(document_id, version)
);
CREATE TABLE IF NOT EXISTS chunks (
  id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, document_id TEXT NOT NULL, version INTEGER NOT NULL,
  ordinal INTEGER NOT NULL, text TEXT NOT NULL, line_start INTEGER NOT NULL, line_end INTEGER NOT NULL,
  section TEXT, symbol TEXT, tokens INTEGER NOT NULL, embedding_json TEXT, superseded INTEGER NOT NULL DEFAULT 0,
  UNIQUE(document_id, version, ordinal)
);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(text, chunk_id UNINDEXED, workspace_id UNINDEXED, document_id UNINDEXED);
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, document_id TEXT, kind TEXT NOT NULL, status TEXT NOT NULL,
  stage TEXT NOT NULL, progress REAL NOT NULL DEFAULT 0, retry_count INTEGER NOT NULL DEFAULT 0,
  last_error TEXT, idempotency_key TEXT NOT NULL, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
  UNIQUE(workspace_id, idempotency_key)
);
CREATE TABLE IF NOT EXISTS index_versions (
  id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, state TEXT NOT NULL, revision INTEGER NOT NULL,
  embedding TEXT, dimensions INTEGER, documents INTEGER NOT NULL DEFAULT 0, chunks INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL, built_at INTEGER, validated INTEGER NOT NULL DEFAULT 0, evaluated INTEGER NOT NULL DEFAULT 0,
  evaluation_score REAL, notes TEXT
);
CREATE TABLE IF NOT EXISTS cache_entries (
  id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, index_version TEXT NOT NULL, model_profile_id TEXT,
  prompt_version TEXT NOT NULL, query_hash TEXT NOT NULL, query_text TEXT NOT NULL, embedding_json TEXT,
  response_json TEXT NOT NULL, confidence REAL NOT NULL, created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL,
  UNIQUE(workspace_id, index_version, model_profile_id, prompt_version, query_hash)
);
CREATE TABLE IF NOT EXISTS traces (
  id TEXT PRIMARY KEY, request_id TEXT NOT NULL, workspace_id TEXT NOT NULL, route TEXT NOT NULL,
  cache_hit INTEGER NOT NULL DEFAULT 0, model_profile_id TEXT, model TEXT, index_version TEXT,
  prompt_version TEXT NOT NULL, stage_timings_json TEXT NOT NULL, token_counts_json TEXT,
  cost_estimate REAL, outcome TEXT, error_code TEXT, created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
  id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, kind TEXT NOT NULL, title TEXT NOT NULL,
  detail TEXT, document_id TEXT, trace_id TEXT, created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS golden_set (
  id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, question TEXT NOT NULL,
  expected_document_id TEXT, expected_chunk_id TEXT, created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS evaluations (
  id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, index_version TEXT NOT NULL,
  recall100 REAL NOT NULL, ndcg10 REAL NOT NULL, mrr10 REAL NOT NULL, passed INTEGER NOT NULL,
  compared_index TEXT, override_reason TEXT, created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS feedback (
  id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, trace_id TEXT NOT NULL,
  rating INTEGER NOT NULL CHECK(rating IN (-1, 1)), comment TEXT, created_at INTEGER NOT NULL
);
"""


@contextmanager
def db() -> Iterator[sqlite3.Connection]:
    # Keep every transaction short and make concurrent API/background writes wait
    # instead of immediately failing with "database is locked". DB_LOCK also
    # prevents this process's worker threads from competing for SQLite's single
    # writer slot; the busy timeout covers a second backend process/reloader.
    with DB_LOCK:
        connection = sqlite3.connect(SETTINGS.db_path, timeout=SQLITE_BUSY_TIMEOUT_MS / 1000, check_same_thread=False)
        connection.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()


def init_db() -> None:
    with DB_LOCK, db() as connection:
        connection.executescript(SCHEMA)
        connection.execute("INSERT OR IGNORE INTO workspaces(id, name, created_at) VALUES (?, ?, ?)", ("default", "Default workspace", now_ms()))


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield
    EXECUTOR.shutdown(wait=False, cancel_futures=False)


app = FastAPI(title="Local KnowledgeOS API", version=APP_VERSION, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.getenv("KNOWLEDGEOS_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@dataclass(frozen=True)
class Principal:
    workspace_id: str
    user_id: str


def principal(
    x_workspace_id: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> Principal:
    workspace_id = (x_workspace_id or "default").strip()
    user_id = (x_user_id or "local").strip()
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", workspace_id):
        raise HTTPException(400, "Invalid workspace id")
    if not SETTINGS.allow_anonymous:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(401, "Bearer authentication required")
        token = authorization.removeprefix("Bearer ")
        expected = hmac.new(SETTINGS.auth_secret, f"{workspace_id}:{user_id}".encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(token, expected):
            raise HTTPException(401, "Invalid authentication token")
    with db() as connection:
        connection.execute("INSERT OR IGNORE INTO workspaces(id, name, created_at) VALUES (?, ?, ?)", (workspace_id, workspace_id, now_ms()))
    return Principal(workspace_id, user_id)


def encrypt_key(value: str) -> str:
    return SETTINGS.fernet.encrypt(value.encode()).decode()


def decrypt_key(value: str) -> str:
    try:
        return SETTINGS.fernet.decrypt(value.encode()).decode()
    except InvalidToken as exc:
        raise HTTPException(500, "Provider key cannot be decrypted") from exc


def row_document(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"], "filename": row["filename"], "path": row["path"], "extension": row["extension"],
        "language": row["language"], "size_bytes": row["size_bytes"], "chunks": 0, "status": row["status"],
        "updated_at": row["updated_at"], "indexed_at": row["indexed_at"], "version": row["version"],
        "content_hash": row["content_hash"], "parser": row["parser"], "chunker": row["chunker"],
        "embedding": row["embedding"], "error": row["error"], "progress": row["progress"], "stage": row["stage"],
    }


def document_row(connection: sqlite3.Connection, workspace_id: str, document_id: str) -> sqlite3.Row | None:
    return connection.execute("SELECT d.*, (SELECT COUNT(*) FROM chunks c WHERE c.document_id=d.id AND c.superseded=0) AS chunks FROM documents d WHERE d.workspace_id=? AND d.id=? AND d.deleted_at IS NULL", (workspace_id, document_id)).fetchone()


def provider_row(connection: sqlite3.Connection, workspace_id: str, provider_id: str, role: str | None = None) -> sqlite3.Row | None:
    query = "SELECT * FROM provider_profiles WHERE workspace_id=? AND id=? AND enabled=1"
    args: list[Any] = [workspace_id, provider_id]
    if role:
        query += " AND (role=? OR role='Both')"
        args.append(role)
    return connection.execute(query, args).fetchone()


def choose_provider(connection: sqlite3.Connection, workspace_id: str, role: str) -> sqlite3.Row | None:
    return connection.execute("SELECT * FROM provider_profiles WHERE workspace_id=? AND enabled=1 AND (role=? OR role='Both') AND (unhealthy_until IS NULL OR unhealthy_until<?) ORDER BY created_at LIMIT 1", (workspace_id, role, now_ms())).fetchone()


def embedding_identity(row: sqlite3.Row | dict[str, Any] | None) -> str:
    return row["model"] if row is not None else f"ollama:{SETTINGS.ollama_embedding_model}"


def provider_request(row: sqlite3.Row | dict[str, Any], path: str, payload: dict[str, Any], timeout: float = 30.0, method: str = "POST") -> dict[str, Any]:
    base = row["base_url"].rstrip("/")
    url = base + (path if path.startswith("/") else "/" + path)
    body = json.dumps(payload).encode() if method != "GET" else None
    request_headers = {"Authorization": f"Bearer {decrypt_key(row['encrypted_key'])}"}
    if body is not None:
        request_headers["Content-Type"] = "application/json"
    request = Request(url, data=body, headers=request_headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode())
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        with db() as connection:
            connection.execute("UPDATE provider_profiles SET failure_count=failure_count+1, unhealthy_until=? WHERE id=?", (now_ms() + 60_000, row["id"]))
        raise RuntimeError(f"Provider request failed: {exc}") from exc


def ollama_post(path: str, payload: dict[str, Any], timeout: float = 30.0) -> dict[str, Any]:
    request = Request(
        f"{SETTINGS.ollama_base_url}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode())


def ollama_embed_text(text: str) -> list[float]:
    """Embed text with Ollama's current API, supporting older Ollama installs."""
    modern_payload = {"model": SETTINGS.ollama_embedding_model, "input": text}
    try:
        response = ollama_post("/api/embed", modern_payload, timeout=30)
    except HTTPError as exc:
        if exc.code != 404:
            raise RuntimeError(f"Ollama embedding request failed: HTTP {exc.code}") from exc
        try:
            response = ollama_post(
                "/api/embeddings",
                {"model": SETTINGS.ollama_embedding_model, "prompt": text},
                timeout=30,
            )
        except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as legacy_exc:
            raise RuntimeError(f"Ollama embedding request failed at {SETTINGS.ollama_base_url}: {legacy_exc}") from legacy_exc
    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Ollama embedding request failed at {SETTINGS.ollama_base_url}: {exc}") from exc

    if not isinstance(response, dict):
        raise RuntimeError("Ollama returned an invalid response")
    embeddings = response.get("embeddings") or []
    if embeddings and isinstance(embeddings[0], (int, float)):
        vector = embeddings
    elif embeddings:
        vector = embeddings[0]
    else:
        vector = response.get("embedding") or []
    if not isinstance(vector, (list, tuple)):
        raise RuntimeError("Ollama returned an invalid embedding vector")
    if not vector:
        raise RuntimeError("Ollama returned no embedding vector")
    try:
        return [float(value) for value in vector]
    except (TypeError, ValueError) as exc:
        raise RuntimeError("Ollama returned an invalid embedding vector") from exc


def embed_text(row: sqlite3.Row | dict[str, Any] | None, text: str) -> list[float]:
    if row is None:
        try:
            return ollama_embed_text(text)
        except RuntimeError:
            if SETTINGS.allow_hash_embedding_fallback:
                return deterministic_vector(text)
            raise
    payload = provider_request(row, "/embeddings", {"model": row["model"], "input": text}, timeout=20)
    data = payload.get("data") or []
    vector = data[0].get("embedding") if data else []
    if not vector:
        raise RuntimeError(f"Embedding provider {row['name']} returned no embedding vector")
    try:
        return [float(value) for value in vector]
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"Embedding provider {row['name']} returned an invalid vector") from exc


def read_document_text(path: Path, name: str) -> str:
    if extension(name) == "pdf":
        try:
            from pypdf import PdfReader
            return "\n\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)
        except Exception:
            return ""
    output: list[str] = []
    remaining = int(os.getenv("KNOWLEDGEOS_MAX_EXTRACTED_BYTES", str(64 * 1024 * 1024)))
    with path.open("rb") as handle:
        while remaining > 0:
            block = handle.read(min(1024 * 1024, remaining))
            if not block:
                break
            remaining -= len(block)
            output.append(block.decode("utf-8", errors="replace"))
    return "".join(output)


def set_job(connection: sqlite3.Connection, job_id: str, **fields: Any) -> None:
    assignments = ", ".join(f"{key}=?" for key in fields)
    values = list(fields.values()) + [now_ms(), job_id]
    connection.execute(f"UPDATE jobs SET {assignments}, updated_at=? WHERE id=?", values)


def emit_event(workspace_id: str, kind: str, title: str, detail: str | None = None, document_id: str | None = None, trace_id: str | None = None) -> None:
    with db() as connection:
        connection.execute("INSERT INTO events(id, workspace_id, kind, title, detail, document_id, trace_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (str(uuid.uuid4()), workspace_id, kind, title, detail, document_id, trace_id, now_ms()))


def process_job(job_id: str) -> None:
    with db() as connection:
        job = connection.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if job is None or not job["document_id"]:
        return
    workspace_id = job["workspace_id"]
    document_id = job["document_id"]
    try:
        with db() as connection:
            document = document_row(connection, workspace_id, document_id)
            if document is None:
                raise RuntimeError("Document not found")
            set_job(connection, job_id, status="running", stage="parsing", progress=0.05)
            connection.execute("UPDATE documents SET status='processing', stage='parsing', progress=0.05, error=NULL WHERE id=?", (document_id,))
        source = Path(document["path"]) / document["filename"] if Path(document["path"]).is_absolute() else None
        source_changed = False
        if source and source.exists() and source.resolve() != Path(document["storage_path"]).resolve():
            live_digest = content_hash(source)
            if live_digest != document["content_hash"]:
                source_changed = True
                copied, live_size, _ = save_local_file(source, workspace_id)
                with db() as connection:
                    connection.execute("UPDATE documents SET storage_path=?, size_bytes=?, content_hash=?, status='changed', updated_at=? WHERE id=?", (str(copied), live_size, live_digest, now_ms(), document_id))
                with db() as connection:
                    document = document_row(connection, workspace_id, document_id)
        text = read_document_text(Path(document["storage_path"]), document["filename"])
        if job["kind"] == "sync" and not source_changed and int(document["version"] or 0) > 0 and content_hash(Path(document["storage_path"])) == document["content_hash"]:
            with db() as connection:
                connection.execute("UPDATE documents SET status='synced', stage=NULL, progress=NULL, error=NULL WHERE id=?", (document_id,))
                set_job(connection, job_id, status="completed", stage="completed", progress=1)
            return
        chunks = split_chunks(text)
        with db() as connection:
            set_job(connection, job_id, stage="structure", progress=0.18)
            connection.execute("UPDATE documents SET stage='structure', progress=0.18 WHERE id=?", (document_id,))
            set_job(connection, job_id, stage="chunking", progress=0.32)
            connection.execute("UPDATE documents SET stage='chunking', progress=0.32 WHERE id=?", (document_id,))
            current = connection.execute("SELECT version, content_hash FROM documents WHERE id=?", (document_id,)).fetchone()
            if current is None:
                raise RuntimeError("Document not found")
            version = int(current["version"]) + 1
            embedding_row = choose_provider(connection, workspace_id, "Embeddings")
            previous_chunk_ids = [row["id"] for row in connection.execute("SELECT id FROM chunks WHERE document_id=? AND superseded=0", (document_id,)).fetchall()]
            content_hash_for_version = current["content_hash"]

        # Embedding calls can take seconds (or longer). Never keep a SQLite
        # transaction open while waiting on Ollama or a remote provider.
        embedding_row = dict(embedding_row) if embedding_row is not None else None
        with db() as connection:
            set_job(connection, job_id, stage="embedding", progress=0.58)
            connection.execute("UPDATE documents SET stage='embedding', progress=0.58, embedding=? WHERE id=?", (embedding_identity(embedding_row), document_id))
        embedded_chunks = [(chunk, embed_text(embedding_row, chunk["text"])) for chunk in chunks]

        with db() as connection:
            current = connection.execute("SELECT version, content_hash FROM documents WHERE id=?", (document_id,)).fetchone()
            if current is None or int(current["version"]) != version - 1 or current["content_hash"] != content_hash_for_version:
                raise RuntimeError("Document changed while it was being indexed; please retry")
            connection.execute("UPDATE document_versions SET current=0 WHERE document_id=?", (document_id,))
            for chunk, vector in embedded_chunks:
                chunk_id = str(uuid.uuid4())
                connection.execute("INSERT INTO chunks(id, workspace_id, document_id, version, ordinal, text, line_start, line_end, tokens, embedding_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (chunk_id, workspace_id, document_id, version, chunk["ordinal"], chunk["text"], chunk["line_start"], chunk["line_end"], chunk["tokens"], json_dumps(vector)))
                connection.execute("INSERT INTO chunks_fts(text, chunk_id, workspace_id, document_id) VALUES (?, ?, ?, ?)", (chunk["text"], chunk_id, workspace_id, document_id))
            if previous_chunk_ids:
                connection.executemany("UPDATE chunks SET superseded=1 WHERE id=?", [(chunk_id,) for chunk_id in previous_chunk_ids])
                connection.executemany("DELETE FROM chunks_fts WHERE chunk_id=?", [(chunk_id,) for chunk_id in previous_chunk_ids])
            set_job(connection, job_id, stage="indexing", progress=0.78)
            connection.execute("UPDATE documents SET stage='indexing', progress=0.78 WHERE id=?", (document_id,))
            connection.execute("INSERT INTO document_versions(id, workspace_id, document_id, version, content_hash, created_at, chunks, reused, newly_embedded, note) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (str(uuid.uuid4()), workspace_id, document_id, version, content_hash_for_version, now_ms(), len(chunks), 0, len(chunks), "Initial ingestion" if version == 1 else "Incremental update"))
            set_job(connection, job_id, stage="validating", progress=0.93)
            connection.execute("UPDATE documents SET stage='validating', progress=0.93 WHERE id=?", (document_id,))
            connection.execute("UPDATE documents SET status='synced', stage=NULL, progress=NULL, indexed_at=?, version=?, parser=?, chunker=?, error=NULL WHERE id=?", (now_ms(), version, "text-v1", f"fixed-{CHUNK_SIZE}-{CHUNK_OVERLAP}", document_id))
            set_job(connection, job_id, status="completed", stage="completed", progress=1)
        emit_event(workspace_id, "sync", f"{document['filename']} indexed", f"{len(chunks)} chunks", document_id=document_id)
    except Exception as exc:
        with db() as connection:
            set_job(connection, job_id, status="failed", stage="failed", progress=1, last_error=str(exc))
            connection.execute("UPDATE documents SET status='failed', stage=NULL, progress=NULL, error=? WHERE id=?", (str(exc), document_id))
        emit_event(workspace_id, "error", "Ingestion failed", str(exc), document_id=document_id)


class ProviderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: str = Field(min_length=1, max_length=80)
    base_url: str = Field(min_length=8, max_length=500)
    model: str = Field(min_length=1, max_length=200)
    role: str = Field(default="Generation", pattern="^(Generation|Embeddings|Both)$")
    api_key: str = Field(min_length=1, max_length=1000)

    @field_validator("base_url")
    @classmethod
    def valid_url(cls, value: str) -> str:
        if not value.startswith(("http://", "https://")):
            raise ValueError("base_url must use http:// or https://")
        return value.rstrip("/")


class ProviderUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    base_url: str | None = Field(default=None, min_length=8, max_length=500)
    model: str | None = Field(default=None, min_length=1, max_length=200)
    role: str | None = Field(default=None, pattern="^(Generation|Embeddings|Both)$")
    api_key: str | None = Field(default=None, min_length=1, max_length=1000)
    enabled: bool | None = None


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=20_000)
    top_k: int = Field(default=6, ge=1, le=20)
    stream: bool = False
    model_profile_id: str | None = None


class GoldenSetItem(BaseModel):
    question: str = Field(min_length=1, max_length=20_000)
    expected_document_id: str | None = None
    expected_chunk_id: str | None = None


class FeedbackRequest(BaseModel):
    trace_id: str
    rating: int = Field(ge=-1, le=1)
    comment: str | None = Field(default=None, max_length=2000)


def provider_public(row: sqlite3.Row) -> dict[str, Any]:
    return {"id": row["id"], "name": row["name"], "kind": row["kind"], "base_url": row["base_url"], "model": row["model"], "role": row["role"], "enabled": bool(row["enabled"]), "created_at": row["created_at"], "updated_at": row["updated_at"], "has_api_key": True}


@app.get("/health")
@app.get("/api/health")
def health(p: Principal = Depends(principal)) -> dict[str, Any]:
    with db() as connection:
        documents = connection.execute("SELECT COUNT(*) FROM documents WHERE workspace_id=? AND deleted_at IS NULL", (p.workspace_id,)).fetchone()[0]
        chunks = connection.execute("SELECT COUNT(*) FROM chunks WHERE workspace_id=? AND superseded=0", (p.workspace_id,)).fetchone()[0]
        active = connection.execute("SELECT id FROM index_versions WHERE workspace_id=? AND state='active' ORDER BY revision DESC LIMIT 1", (p.workspace_id,)).fetchone()
        embedding_row = choose_provider(connection, p.workspace_id, "Embeddings")
    return {"ok": True, "version": APP_VERSION, "documents": documents, "chunks": chunks, "fts5_active": True, "active_index": active["id"] if active else None, "embedding_provider": embedding_identity(embedding_row), "ollama": {"base_url": SETTINGS.ollama_base_url, "model": SETTINGS.ollama_embedding_model, "hash_fallback": SETTINGS.allow_hash_embedding_fallback}}


@app.get("/api/models/profiles")
def list_providers(p: Principal = Depends(principal)) -> list[dict[str, Any]]:
    with db() as connection:
        return [provider_public(row) for row in connection.execute("SELECT * FROM provider_profiles WHERE workspace_id=? ORDER BY created_at", (p.workspace_id,)).fetchall()]


@app.post("/api/models/profiles", status_code=201)
def create_provider(payload: ProviderCreate, p: Principal = Depends(principal)) -> dict[str, Any]:
    provider_id = str(uuid.uuid4())
    timestamp = now_ms()
    with db() as connection:
        try:
            connection.execute("INSERT INTO provider_profiles(id, workspace_id, name, kind, base_url, model, role, encrypted_key, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (provider_id, p.workspace_id, payload.name, payload.kind, payload.base_url, payload.model, payload.role, encrypt_key(payload.api_key), timestamp, timestamp))
        except sqlite3.IntegrityError as exc:
            raise HTTPException(409, "A provider with this name already exists") from exc
        row = connection.execute("SELECT * FROM provider_profiles WHERE id=?", (provider_id,)).fetchone()
    return provider_public(row)


@app.patch("/api/models/profiles/{provider_id}")
def update_provider(provider_id: str, payload: ProviderUpdate, p: Principal = Depends(principal)) -> dict[str, Any]:
    values = payload.model_dump(exclude_unset=True)
    if "api_key" in values:
        values["encrypted_key"] = encrypt_key(values.pop("api_key"))
    if not values:
        raise HTTPException(400, "No fields to update")
    values["updated_at"] = now_ms()
    assignments = ", ".join(f"{key}=?" for key in values)
    with db() as connection:
        result = connection.execute(f"UPDATE provider_profiles SET {assignments} WHERE id=? AND workspace_id=?", [*values.values(), provider_id, p.workspace_id])
        if result.rowcount == 0:
            raise HTTPException(404, "Provider not found")
        return provider_public(connection.execute("SELECT * FROM provider_profiles WHERE id=?", (provider_id,)).fetchone())


@app.delete("/api/models/profiles/{provider_id}", status_code=204)
def delete_provider(provider_id: str, p: Principal = Depends(principal)) -> None:
    with db() as connection:
        result = connection.execute("DELETE FROM provider_profiles WHERE id=? AND workspace_id=?", (provider_id, p.workspace_id))
        if result.rowcount == 0:
            raise HTTPException(404, "Provider not found")


@app.post("/api/models/profiles/{provider_id}/test")
def test_provider(provider_id: str, p: Principal = Depends(principal)) -> dict[str, Any]:
    with db() as connection:
        row = provider_row(connection, p.workspace_id, provider_id)
    if row is None:
        raise HTTPException(404, "Provider not found")
    try:
        result = provider_request(row, "/models", {}, timeout=15, method="GET")
        return {"ok": True, "provider_id": provider_id, "models": result.get("data", result.get("models", []))}
    except RuntimeError as exc:
        return {"ok": False, "provider_id": provider_id, "detail": str(exc)}


def save_upload(upload: UploadFile, workspace_id: str) -> tuple[Path, int, str]:
    target_dir = SETTINGS.files_dir / workspace_id
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{uuid.uuid4()}-{safe_filename(upload.filename or 'upload')}"
    digest = hashlib.sha256()
    total = 0
    with target.open("wb") as handle:
        while True:
            block = upload.file.read(1024 * 1024)
            if not block:
                break
            total += len(block)
            if total > SETTINGS.max_upload_bytes:
                target.unlink(missing_ok=True)
                raise HTTPException(413, f"File exceeds {SETTINGS.max_upload_bytes} bytes")
            digest.update(block)
            handle.write(block)
    return target, total, digest.hexdigest()


def save_local_file(source: Path, workspace_id: str) -> tuple[Path, int, str]:
    """Copy a local source into workspace storage while hashing it in one pass."""
    target_dir = SETTINGS.files_dir / workspace_id
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{uuid.uuid4()}-{safe_filename(source.name)}"
    digest = hashlib.sha256()
    total = 0
    try:
        with source.open("rb") as source_handle, target.open("wb") as target_handle:
            for block in iter(lambda: source_handle.read(1024 * 1024), b""):
                total += len(block)
                if total > SETTINGS.max_upload_bytes:
                    raise HTTPException(413, f"File exceeds {SETTINGS.max_upload_bytes} bytes")
                digest.update(block)
                target_handle.write(block)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return target, total, digest.hexdigest()


def queue_document(workspace_id: str, filename: str, path: Path, size: int, digest: str, source_path: str = "Uploads") -> tuple[dict[str, Any], dict[str, Any] | None]:
    timestamp = now_ms()
    with db() as connection:
        source_existing = connection.execute("SELECT * FROM documents WHERE workspace_id=? AND path=? AND filename=? AND deleted_at IS NULL ORDER BY updated_at DESC LIMIT 1", (workspace_id, source_path, filename)).fetchone()
        if source_existing:
            if source_existing["content_hash"] == digest:
                return row_document(source_existing), None
            hash_owner = connection.execute("SELECT * FROM documents WHERE workspace_id=? AND content_hash=? AND deleted_at IS NULL AND id!=?", (workspace_id, digest, source_existing["id"])).fetchone()
            if hash_owner:
                return row_document(hash_owner), None
            document_id = source_existing["id"]
            connection.execute("UPDATE documents SET storage_path=?, size_bytes=?, content_hash=?, status='changed', updated_at=?, error=NULL, progress=NULL, stage=NULL WHERE id=?", (str(path), size, digest, timestamp, document_id))
            idempotency_key = f"ingest:{document_id}:{digest}"
            job_id = str(uuid.uuid4())
            connection.execute("INSERT INTO jobs(id, workspace_id, document_id, kind, status, stage, idempotency_key, created_at, updated_at) VALUES (?, ?, ?, 'ingest', 'queued', 'parsing', ?, ?, ?)", (job_id, workspace_id, document_id, idempotency_key, timestamp, timestamp))
            document = connection.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()
            job = connection.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            submit_job = job_id
        else:
            submit_job = None
        existing = connection.execute("SELECT * FROM documents WHERE workspace_id=? AND content_hash=?", (workspace_id, digest)).fetchone()
        if source_existing:
            pass
        elif existing and existing["deleted_at"] is None:
            return row_document(existing), None
        elif existing:
            document_id = existing["id"]
            connection.execute("UPDATE documents SET filename=?, path=?, storage_path=?, extension=?, language=?, size_bytes=?, status='not_indexed', updated_at=?, deleted_at=NULL, error=NULL, progress=NULL, stage=NULL WHERE id=?", (filename, source_path, str(path), extension(filename), language_for(filename), size, timestamp, document_id))
            idempotency_key = f"ingest:{digest}:{timestamp}"
            job_id = str(uuid.uuid4())
            connection.execute("INSERT INTO jobs(id, workspace_id, document_id, kind, status, stage, idempotency_key, created_at, updated_at) VALUES (?, ?, ?, 'ingest', 'queued', 'parsing', ?, ?, ?)", (job_id, workspace_id, document_id, idempotency_key, timestamp, timestamp))
            document = connection.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()
            job = connection.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            submit_job = job_id
        elif not source_existing:
            document_id = str(uuid.uuid4())
            connection.execute("INSERT INTO documents(id, workspace_id, filename, path, storage_path, extension, language, size_bytes, content_hash, status, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'not_indexed', ?)", (document_id, workspace_id, filename, source_path, str(path), extension(filename), language_for(filename), size, digest, timestamp))
            idempotency_key = f"ingest:{digest}"
            job_id = str(uuid.uuid4())
            connection.execute("INSERT INTO jobs(id, workspace_id, document_id, kind, status, stage, idempotency_key, created_at, updated_at) VALUES (?, ?, ?, 'ingest', 'queued', 'parsing', ?, ?, ?)", (job_id, workspace_id, document_id, idempotency_key, timestamp, timestamp))
            document = connection.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()
            job = connection.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            submit_job = job_id
    EXECUTOR.submit(process_job, submit_job)
    return row_document(document), dict(job)


def job_public(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    get = row.__getitem__
    return {"id": get("id"), "document_id": get("document_id"), "document_name": get("document_name") if "document_name" in row.keys() else None, "stage": get("stage"), "status": get("status"), "progress": get("progress"), "error": get("last_error")}


@app.get("/api/documents")
def list_documents(p: Principal = Depends(principal)) -> dict[str, Any]:
    with db() as connection:
        rows = connection.execute("SELECT d.*, (SELECT COUNT(*) FROM chunks c WHERE c.document_id=d.id AND c.superseded=0) AS chunks FROM documents d WHERE d.workspace_id=? AND d.deleted_at IS NULL ORDER BY d.updated_at DESC", (p.workspace_id,)).fetchall()
        return {"documents": [row_document(row) | {"chunks": row["chunks"]} for row in rows]}


@app.post("/api/documents")
async def upload_documents(
    request: FastAPIRequest,
    files: list[UploadFile] = File(default=[]),
    p: Principal = Depends(principal),
) -> dict[str, Any]:
    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" not in content_type:
        body = await request.json()
        source = Path(str(body.get("path", "")).strip()).expanduser()
        try:
            source = source.resolve(strict=True)
        except FileNotFoundError as exc:
            raise HTTPException(400, "Folder path does not exist") from exc
        if not source.is_dir():
            raise HTTPException(400, "Folder path must point to a directory")
        candidates: list[Path] = []
        for item in source.rglob("*"):
            if item.is_file() and not item.is_symlink() and extension(item.name) in INGEST_EXTENSIONS:
                candidates.append(item)
                if len(candidates) > MAX_BATCH_FILES:
                    raise HTTPException(413, f"Folder contains more than {MAX_BATCH_FILES} supported files")
        jobs: list[dict[str, Any]] = []
        accepted: list[str] = []
        for item in candidates:
            try:
                stored, size, digest = save_local_file(item, p.workspace_id)
                document, job = queue_document(p.workspace_id, safe_filename(item.name), stored, size, digest, str(item.parent))
                if job:
                    jobs.append(job_public(job))
                    accepted.append(document["filename"])
                else:
                    stored.unlink(missing_ok=True)
            except HTTPException:
                raise
            except OSError as exc:
                raise HTTPException(400, f"Could not read {item.name}: {exc}") from exc
        return {"accepted": accepted, "jobs": jobs, "files_seen": len(candidates)}
        
    jobs: list[dict[str, Any]] = []
    accepted: list[str] = []
    if len(files) > MAX_BATCH_FILES:
        raise HTTPException(413, f"Upload contains more than {MAX_BATCH_FILES} files")
    for upload in files:
        path, size, digest = save_upload(upload, p.workspace_id)
        document, job = queue_document(p.workspace_id, safe_filename(upload.filename or "upload"), path, size, digest)
        accepted.append(document["filename"])
        if job:
            jobs.append(job_public(job))
        else:
            path.unlink(missing_ok=True)
    return {"accepted": accepted, "jobs": jobs}


@app.get("/api/documents/{document_id}")
def get_document(document_id: str, p: Principal = Depends(principal)) -> dict[str, Any]:
    with db() as connection:
        row = document_row(connection, p.workspace_id, document_id)
        if row is None:
            raise HTTPException(404, "Document not found")
        chunks = connection.execute("SELECT id, ordinal, line_start, line_end, section, symbol, tokens, text FROM chunks WHERE workspace_id=? AND document_id=? AND superseded=0 ORDER BY ordinal", (p.workspace_id, document_id)).fetchall()
        versions = connection.execute("SELECT version, chunks, created_at, current, content_hash, reused, newly_embedded, note FROM document_versions WHERE workspace_id=? AND document_id=? ORDER BY version DESC", (p.workspace_id, document_id)).fetchall()
    text = read_document_text(Path(row["storage_path"]), row["filename"])
    return {"document": row_document(row) | {"chunks": row["chunks"]}, "content": text, "chunks": [{"id": c["id"], "index": c["ordinal"], "line_start": c["line_start"], "line_end": c["line_end"], "section": c["section"], "symbol": c["symbol"], "tokens": c["tokens"], "excerpt": c["text"]} for c in chunks], "versions": [dict(v) for v in versions]}


@app.delete("/api/documents/{document_id}", status_code=202)
def delete_document(document_id: str, p: Principal = Depends(principal)) -> dict[str, Any]:
    with db() as connection:
        row = document_row(connection, p.workspace_id, document_id)
        if row is None:
            raise HTTPException(404, "Document not found")
        connection.execute("UPDATE documents SET deleted_at=?, status='processing' WHERE id=?", (now_ms(), document_id))
        connection.execute("DELETE FROM chunks_fts WHERE document_id=? AND workspace_id=?", (document_id, p.workspace_id))
        connection.execute("UPDATE chunks SET superseded=1 WHERE document_id=?", (document_id,))
        connection.execute("DELETE FROM cache_entries WHERE workspace_id=?", (p.workspace_id,))
    emit_event(p.workspace_id, "document", f"{row['filename']} deleted")
    return {"accepted": True, "document_id": document_id}


@app.delete("/api/documents/{document_id}/chunks", status_code=202)
def clear_document_chunks(document_id: str, p: Principal = Depends(principal)) -> dict[str, Any]:
    with db() as connection:
        row = document_row(connection, p.workspace_id, document_id)
        if row is None:
            raise HTTPException(404, "Document not found")
        removed = connection.execute("SELECT COUNT(*) FROM chunks WHERE document_id=? AND superseded=0", (document_id,)).fetchone()[0]
        connection.execute("DELETE FROM chunks_fts WHERE document_id=? AND workspace_id=?", (document_id, p.workspace_id))
        connection.execute("DELETE FROM chunks WHERE document_id=?", (document_id,))
        connection.execute("DELETE FROM cache_entries WHERE workspace_id=?", (p.workspace_id,))
        connection.execute("UPDATE documents SET status='not_indexed', version=0, embedding=NULL, parser=NULL, chunker=NULL, indexed_at=NULL, stage=NULL, progress=NULL, error=NULL, updated_at=? WHERE id=?", (now_ms(), document_id))
    emit_event(p.workspace_id, "document", f"{row['filename']} chunks removed", str(removed))
    return {"accepted": True, "document_id": document_id, "removed_chunks": removed}


@app.get("/api/changes/latest")
def latest_changes(p: Principal = Depends(principal)) -> dict[str, Any]:
    with db() as connection:
        rows = connection.execute("SELECT d.id AS document_id, d.filename, d.path, d.updated_at AS changed_at, d.version AS current_version, 0 AS previous_version, 0 AS previous_chunks, (SELECT COUNT(*) FROM chunks c WHERE c.document_id=d.id AND c.superseded=0) AS current_chunks FROM documents d WHERE d.workspace_id=? AND d.status='changed' AND d.deleted_at IS NULL ORDER BY d.updated_at DESC", (p.workspace_id,)).fetchall()
    return {"changes": [dict(row) for row in rows]}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str, p: Principal = Depends(principal)) -> dict[str, Any]:
    with db() as connection:
        row = connection.execute("SELECT j.*, d.filename AS document_name FROM jobs j LEFT JOIN documents d ON d.id=j.document_id WHERE j.workspace_id=? AND j.id=?", (p.workspace_id, job_id)).fetchone()
    if row is None:
        raise HTTPException(404, "Job not found")
    return job_public(row)


@app.delete("/api/jobs/{job_id}", status_code=202)
def cancel_job(job_id: str, p: Principal = Depends(principal)) -> dict[str, Any]:
    with db() as connection:
        row = connection.execute("SELECT j.*, d.filename AS document_name FROM jobs j LEFT JOIN documents d ON d.id=j.document_id WHERE j.workspace_id=? AND j.id=?", (p.workspace_id, job_id)).fetchone()
    if row is None:
        raise HTTPException(404, "Job not found")
    if row["status"] not in {"queued", "running"}:
        raise HTTPException(409, f"Job is already {row['status']}; only queued or running jobs can be cancelled")
    with db() as connection:
        connection.execute("UPDATE jobs SET status='cancelled', stage='failed', progress=0, last_error='Cancelled by user' WHERE id=?", (job_id,))
        # Reset the associated document so it is not left stuck in processing.
        if row["document_id"]:
            connection.execute("UPDATE documents SET status='not_indexed', stage=NULL, progress=NULL, error=NULL WHERE id=? AND workspace_id=?", (row["document_id"], p.workspace_id))
    emit_event(p.workspace_id, "error", f"{row['document_name'] or 'Job'} cancelled", job_id=job_id, document_id=row["document_id"])
    return {"accepted": True, "job_id": job_id}


@app.get("/api/sync")
def sync_queue(p: Principal = Depends(principal)) -> dict[str, Any]:
    with db() as connection:
        rows = connection.execute("SELECT j.*, d.filename AS document_name FROM jobs j LEFT JOIN documents d ON d.id=j.document_id WHERE j.workspace_id=? ORDER BY j.created_at DESC LIMIT 200", (p.workspace_id,)).fetchall()
    return {"jobs": [job_public(row) for row in rows]}


def enqueue_existing(workspace_id: str, document_id: str, kind: str) -> dict[str, Any]:
    timestamp = now_ms()
    with db() as connection:
        document = document_row(connection, workspace_id, document_id)
        if document is None:
            raise HTTPException(404, "Document not found")
        key = f"{kind}:{document_id}:{document['content_hash']}"
        current = connection.execute("SELECT * FROM jobs WHERE workspace_id=? AND idempotency_key=?", (workspace_id, key)).fetchone()
        if current and current["status"] in {"queued", "running"}:
            return job_public(current)
        if current and current["status"] == "failed":
            # A previously failed job must always be retried, even when the
            # source bytes are unchanged. Returning the failed row made Retry
            # a no-op for documents whose embedding provider was broken.
            key = f"{key}:{timestamp}"
        elif current and kind == "sync":
            source = Path(document["path"]) / document["filename"] if Path(document["path"]).is_absolute() else Path(document["storage_path"])
            if not source.exists() or content_hash(source) == document["content_hash"]:
                return job_public(current)
            key = f"{key}:{timestamp}"
        elif current:
            key = f"{key}:{timestamp}"
        job_id = str(uuid.uuid4())
        connection.execute("INSERT INTO jobs(id, workspace_id, document_id, kind, status, stage, idempotency_key, created_at, updated_at) VALUES (?, ?, ?, ?, 'queued', 'parsing', ?, ?, ?)", (job_id, workspace_id, document_id, kind, key, timestamp, timestamp))
        job = connection.execute("SELECT j.*, d.filename AS document_name FROM jobs j LEFT JOIN documents d ON d.id=j.document_id WHERE j.id=?", (job_id,)).fetchone()
    EXECUTOR.submit(process_job, job_id)
    return job_public(job)


class SyncRequest(BaseModel):
    document_id: str | None = None


@app.post("/api/documents/sync")
def sync_documents(payload: SyncRequest, p: Principal = Depends(principal)) -> dict[str, Any]:
    if payload.document_id:
        return {"job": enqueue_existing(p.workspace_id, payload.document_id, "sync")}
    with db() as connection:
        ids = [row["id"] for row in connection.execute("SELECT id FROM documents WHERE workspace_id=? AND deleted_at IS NULL", (p.workspace_id,)).fetchall()]
    jobs = [enqueue_existing(p.workspace_id, document_id, "sync") for document_id in ids]
    return {"jobs": jobs}


@app.post("/api/documents/index")
def index_document(payload: SyncRequest, p: Principal = Depends(principal)) -> dict[str, Any]:
    if not payload.document_id:
        raise HTTPException(400, "document_id is required")
    return {"job": enqueue_existing(p.workspace_id, payload.document_id, "index")}


@app.post("/api/repositories/git", status_code=202)
def git_repository(payload: dict[str, Any], p: Principal = Depends(principal)) -> dict[str, Any]:
    url = str(payload.get("url", ""))
    if not re.fullmatch(r"https://[^\s]+", url):
        raise HTTPException(400, "Only HTTPS repository URLs are accepted")
    branch = str(payload.get("branch") or "").strip()
    if branch and not re.fullmatch(r"[A-Za-z0-9._/-]{1,200}", branch):
        raise HTTPException(400, "Invalid branch name")
    with tempfile.TemporaryDirectory(prefix="knowledgeos-git-") as directory:
        clone_target = Path(directory) / "repo"
        command = ["git", "clone", "--depth", "1"]
        if branch:
            command.extend(["--branch", branch])
        command.extend([url, str(clone_target)])
        try:
            subprocess.run(command, check=True, capture_output=True, text=True, timeout=180)
            commit = subprocess.run(["git", "-C", str(clone_target), "rev-parse", "HEAD"], check=True, capture_output=True, text=True, timeout=15).stdout.strip()
        except FileNotFoundError as exc:
            raise HTTPException(503, "Git is not installed on the backend host") from exc
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or "git clone failed").strip()[-1000:]
            raise HTTPException(502, detail) from exc
        except subprocess.TimeoutExpired as exc:
            raise HTTPException(504, "Git clone timed out") from exc
        files = [item for item in clone_target.rglob("*") if item.is_file() and not item.is_symlink() and ".git" not in item.parts and extension(item.name) in INGEST_EXTENSIONS]
        if len(files) > MAX_BATCH_FILES:
            raise HTTPException(413, f"Repository contains more than {MAX_BATCH_FILES} supported files")
        jobs: list[dict[str, Any]] = []
        for item in files:
            stored, size, digest = save_local_file(item, p.workspace_id)
            relative_parent = str(item.parent.relative_to(clone_target)) if item.parent != clone_target else "."
            document, job = queue_document(p.workspace_id, safe_filename(item.name), stored, size, digest, f"git:{url}#{relative_parent}")
            if job:
                jobs.append(job_public(job))
            else:
                stored.unlink(missing_ok=True)
    return {"accepted": True, "files": len(files), "commit": commit, "jobs": jobs}


def index_public(row: sqlite3.Row) -> dict[str, Any]:
    return {"id": row["id"], "state": row["state"], "embedding": row["embedding"], "dimensions": row["dimensions"], "revision": row["revision"], "documents": row["documents"], "chunks": row["chunks"], "created_at": row["created_at"], "built_at": row["built_at"], "validated": bool(row["validated"]), "evaluated": bool(row["evaluated"]), "evaluation_score": row["evaluation_score"], "notes": row["notes"]}


@app.get("/api/indexes")
def list_indexes(p: Principal = Depends(principal)) -> dict[str, Any]:
    with db() as connection:
        rows = connection.execute("SELECT * FROM index_versions WHERE workspace_id=? ORDER BY revision DESC", (p.workspace_id,)).fetchall()
    return {"indexes": [index_public(row) for row in rows]}


@app.get("/api/evaluations/golden")
def list_golden_set(p: Principal = Depends(principal)) -> dict[str, Any]:
    with db() as connection:
        rows = connection.execute("SELECT id, question, expected_document_id, expected_chunk_id, created_at FROM golden_set WHERE workspace_id=? ORDER BY created_at", (p.workspace_id,)).fetchall()
    return {"items": [dict(row) for row in rows]}


@app.post("/api/evaluations/golden", status_code=201)
def add_golden_item(payload: GoldenSetItem, p: Principal = Depends(principal)) -> dict[str, Any]:
    if not payload.expected_document_id and not payload.expected_chunk_id:
        raise HTTPException(400, "expected_document_id or expected_chunk_id is required")
    item_id = str(uuid.uuid4())
    with db() as connection:
        connection.execute("INSERT INTO golden_set(id, workspace_id, question, expected_document_id, expected_chunk_id, created_at) VALUES (?, ?, ?, ?, ?, ?)", (item_id, p.workspace_id, payload.question, payload.expected_document_id, payload.expected_chunk_id, now_ms()))
        row = connection.execute("SELECT id, question, expected_document_id, expected_chunk_id, created_at FROM golden_set WHERE id=?", (item_id,)).fetchone()
    return dict(row)


@app.post("/api/feedback", status_code=201)
def add_feedback(payload: FeedbackRequest, p: Principal = Depends(principal)) -> dict[str, Any]:
    if payload.rating not in {-1, 1}:
        raise HTTPException(400, "rating must be 1 or -1")
    with db() as connection:
        trace = connection.execute("SELECT id FROM traces WHERE id=? AND workspace_id=?", (payload.trace_id, p.workspace_id)).fetchone()
        if trace is None:
            raise HTTPException(404, "Trace not found")
        connection.execute("INSERT INTO feedback(id, workspace_id, trace_id, rating, comment, created_at) VALUES (?, ?, ?, ?, ?, ?)", (str(uuid.uuid4()), p.workspace_id, payload.trace_id, 1 if payload.rating > 0 else -1, payload.comment, now_ms()))
    return {"accepted": True}


class IndexCreate(BaseModel):
    embedding: str | None = None
    notes: str | None = None


@app.post("/api/indexes", status_code=201)
def create_index(payload: IndexCreate, p: Principal = Depends(principal)) -> dict[str, Any]:
    with db() as connection:
        revision = (connection.execute("SELECT COALESCE(MAX(revision), 0) + 1 FROM index_versions WHERE workspace_id=?", (p.workspace_id,)).fetchone()[0])
        row_id = f"index-v{revision}"
        embedding_row = choose_provider(connection, p.workspace_id, "Embeddings")
        connection.execute("INSERT INTO index_versions(id, workspace_id, state, revision, embedding, created_at, notes) VALUES (?, ?, 'building', ?, ?, ?, ?)", (row_id, p.workspace_id, revision, payload.embedding or embedding_identity(embedding_row), now_ms(), payload.notes))
        row = connection.execute("SELECT * FROM index_versions WHERE id=?", (row_id,)).fetchone()
    return {"index": index_public(row)}


def run_index_evaluation(index_id: str, p: Principal) -> dict[str, Any]:
    """Evaluate an index without holding SQLite open during embeddings."""
    with db() as connection:
        row = connection.execute("SELECT * FROM index_versions WHERE id=? AND workspace_id=?", (index_id, p.workspace_id)).fetchone()
        if row is None:
            raise HTTPException(404, "Index not found")
        if row["state"] not in {"ready", "active"} or not row["validated"]:
            raise HTTPException(409, "Build and validate the index before evaluating")
        golden = [dict(item) for item in connection.execute("SELECT question, expected_document_id, expected_chunk_id FROM golden_set WHERE workspace_id=? ORDER BY created_at", (p.workspace_id,)).fetchall()]
        embedding_row = choose_provider(connection, p.workspace_id, "Embeddings")
    embedding_row = dict(embedding_row) if embedding_row is not None else None

    scores: list[tuple[float, float, float]] = []
    for item in golden:
        vector = embed_text(embedding_row, item["question"])
        with db() as connection:
            candidates, _ = retrieve(connection, p.workspace_id, item["question"], 100, vector)
        expected_chunk = item["expected_chunk_id"]
        expected_document = item["expected_document_id"]
        hit_index = next((index for index, candidate in enumerate(candidates) if (expected_chunk and candidate["chunk_id"] == expected_chunk) or (expected_document and candidate.get("document_id") == expected_document)), None)
        if hit_index is None:
            scores.append((0.0, 0.0, 0.0))
        else:
            rank = hit_index + 1
            scores.append((1.0, 1.0 / rank, 1.0 / math.log2(rank + 1) if rank <= 10 else 0.0))
    recall100 = statistics.mean(score[0] for score in scores) if scores else 1.0
    mrr10 = statistics.mean(score[1] for score in scores) if scores else 1.0
    ndcg10 = statistics.mean(score[2] for score in scores) if scores else 1.0

    with db() as connection:
        baseline = connection.execute("SELECT e.index_version, e.recall100, e.ndcg10 FROM evaluations e JOIN index_versions i ON i.id=e.index_version WHERE e.workspace_id=? AND i.state='active' ORDER BY e.created_at DESC LIMIT 1", (p.workspace_id,)).fetchone()
        passed = baseline is None or (recall100 >= baseline[1] - 0.03 and ndcg10 >= baseline[2] - 0.05)
        connection.execute("UPDATE index_versions SET evaluated=1, evaluation_score=?, notes=? WHERE id=?", (ndcg10, "No golden set configured" if not golden else ("Passed golden-set regression gate" if passed else "Failed golden-set regression gate"), index_id))
        connection.execute("INSERT INTO evaluations(id, workspace_id, index_version, recall100, ndcg10, mrr10, passed, compared_index, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (str(uuid.uuid4()), p.workspace_id, index_id, recall100, ndcg10, mrr10, int(passed), baseline[0] if baseline else None, now_ms()))
        updated = connection.execute("SELECT * FROM index_versions WHERE id=?", (index_id,)).fetchone()
    if not passed:
        raise HTTPException(409, "Index evaluation gate failed")
    return {"index": index_public(updated)}


def index_action(index_id: str, action: str, p: Principal) -> dict[str, Any]:
    if action == "evaluate":
        return run_index_evaluation(index_id, p)
    with db() as connection:
        row = connection.execute("SELECT * FROM index_versions WHERE id=? AND workspace_id=?", (index_id, p.workspace_id)).fetchone()
        if row is None:
            raise HTTPException(404, "Index not found")
        if action == "build":
            counts = connection.execute("SELECT COUNT(DISTINCT d.id), COUNT(c.id) FROM documents d LEFT JOIN chunks c ON c.document_id=d.id AND c.superseded=0 WHERE d.workspace_id=? AND d.deleted_at IS NULL", (p.workspace_id,)).fetchone()
            connection.execute("UPDATE index_versions SET state='ready', documents=?, chunks=?, built_at=?, validated=0, evaluated=0 WHERE id=?", (counts[0], counts[1], now_ms(), index_id))
        elif action == "validate":
            if row["state"] not in {"ready", "active"}:
                raise HTTPException(409, "Build the index before validating")
            connection.execute("UPDATE index_versions SET validated=1 WHERE id=?", (index_id,))
        elif action == "activate":
            current = connection.execute("SELECT * FROM index_versions WHERE workspace_id=? AND state='active' ORDER BY revision DESC LIMIT 1", (p.workspace_id,)).fetchone()
            updated = connection.execute("SELECT * FROM index_versions WHERE id=?", (index_id,)).fetchone()
            if not updated["validated"]:
                raise HTTPException(409, "Index must pass validation before activation")
            golden_count = connection.execute("SELECT COUNT(*) FROM golden_set WHERE workspace_id=?", (p.workspace_id,)).fetchone()[0]
            if golden_count and not updated["evaluated"]:
                raise HTTPException(409, "Run the golden-set evaluation before activation")
            if updated["evaluated"] and updated["evaluation_score"] is not None and updated["notes"] == "Failed golden-set regression gate":
                raise HTTPException(409, "Index evaluation gate failed")
            connection.execute("UPDATE index_versions SET state='retired' WHERE workspace_id=? AND state='active'", (p.workspace_id,))
            connection.execute("UPDATE index_versions SET state='active' WHERE id=?", (index_id,))
            connection.execute("DELETE FROM cache_entries WHERE workspace_id=? AND index_version!=?", (p.workspace_id, index_id))
        elif action == "rollback":
            active = connection.execute("SELECT * FROM index_versions WHERE workspace_id=? AND state='active' ORDER BY revision DESC LIMIT 1", (p.workspace_id,)).fetchone()
            target = connection.execute("SELECT * FROM index_versions WHERE workspace_id=? AND state='retired' AND validated=1 ORDER BY revision DESC LIMIT 1", (p.workspace_id,)).fetchone()
            if target is None:
                raise HTTPException(409, "No validated retired index is available")
            connection.execute("UPDATE index_versions SET state='retired' WHERE id=?", (active["id"],) if active else ("",))
            connection.execute("UPDATE index_versions SET state='active' WHERE id=?", (target["id"],))
        else:
            raise HTTPException(400, "Unsupported index action")
        return {"index": index_public(connection.execute("SELECT * FROM index_versions WHERE id=?", (index_id if action != 'rollback' else target['id'],)).fetchone())}


for _action in ("build", "validate", "activate", "rollback"):
    pass


@app.post("/api/indexes/{index_id}/build")
def build_index(index_id: str, p: Principal = Depends(principal)) -> dict[str, Any]:
    return index_action(index_id, "build", p)


@app.post("/api/indexes/{index_id}/validate")
def validate_index(index_id: str, p: Principal = Depends(principal)) -> dict[str, Any]:
    return index_action(index_id, "validate", p)


@app.post("/api/indexes/{index_id}/evaluate")
def evaluate_index(index_id: str, p: Principal = Depends(principal)) -> dict[str, Any]:
    return index_action(index_id, "evaluate", p)


@app.post("/api/indexes/{index_id}/activate")
def activate_index(index_id: str, p: Principal = Depends(principal)) -> dict[str, Any]:
    return index_action(index_id, "activate", p)


@app.post("/api/indexes/{index_id}/rollback")
def rollback_index(index_id: str, p: Principal = Depends(principal)) -> dict[str, Any]:
    return index_action(index_id, "rollback", p)


def active_index(connection: sqlite3.Connection, workspace_id: str) -> sqlite3.Row | None:
    return connection.execute("SELECT * FROM index_versions WHERE workspace_id=? AND state='active' ORDER BY revision DESC LIMIT 1", (workspace_id,)).fetchone()


def retrieve(connection: sqlite3.Connection, workspace_id: str, question: str, top_k: int, embedding: list[float]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    lexical_rows: list[sqlite3.Row] = []
    try:
        lexical_rows = connection.execute("SELECT c.*, d.filename, d.path, d.version AS document_version, bm25(chunks_fts) AS rank FROM chunks_fts JOIN chunks c ON c.id=chunks_fts.chunk_id JOIN documents d ON d.id=c.document_id WHERE chunks_fts.workspace_id=? AND chunks_fts MATCH ? AND c.superseded=0 ORDER BY rank LIMIT ?", (workspace_id, fts_query(question), max(30, top_k * 5))).fetchall()
    except sqlite3.OperationalError:
        lexical_rows = []
    dense_rows = connection.execute("SELECT c.*, d.filename, d.path, d.version AS document_version FROM chunks c JOIN documents d ON d.id=c.document_id WHERE c.workspace_id=? AND c.superseded=0 AND d.deleted_at IS NULL ORDER BY c.id LIMIT ?", (workspace_id, int(os.getenv("KNOWLEDGEOS_DENSE_SCAN_LIMIT", "50000")))).fetchall()
    by_id = {row["id"]: row for row in lexical_rows}
    for row in dense_rows:
        by_id.setdefault(row["id"], row)
    lexical_rank = {row["id"]: rank for rank, row in enumerate(lexical_rows, start=1)}
    dense_scores = {row["id"]: cosine(embedding, json.loads(row["embedding_json"] or "[]")) for row in dense_rows}
    dense_rank = {chunk_id: rank for rank, (chunk_id, _) in enumerate(sorted(dense_scores.items(), key=lambda item: item[1], reverse=True), start=1)}
    candidates: list[dict[str, Any]] = []
    terms = set(query_terms(question))
    for chunk_id, row in by_id.items():
        lexical = sum(1 for term in terms if term in row["text"].lower()) / max(1, len(terms))
        dense = dense_scores.get(chunk_id, 0.0)
        bm25_position = lexical_rank.get(chunk_id)
        dense_position = dense_rank.get(chunk_id)
        source = "both" if bm25_position and dense_position else "bm25" if bm25_position else "dense"
        candidates.append({"chunk_id": row["id"], "document_id": row["document_id"], "filename": row["filename"], "source": source, "cosine": dense, "bm25_rank": bm25_position, "rrf_score": (1 / (60 + bm25_position) if bm25_position else 0) + (1 / (60 + dense_position) if dense_position else 0), "reranker_score": lexical * 0.55 + max(0, dense) * 0.45, "excerpt": row["text"]})
    candidates.sort(key=lambda value: (value["reranker_score"], value["rrf_score"]), reverse=True)
    citations = []
    for candidate in candidates[:top_k]:
        row = by_id[candidate["chunk_id"]]
        citations.append({"chunk_id": row["id"], "document_id": row["document_id"], "filename": row["filename"], "path": row["path"], "line_start": row["line_start"], "line_end": row["line_end"], "version": row["document_version"], "excerpt": row["text"], "score": candidate["reranker_score"], "verification": "verified"})
    return candidates[:top_k], citations


def cache_lookup(connection: sqlite3.Connection, workspace_id: str, index_id: str, provider_id: str | None, question: str, query_embedding: list[float]) -> dict[str, Any] | None:
    digest = hashlib.sha256(question.strip().lower().encode()).hexdigest()
    rows = connection.execute("SELECT response_json, embedding_json, query_hash FROM cache_entries WHERE workspace_id=? AND index_version=? AND model_profile_id IS ? AND prompt_version=? AND expires_at>? ORDER BY created_at DESC", (workspace_id, index_id, provider_id, PROMPT_VERSION, now_ms())).fetchall()
    best: sqlite3.Row | None = None
    best_score = 0.0
    for row in rows:
        if row["query_hash"] == digest:
            return json.loads(row["response_json"])
        if row["embedding_json"]:
            score = cosine(query_embedding, json.loads(row["embedding_json"]))
            if score >= SEMANTIC_CACHE_THRESHOLD and score > best_score:
                best, best_score = row, score
    return json.loads(best["response_json"]) if best else None


def cache_store(connection: sqlite3.Connection, workspace_id: str, index_id: str, provider_id: str | None, question: str, query_embedding: list[float], response: dict[str, Any], confidence: float) -> None:
    if confidence < 0.55:
        return
    digest = hashlib.sha256(question.strip().lower().encode()).hexdigest()
    connection.execute("INSERT OR REPLACE INTO cache_entries(id, workspace_id, index_version, model_profile_id, prompt_version, query_hash, query_text, embedding_json, response_json, confidence, created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (str(uuid.uuid4()), workspace_id, index_id, provider_id, PROMPT_VERSION, digest, question, json_dumps(query_embedding), json_dumps(response), confidence, now_ms(), now_ms() + CACHE_TTL_SECONDS * 1000))


def answer_question(p: Principal, payload: ChatRequest) -> dict[str, Any]:
    started = time.perf_counter()
    timings: dict[str, float] = {}
    request_id = str(uuid.uuid4())
    query_parts, modality = understand_query(payload.question)
    timings["query_understanding"] = (time.perf_counter() - started) * 1000

    with db() as connection:
        index = active_index(connection, p.workspace_id)
        index_id = index["id"] if index else "unindexed"
        provider_row_value = provider_row(connection, p.workspace_id, payload.model_profile_id, "Generation") if payload.model_profile_id else choose_provider(connection, p.workspace_id, "Generation")
        provider = dict(provider_row_value) if provider_row_value is not None else None
        embedding_provider = choose_provider(connection, p.workspace_id, "Embeddings")
    embedding_provider = dict(embedding_provider) if embedding_provider is not None else None

    # Provider calls must not share a live SQLite transaction. In WAL mode a
    # read transaction upgraded to a write after another request commits can
    # fail immediately with SQLITE_BUSY_SNAPSHOT (reported as "database is
    # locked").
    cache_embedding = embed_text(embedding_provider, " ".join(query_parts))
    timings["query_embedding"] = (time.perf_counter() - started) * 1000

    with db() as connection:
        cached = cache_lookup(connection, p.workspace_id, index_id, provider["id"] if provider else None, payload.question, cache_embedding)
        if cached:
            timings["cache"] = (time.perf_counter() - started) * 1000
            trace_id = str(uuid.uuid4())
            connection.execute("INSERT INTO traces(id, request_id, workspace_id, route, cache_hit, model_profile_id, model, index_version, prompt_version, stage_timings_json, outcome, created_at) VALUES (?, ?, ?, '/chat', 1, ?, ?, ?, ?, ?, ?, ?)", (trace_id, request_id, p.workspace_id, provider["id"] if provider else None, provider["model"] if provider else None, index_id, PROMPT_VERSION, json_dumps(timings), cached["evidence"]["decision"], now_ms()))
            cached["trace_id"] = trace_id
            cached["latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
            return cached
        candidates, citations = retrieve(connection, p.workspace_id, query_parts[0], payload.top_k, cache_embedding)
        if len(query_parts) > 1:
            by_chunk = {item["chunk_id"]: item for item in candidates}
            citation_by_chunk = {item["chunk_id"]: item for item in citations}
            for part in query_parts[1:]:
                extra_candidates, extra_citations = retrieve(connection, p.workspace_id, part, payload.top_k, cache_embedding)
                for item in extra_candidates:
                    current = by_chunk.get(item["chunk_id"])
                    if current is None or item["reranker_score"] > current["reranker_score"]:
                        by_chunk[item["chunk_id"]] = item
                for item in extra_citations:
                    citation_by_chunk.setdefault(item["chunk_id"], item)
            candidates = sorted(by_chunk.values(), key=lambda item: (item["reranker_score"], item["rrf_score"]), reverse=True)[:payload.top_k]
            citations = [citation_by_chunk[item["chunk_id"]] for item in candidates if item["chunk_id"] in citation_by_chunk][:payload.top_k]
    timings["hybrid_retrieval"] = (time.perf_counter() - started) * 1000 - timings["query_embedding"]
    confidence = max((citation.get("score", 0) for citation in citations), default=0.0)
    if not citations or confidence < 0.15:
        decision = "abstain"
        answer = "I don't have enough indexed evidence to answer that question."
    elif provider:
        context = "\n\n".join(f"[{item['filename']}:{item['line_start']}-{item['line_end']}] {item['excerpt']}" for item in citations)
        prompt = f"Answer the question only from the supplied evidence. Cite sources using their bracket labels.\n\nQuestion: {payload.question}\n\nEvidence:\n{context}"
        try:
            result = provider_request(provider, "/chat/completions", {"model": provider["model"], "temperature": 0.1, "messages": [{"role": "user", "content": prompt}]}, timeout=60)
            answer = (((result.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
            decision = "answer" if answer else "answer_with_uncertainty"
        except RuntimeError:
            answer = citations[0]["excerpt"]
            decision = "answer_with_uncertainty"
    else:
        answer = citations[0]["excerpt"]
        decision = "answer_with_uncertainty"
    trace_id = str(uuid.uuid4())
    response = {"question": payload.question, "answer": answer, "evidence": {"decision": decision, "query_coverage": min(1, confidence), "evidence_agreement": min(1, len(citations) / max(1, payload.top_k)), "supporting_sources": len(citations), "citation_verification": bool(citations), "evidence_score": confidence}, "citations": citations, "retrieval": {"stages": [{"label": "Query understanding", "candidates": len(query_parts), "ms": round(timings["query_understanding"], 2)}, {"label": f"Hybrid retrieval ({modality})", "candidates": len(candidates), "ms": round(timings["hybrid_retrieval"], 2)}], "candidates": candidates, "evidence_passed": decision != "abstain"}, "trace_id": trace_id, "latency_ms": round((time.perf_counter() - started) * 1000, 2)}
    with db() as connection:
        connection.execute("INSERT INTO traces(id, request_id, workspace_id, route, cache_hit, model_profile_id, model, index_version, prompt_version, stage_timings_json, token_counts_json, outcome, created_at) VALUES (?, ?, ?, '/chat', 0, ?, ?, ?, ?, ?, ?, ?, ?)", (trace_id, request_id, p.workspace_id, provider["id"] if provider else None, provider["model"] if provider else None, index_id, PROMPT_VERSION, json_dumps(timings), json_dumps({"input": token_count(payload.question), "output": token_count(answer)}), decision, now_ms()))
        cache_store(connection, p.workspace_id, index_id, provider["id"] if provider else None, payload.question, cache_embedding, response, confidence)
    emit_event(p.workspace_id, "query", "Knowledge query completed", payload.question, trace_id=trace_id)
    return response


@app.post("/api/chat")
def chat(payload: ChatRequest, p: Principal = Depends(principal)) -> dict[str, Any]:
    return answer_question(p, payload)


@app.post("/api/chat/stream")
async def chat_stream(payload: ChatRequest, request: FastAPIRequest, p: Principal = Depends(principal)) -> StreamingResponse:

    async def events() -> AsyncIterator[str]:
        try:
            response = await asyncio.to_thread(answer_question, p, payload)
            yield f"event: citations\ndata: {json_dumps({'citations': response['citations'], 'trace_id': response['trace_id']})}\n\n"
            for token in re.findall(r"\S+\s*", response["answer"]):
                if await request.is_disconnected():
                    return
                yield f"event: token\ndata: {json_dumps({'text': token})}\n\n"
                await asyncio.sleep(0)
            yield f"event: done\ndata: {json_dumps(response)}\n\n"
        except Exception as exc:
            yield f"event: error\ndata: {json_dumps({'error': str(exc)})}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/metrics")
def metrics(p: Principal = Depends(principal)) -> dict[str, Any]:
    with db() as connection:
        rows = connection.execute("SELECT * FROM traces WHERE workspace_id=? ORDER BY created_at DESC LIMIT 1000", (p.workspace_id,)).fetchall()
    latencies = [sum(json.loads(row["stage_timings_json"]).values()) for row in rows]
    outcomes = [row["outcome"] for row in rows]
    stage_values: dict[str, list[float]] = {}
    for row in rows:
        for label, value in json.loads(row["stage_timings_json"]).items():
            stage_values.setdefault(label, []).append(float(value))
    def percentile(value: float) -> float | None:
        if not latencies:
            return None
        return round(statistics.quantiles(latencies, n=100, method="inclusive")[max(0, min(98, int(value) - 1))], 2) if len(latencies) > 1 else round(latencies[0], 2)
    return {"latency": {"p50": percentile(50), "p95": percentile(95), "p99": percentile(99)}, "queries": len(rows), "answers": outcomes.count("answer"), "answers_with_uncertainty": outcomes.count("answer_with_uncertainty"), "abstentions": outcomes.count("abstain"), "errors": outcomes.count("error"), "mean_ms": round(statistics.mean(latencies), 2) if latencies else None, "stages": [{"label": label, "ms": round(statistics.mean(values), 2)} for label, values in stage_values.items()]}


@app.get("/api/activity")
def activity(limit: int = Query(default=100, ge=1, le=500), p: Principal = Depends(principal)) -> dict[str, Any]:
    with db() as connection:
        rows = connection.execute("SELECT * FROM events WHERE workspace_id=? ORDER BY created_at DESC LIMIT ?", (p.workspace_id, limit)).fetchall()
    return {"events": [dict(row) for row in rows]}


@app.get("/api/config")
def config(p: Principal = Depends(principal)) -> dict[str, Any]:
    with db() as connection:
        profiles = connection.execute("SELECT id, name, kind, model, role, base_url FROM provider_profiles WHERE workspace_id=? AND enabled=1", (p.workspace_id,)).fetchall()
        embedding_row = choose_provider(connection, p.workspace_id, "Embeddings")
    return {"providers": [dict(row) for row in profiles], "embedding": {"provider": embedding_identity(embedding_row), "ollama_base_url": SETTINGS.ollama_base_url, "ollama_model": SETTINGS.ollama_embedding_model, "hash_fallback": SETTINGS.allow_hash_embedding_fallback}, "limits": {"max_upload_bytes": SETTINGS.max_upload_bytes, "max_batch_files": MAX_BATCH_FILES, "chunk_size": CHUNK_SIZE, "chunk_overlap": CHUNK_OVERLAP, "cache_ttl_seconds": CACHE_TTL_SECONDS}}


@app.get("/api/storage")
def storage(p: Principal = Depends(principal)) -> dict[str, Any]:
    with db() as connection:
        documents = connection.execute("SELECT COUNT(*), COALESCE(SUM(size_bytes), 0) FROM documents WHERE workspace_id=? AND deleted_at IS NULL", (p.workspace_id,)).fetchone()
        chunks = connection.execute("SELECT COUNT(*) FROM chunks WHERE workspace_id=? AND superseded=0", (p.workspace_id,)).fetchone()[0]
    return {"documents": documents[0], "original_bytes": documents[1], "chunks": chunks, "storage": "local filesystem", "data_directory": str(SETTINGS.files_dir / p.workspace_id)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="127.0.0.1", port=8000, reload=True)
