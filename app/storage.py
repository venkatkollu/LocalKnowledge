from __future__ import annotations

from contextlib import contextmanager
import json
import sqlite3
import time
import uuid

from app.chunking import CHUNKER_VERSION, sha256
from app.embeddings import HashEmbedding, LocalEmbedding, cosine, validate_vectors
from app.parsing import PARSER_VERSION
from app.security import Principal, acl_clause

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
 id INTEGER PRIMARY KEY, path TEXT UNIQUE NOT NULL, filename TEXT NOT NULL,
 content_hash TEXT NOT NULL, size INTEGER NOT NULL, modified REAL NOT NULL,
 version INTEGER NOT NULL DEFAULT 1, status TEXT NOT NULL DEFAULT 'indexed',
 error TEXT, updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS document_versions (
 id INTEGER PRIMARY KEY, document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
 version INTEGER NOT NULL, content_hash TEXT NOT NULL, size INTEGER NOT NULL,
 parser_version TEXT NOT NULL, chunker_version TEXT NOT NULL,
 embedding_model TEXT NOT NULL, created_at REAL NOT NULL, UNIQUE(document_id,version));
CREATE TABLE IF NOT EXISTS ingestion_jobs (
 id TEXT PRIMARY KEY, kind TEXT NOT NULL, status TEXT NOT NULL,
 total INTEGER DEFAULT 0, completed INTEGER DEFAULT 0, failed INTEGER DEFAULT 0,
 error TEXT, summary TEXT, created_at REAL NOT NULL, started_at REAL, finished_at REAL);
CREATE TABLE IF NOT EXISTS rag_indexes (
 id TEXT PRIMARY KEY, name TEXT UNIQUE NOT NULL, status TEXT NOT NULL,
 embedding_provider TEXT NOT NULL, embedding_model TEXT NOT NULL,
 embedding_dimension INTEGER NOT NULL, config TEXT NOT NULL,
 validated INTEGER NOT NULL DEFAULT 0, validation TEXT, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS rag_state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS rag_parents (
 id INTEGER PRIMARY KEY, version_id INTEGER NOT NULL REFERENCES document_versions(id),
 content TEXT NOT NULL, metadata TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS rag_chunks (
 id INTEGER PRIMARY KEY, document_id INTEGER NOT NULL REFERENCES documents(id),
 version_id INTEGER NOT NULL REFERENCES document_versions(id),
 parent_id INTEGER REFERENCES rag_parents(id), ordinal INTEGER NOT NULL,
 chunk_hash TEXT NOT NULL, raw_content TEXT NOT NULL, contextual_content TEXT NOT NULL,
 contextual_description TEXT NOT NULL, metadata TEXT NOT NULL, embedding TEXT NOT NULL,
 embedding_model TEXT NOT NULL, embedding_dimension INTEGER NOT NULL,
 pipeline_hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS rag_members (
 index_id TEXT NOT NULL REFERENCES rag_indexes(id),
 chunk_id INTEGER NOT NULL REFERENCES rag_chunks(id),
 PRIMARY KEY(index_id,chunk_id));
CREATE VIRTUAL TABLE IF NOT EXISTS rag_fts USING fts5(contextual_content, filename, section);
CREATE TABLE IF NOT EXISTS rag_traces (
 trace_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, owner_id TEXT NOT NULL,
 index_id TEXT NOT NULL, payload TEXT NOT NULL, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS rag_evaluations (
 id INTEGER PRIMARY KEY, tenant_id TEXT NOT NULL, owner_id TEXT NOT NULL,
 payload TEXT NOT NULL, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS query_logs (
 id INTEGER PRIMARY KEY, request_id TEXT NOT NULL, query TEXT NOT NULL,
 latency_ms REAL NOT NULL, retrieval_ms REAL NOT NULL, generation_ms REAL NOT NULL,
 result_count INTEGER NOT NULL, model TEXT NOT NULL, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS evaluation_results (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL, recall_at_5 REAL, mrr REAL,
 questions INTEGER NOT NULL, details TEXT NOT NULL, created_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS rag_chunks_doc ON rag_chunks(document_id,version_id);
CREATE INDEX IF NOT EXISTS rag_members_chunk ON rag_members(chunk_id);
CREATE INDEX IF NOT EXISTS rag_traces_time ON rag_traces(created_at);
"""


class SQLiteStorage:
    def __init__(self, settings):
        self.settings = settings

    @contextmanager
    def connect(self):
        self.settings.db_path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self.settings.db_path, timeout=30)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("PRAGMA busy_timeout=30000")
        try:
            with con:
                yield con
        finally:
            con.close()

    def initialize(self):
        self.settings.knowledge_dir.mkdir(parents=True, exist_ok=True)
        with self.connect() as con:
            con.execute("PRAGMA journal_mode=WAL")
            # Additive migration. Legacy chunks and FTS are retained untouched.
            con.executescript(SCHEMA)
            additions = {
                "rag_indexes": {"revision": "INTEGER NOT NULL DEFAULT 0"},
                "documents": {"tenant_id": "TEXT NOT NULL DEFAULT 'local'", "owner_id": "TEXT NOT NULL DEFAULT 'local'",
                              "visibility": "TEXT NOT NULL DEFAULT 'private'", "permissions": "TEXT NOT NULL DEFAULT '[]'",
                              "repository": "TEXT"},
                "document_versions": {"pipeline_hash": "TEXT", "index_id": "TEXT"},
                "ingestion_jobs": {"summary": "TEXT", "tenant_id": "TEXT NOT NULL DEFAULT 'local'",
                                   "owner_id": "TEXT NOT NULL DEFAULT 'local'", "payload": "TEXT", "stage": "TEXT",
                                   "stage_history": "TEXT NOT NULL DEFAULT '[]'"},
            }
            for table, columns in additions.items():
                existing = {row[1] for row in con.execute(f"PRAGMA table_info({table})")}
                for name, definition in columns.items():
                    if name not in existing:
                        con.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
            con.execute("INSERT OR REPLACE INTO rag_state VALUES('schema_version','2')")

    def indexes(self) -> list[dict]:
        with self.connect() as con:
            rows = con.execute("SELECT * FROM rag_indexes ORDER BY created_at").fetchall()
        return [self.decode_index(row) for row in rows]

    @staticmethod
    def decode_index(row) -> dict:
        value = dict(row)
        value["config"] = json.loads(value["config"])
        if value.get("validation"):
            value["validation"] = json.loads(value["validation"])
        return value

    def active_index(self) -> dict | None:
        with self.connect() as con:
            row = con.execute("SELECT i.* FROM rag_indexes i JOIN rag_state s ON s.value=i.id WHERE s.key='active_index'").fetchone()
        return self.decode_index(row) if row else None

    def get_index(self, index_id: str) -> dict:
        with self.connect() as con:
            row = con.execute("SELECT * FROM rag_indexes WHERE id=? OR name=?", (index_id, index_id)).fetchone()
        if not row:
            raise KeyError("Index not found")
        return self.decode_index(row)

    def create_index(self, name: str, config=None) -> dict:
        settings = config or self.settings
        cfg = settings.embeddings
        if cfg.provider == "hash":
            embedding = HashEmbedding(cfg.dimension)
        else:
            embedding = LocalEmbedding(settings, cfg.provider, cfg.model)
            try:
                embedding.embed(["embedding dimension probe"])
            except Exception:
                if not cfg.allow_initial_hash_fallback:
                    raise
                embedding = HashEmbedding(cfg.dimension)
        index_id = str(uuid.uuid4())
        snapshot = settings.model_dump(mode="json")
        snapshot["registry"] = {"parser_version": PARSER_VERSION, "chunker_version": CHUNKER_VERSION,
                                "contextualizer_version": "context-2.0", "reranker_model": settings.reranker.model if settings.reranker.provider == "cross_encoder" else "cross-signal-v2",
                                "generation_model": settings.generation.model}
        snapshot["registry"]["embedding_revision"] = embedding.revision() if embedding.provider != "hash" else "blake2b-token-hash-v2"
        with self.connect() as con:
            con.execute("INSERT INTO rag_indexes(id,name,status,embedding_provider,embedding_model,embedding_dimension,config,created_at) VALUES(?,?,?,?,?,?,?,?)",
                        (index_id, name, "building", embedding.provider, embedding.model, embedding.dimension, json.dumps(snapshot), time.time()))
        return self.get_index(index_id)

    @staticmethod
    def pipeline_hash(index: dict) -> str:
        config = index["config"]
        values = {"registry": config["registry"], "chunk_size": config["chunk_size"], "chunk_overlap": config["chunk_overlap"],
                  "contextual_chunking": config["retrieval"]["contextual_chunking"],
                  "embedding": [index["embedding_provider"], index["embedding_model"], index["embedding_dimension"]]}
        return sha256(json.dumps(values, sort_keys=True).encode())

    def validate_index(self, index_id: str) -> dict:
        index = self.get_index(index_id)
        with self.connect() as con:
            rows = con.execute("SELECT c.*,v.parser_version,v.chunker_version FROM rag_members m JOIN rag_chunks c ON c.id=m.chunk_id JOIN document_versions v ON v.id=c.version_id WHERE m.index_id=?", (index["id"],)).fetchall()
            bad = []
            for row in rows:
                try:
                    validate_vectors([json.loads(row["embedding"])], 1, index["embedding_dimension"])
                    if row["embedding_model"] != index["embedding_model"] or row["pipeline_hash"] != self.pipeline_hash(index):
                        raise ValueError("model or pipeline mismatch")
                    if row["parser_version"] != index["config"]["registry"]["parser_version"] or row["chunker_version"] != index["config"]["registry"]["chunker_version"]:
                        raise ValueError("parser or chunker version mismatch")
                    if not con.execute("SELECT rowid FROM rag_fts WHERE rowid=?", (row["id"],)).fetchone():
                        raise ValueError("missing sparse entry")
                except Exception as exc:
                    bad.append({"chunk_id": row["id"], "error": str(exc)})
            duplicate_versions = con.execute("SELECT c.document_id FROM rag_members m JOIN rag_chunks c ON c.id=m.chunk_id WHERE m.index_id=? GROUP BY c.document_id HAVING count(DISTINCT c.version_id)>1", (index["id"],)).fetchall()
            build_jobs = con.execute("SELECT count(*) FROM ingestion_jobs WHERE kind='index-build' AND status NOT IN ('completed','failed') AND json_extract(payload,'$.index_id')=?", (index["id"],)).fetchone()[0]
            expected_docs = {row[0] for row in con.execute("SELECT id FROM documents WHERE status != 'deleted'")}
            missing_docs = sorted(expected_docs - {row["document_id"] for row in rows}) if index["status"] in {"building", "ready"} else []
            valid = bool(rows) and not bad and not duplicate_versions and not build_jobs and not missing_docs
            result = {"valid": valid, "chunks": len(rows), "errors": bad, "mixed_document_versions": len(duplicate_versions),
                      "pending_build_jobs": build_jobs, "missing_documents": missing_docs,
                      "scope": "structural-integrity; run eval.run before activating a model migration"}
            con.execute("UPDATE rag_indexes SET validated=?,validation=?,status=CASE WHEN status='active' THEN status ELSE ? END WHERE id=?",
                        (int(valid), json.dumps(result), "ready" if valid else "building", index["id"]))
        return result

    def activate(self, index_id: str) -> dict:
        index = self.get_index(index_id)
        if not self.validate_index(index["id"])["valid"]:
            raise ValueError("Index validation failed")
        with self.connect() as con:
            con.execute("UPDATE rag_indexes SET status='retired' WHERE status='active'")
            con.execute("UPDATE rag_indexes SET status='active' WHERE id=?", (index["id"],))
            con.execute("INSERT OR REPLACE INTO rag_state VALUES('active_index',?)", (index["id"],))
        return self.get_index(index["id"])

    def query_scope(self, index: dict, principal: Principal, filters: dict) -> tuple[str, list]:
        clause, params = acl_clause("d", principal)
        clause += " AND m.index_id=?"
        params.append(index["id"])
        for key in ("filename", "repository"):
            if filters.get(key) is not None:
                clause += f" AND d.{key}=?"
                params.append(filters[key])
        for key in ("language", "symbol", "section"):
            if filters.get(key) is not None:
                clause += " AND json_extract(c.metadata,?)=?"
                params.extend([f"$.{key}", filters[key]])
        return clause, params

    @staticmethod
    def chunk_record(row) -> dict:
        item = dict(row)
        item["metadata"] = json.loads(item["metadata"])
        item["content"] = item["raw_content"] # backward-compatible UI field
        item["section"] = item["metadata"].get("section")
        item["page"] = item["metadata"].get("page")
        return item

    def authorized_chunks(self, index: dict, principal: Principal, filters: dict) -> list[dict]:
        clause, params = self.query_scope(index, principal, filters)
        with self.connect() as con:
            rows = con.execute(f"SELECT c.*,d.filename,d.path,v.version FROM rag_members m JOIN rag_chunks c ON c.id=m.chunk_id JOIN documents d ON d.id=c.document_id JOIN document_versions v ON v.id=c.version_id WHERE {clause}", params).fetchall()
        return [self.chunk_record(row) for row in rows]

    def parent(self, parent_id: int, index: dict, principal: Principal) -> dict | None:
        clause, params = self.query_scope(index, principal, {})
        with self.connect() as con:
            row = con.execute(f"SELECT p.* FROM rag_parents p JOIN rag_chunks c ON c.parent_id=p.id JOIN rag_members m ON m.chunk_id=c.id JOIN documents d ON d.id=c.document_id WHERE p.id=? AND {clause} LIMIT 1", [parent_id, *params]).fetchone()
        return dict(row) if row else None


class SQLiteVectorStore:
    def __init__(self, storage: SQLiteStorage):
        self.storage = storage

    def search(self, vector: list[float], index: dict, principal: Principal, filters: dict, limit: int) -> list[dict]:
        validate_vectors([vector], 1, index["embedding_dimension"])
        # Unauthorized vectors are never loaded or scored.
        records = self.storage.authorized_chunks(index, principal, filters)
        scored = []
        for item in records:
            if item["embedding_model"] != index["embedding_model"] or item["embedding_dimension"] != index["embedding_dimension"]:
                raise ValueError("Index embedding space mismatch")
            item["vector_score"] = cosine(vector, json.loads(item.pop("embedding")))
            item["score"] = item["vector_score"]
            scored.append(item)
        return sorted(scored, key=lambda item: (-item["score"], item["id"]))[:limit]

    def upsert(self, connection, **chunk) -> int:
        fields = list(chunk)
        cursor = connection.execute(f"INSERT INTO rag_chunks({','.join(fields)}) VALUES({','.join('?' for _ in fields)})", [chunk[key] for key in fields])
        return cursor.lastrowid

    def delete(self, connection, index_id: str, document_id: int) -> None:
        connection.execute("DELETE FROM rag_members WHERE index_id=? AND chunk_id IN (SELECT id FROM rag_chunks WHERE document_id=?)", (index_id, document_id))


class SQLiteSparseRetriever:
    def __init__(self, storage: SQLiteStorage):
        self.storage = storage

    def search(self, query: str, index: dict, principal: Principal, filters: dict, limit: int) -> list[dict]:
        from app.reranking import query_terms
        terms = sorted(query_terms(query))
        if not terms:
            return []
        match = " OR ".join('"' + term.replace('"', '') + '"' for term in terms)
        clause, params = self.storage.query_scope(index, principal, filters)
        with self.storage.connect() as con:
            rows = con.execute(f"""SELECT c.*,d.filename,d.path,v.version,bm25(rag_fts) AS bm25_score
                FROM rag_fts JOIN rag_chunks c ON c.id=rag_fts.rowid JOIN rag_members m ON m.chunk_id=c.id
                JOIN documents d ON d.id=c.document_id JOIN document_versions v ON v.id=c.version_id
                WHERE rag_fts MATCH ? AND {clause} ORDER BY bm25_score,c.id LIMIT ?""", [match, *params, limit]).fetchall()
        results = [self.storage.chunk_record(row) for row in rows]
        for item in results:
            item.pop("embedding", None)
        return results
