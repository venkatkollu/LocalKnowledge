"""SQLite connection handling, schema, migrations and secrets-at-rest."""
from __future__ import annotations

import os
import sqlite3
import sys
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from cryptography.fernet import InvalidToken

from .config import SETTINGS, SQLITE_BUSY_TIMEOUT_MS
from .security import PRIVATE_FILE_MODE, ensure_private_dir, set_private_mode
from .utils import now_ms


# SQLite has a single writer; serialize transactions inside this process.
DB_LOCK = threading.RLock()


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
  progress REAL, stage TEXT, title TEXT, author TEXT, uploaded_at INTEGER, pages INTEGER,
  total_chunks INTEGER NOT NULL DEFAULT 0,
  deleted_at INTEGER, UNIQUE(workspace_id, content_hash)
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
  section TEXT, symbol TEXT, chunk_type TEXT, page_number INTEGER,
  start_offset INTEGER, end_offset INTEGER, tokens INTEGER NOT NULL, embedding_json TEXT,
  superseded INTEGER NOT NULL DEFAULT 0,
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
CREATE TABLE IF NOT EXISTS index_chunks (
  index_id TEXT NOT NULL, workspace_id TEXT NOT NULL, chunk_id TEXT NOT NULL,
  PRIMARY KEY(index_id, chunk_id)
);
CREATE INDEX IF NOT EXISTS idx_index_chunks_workspace ON index_chunks(workspace_id, index_id);
CREATE TABLE IF NOT EXISTS index_chunk_embeddings (
  index_id TEXT NOT NULL, workspace_id TEXT NOT NULL, chunk_id TEXT NOT NULL,
  embedding_json TEXT NOT NULL, model TEXT NOT NULL,
  PRIMARY KEY(index_id, chunk_id)
);
CREATE INDEX IF NOT EXISTS idx_index_chunk_embeddings_workspace ON index_chunk_embeddings(workspace_id, index_id);
CREATE TABLE IF NOT EXISTS cache_entries (
  id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, index_version TEXT NOT NULL, model_profile_id TEXT,
  prompt_version TEXT NOT NULL, query_hash TEXT NOT NULL, query_text TEXT NOT NULL, embedding_json TEXT,
  response_json TEXT NOT NULL, confidence REAL NOT NULL, created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL,
  filter_fingerprint TEXT, intent_class TEXT,
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
CREATE TABLE IF NOT EXISTS routing_log (
  id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, question TEXT NOT NULL,
  tier TEXT NOT NULL, rule_route TEXT, llm_route TEXT, route TEXT NOT NULL,
  confidence REAL NOT NULL DEFAULT 0.0, reason TEXT NOT NULL,
  outcome TEXT, final_route TEXT, disagreement INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL, updated_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_routing_log_workspace ON routing_log(workspace_id);
CREATE INDEX IF NOT EXISTS idx_routing_log_outcome ON routing_log(outcome);
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



def backup_database(connection: sqlite3.Connection, reason: str) -> Path:
    """Create a consistent, private SQLite snapshot before a migration."""
    backup_dir = SETTINGS.data_dir / "backups"
    ensure_private_dir(backup_dir)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    path = backup_dir / f"knowledgeos-{reason}-{stamp}.sqlite3"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, PRIVATE_FILE_MODE)
    os.close(descriptor)
    destination = sqlite3.connect(path)
    try:
        connection.backup(destination)
        integrity = destination.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"Backup integrity check failed for {path}: {integrity}")
    finally:
        destination.close()
    set_private_mode(path, PRIVATE_FILE_MODE)
    return path



def migrate_provider_keys(connection: sqlite3.Connection) -> tuple[int, int]:
    """Move provider keys from the legacy derived key to the dedicated key.

    Older builds encrypted provider keys with a key derived from the auth
    secret, which defaulted to a public constant. Rows that still decrypt with
    that legacy key are re-encrypted with the current Fernet key after a
    verified snapshot. Unknown keys are left untouched and reported.
    """
    rows = connection.execute("SELECT id, encrypted_key FROM provider_profiles").fetchall()
    pending: list[tuple[str, str]] = []
    failed = 0
    for row in rows:
        token = row["encrypted_key"].encode()
        try:
            SETTINGS.fernet.decrypt(token)
            continue
        except (InvalidToken, TypeError, ValueError):
            pass
        plaintext: str | None = None
        for legacy in SETTINGS.legacy_fernets:
            try:
                plaintext = legacy.decrypt(token).decode("utf-8")
                break
            except (InvalidToken, TypeError, ValueError, UnicodeDecodeError):
                continue
        if plaintext is None:
            failed += 1
            continue
        pending.append((row["id"], SETTINGS.fernet.encrypt(plaintext.encode()).decode()))
    if pending:
        backup_path = backup_database(connection, "pre-key-migration")
        replacements = [(new_token, provider_id) for provider_id, new_token in pending]
        connection.executemany("UPDATE provider_profiles SET encrypted_key=? WHERE id=?", replacements)
        # The snapshot is private, but its tokens were still encrypted with the
        # legacy key. Rewrite them so a stolen backup cannot expose provider keys.
        try:
            backup_connection = sqlite3.connect(backup_path)
            try:
                backup_connection.executemany("UPDATE provider_profiles SET encrypted_key=? WHERE id=?", replacements)
                backup_connection.commit()
            finally:
                backup_connection.close()
        except sqlite3.Error as exc:
            print(f"WARNING: could not re-encrypt provider keys in backup {backup_path}: {exc}", file=sys.stderr)
        print(
            f"Re-encrypted {len(pending)} provider key(s) with the dedicated encryption key; backup at {backup_path}",
            file=sys.stderr,
        )
    if failed:
        print(
            f"WARNING: {failed} provider key(s) could not be decrypted with the configured or legacy keys; re-enter them in Models",
            file=sys.stderr,
        )
    return len(pending), failed



def init_db() -> None:
    # Imported here to keep the schema/migration layer independent of the
    # retrieval and index modules that depend on it.
    from .indexes import refresh_index_membership

    with DB_LOCK, db() as connection:
        connection.executescript(SCHEMA)

        cache_columns = {row[1] for row in connection.execute("PRAGMA table_info(cache_entries)").fetchall()}
        if cache_columns and not {"filter_fingerprint", "intent_class"}.issubset(cache_columns):
            # Additive migration: verified snapshot before changing the shape.
            # Run this before any other migration writes so the backup sees a
            # settled database and cannot block on an open write transaction.
            backup_database(connection, "pre-cache-key-migration")
            if "filter_fingerprint" not in cache_columns:
                connection.execute("ALTER TABLE cache_entries ADD COLUMN filter_fingerprint TEXT")
            if "intent_class" not in cache_columns:
                connection.execute("ALTER TABLE cache_entries ADD COLUMN intent_class TEXT")

        # Additive metadata migrations. Existing rows keep NULLs for fields the
        # old build never captured instead of guessing values.
        document_columns = {row[1] for row in connection.execute("PRAGMA table_info(documents)").fetchall()}
        for column, ddl in (
            ("pages", "INTEGER"),
            ("title", "TEXT"),
            ("author", "TEXT"),
            ("uploaded_at", "INTEGER"),
        ):
            if document_columns and column not in document_columns:
                connection.execute(f"ALTER TABLE documents ADD COLUMN {column} {ddl}")
        chunk_columns = {row[1] for row in connection.execute("PRAGMA table_info(chunks)").fetchall()}
        for column, ddl in (
            ("chunk_type", "TEXT"),
            ("page_number", "INTEGER"),
            ("start_offset", "INTEGER"),
            ("end_offset", "INTEGER"),
        ):
            if chunk_columns and column not in chunk_columns:
                connection.execute(f"ALTER TABLE chunks ADD COLUMN {column} {ddl}")
        if document_columns and "total_chunks" not in document_columns:
            connection.execute("ALTER TABLE documents ADD COLUMN total_chunks INTEGER NOT NULL DEFAULT 0")
        connection.execute(
            "UPDATE documents SET uploaded_at=updated_at WHERE uploaded_at IS NULL"
        )
        connection.execute("UPDATE chunks SET chunk_type='text' WHERE chunk_type IS NULL")

        # Keep active indexes self-contained. Candidate indexes stay snapshots
        # until they are activated; active ones track the live chunk set so new
        # documents remain searchable without mixing embedding spaces.
        for index_row in connection.execute("SELECT id, workspace_id FROM index_versions WHERE state='active'").fetchall():
            refresh_index_membership(connection, index_row["workspace_id"], index_row["id"])

        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"Database integrity check failed after migration: {integrity}")

        connection.execute("INSERT OR IGNORE INTO workspaces(id, name, created_at) VALUES (?, ?, ?)", ("default", "Default workspace", now_ms()))
        connection.commit()
        migrate_provider_keys(connection)
    set_private_mode(SETTINGS.db_path, PRIVATE_FILE_MODE)
    for suffix in ("-wal", "-shm"):
        sidecar = Path(f"{SETTINGS.db_path}{suffix}")
        if sidecar.exists():
            set_private_mode(sidecar, PRIVATE_FILE_MODE)
