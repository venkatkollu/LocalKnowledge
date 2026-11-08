"""Model provider profiles and embedding/generation transport."""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from . import runtime
from .config import SETTINGS
from .db import db
from .security import PRIVATE_FILE_MODE, decrypt_key, ensure_private_dir, set_private_mode
from .utils import deterministic_vector, now_ms


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



def _ollama_log_path():
    return SETTINGS.data_dir / "ollama" / "server.log"



def _ollama_bind_address() -> str:
    parsed = urlparse(SETTINGS.ollama_base_url)
    return f"{parsed.hostname or '127.0.0.1'}:{parsed.port or 11434}"



def _ollama_tags(timeout: float = 1.0) -> dict[str, Any] | None:
    """Return Ollama's model list, or None when the endpoint is unreachable."""
    try:
        with urlopen(Request(f"{SETTINGS.ollama_base_url}/api/tags", method="GET"), timeout=timeout) as response:
            payload = json.loads(response.read().decode())
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else {}



def _ollama_model_installed(tags: dict[str, Any]) -> bool:
    model = SETTINGS.ollama_embedding_model
    names = {
        str(entry.get("name") or entry.get("model") or "")
        for entry in tags.get("models") or []
        if isinstance(entry, dict)
    }
    return model in names or f"{model}:latest" in names



def _start_and_wait_for_ollama() -> dict[str, Any]:
    log_path = _ollama_log_path()
    if runtime.OLLAMA_PROCESS is None or runtime.OLLAMA_PROCESS.poll() is not None:
        ensure_private_dir(log_path.parent)
        try:
            descriptor = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, PRIVATE_FILE_MODE)
            set_private_mode(log_path, PRIVATE_FILE_MODE)
            with os.fdopen(descriptor, "ab") as log:
                runtime.OLLAMA_PROCESS = subprocess.Popen(
                    ["ollama", "serve"],
                    env={**os.environ, "OLLAMA_HOST": _ollama_bind_address()},
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
        except FileNotFoundError as exc:
            raise RuntimeError(
                "Ollama is not reachable and the `ollama` command is not installed. "
                "Install it with `sh backend/setup_ollama.sh`."
            ) from exc
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        tags = _ollama_tags()
        if tags is not None:
            return tags
        if runtime.OLLAMA_PROCESS is not None and runtime.OLLAMA_PROCESS.poll() is not None:
            raise RuntimeError(f"Ollama exited while starting; see {log_path}.")
        time.sleep(0.25)
    raise RuntimeError(f"Ollama did not become ready at {SETTINGS.ollama_base_url} within 30s; see {log_path}.")



def _pull_ollama_model() -> None:
    model = SETTINGS.ollama_embedding_model
    try:
        result = subprocess.run(
            ["ollama", "pull", model],
            env={**os.environ, "OLLAMA_HOST": _ollama_bind_address()},
            capture_output=True,
            text=True,
            timeout=SETTINGS.ollama_pull_timeout_seconds,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("The `ollama` command is not installed; cannot pull the embedding model.") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"Timed out after {SETTINGS.ollama_pull_timeout_seconds}s pulling embedding model '{model}'."
        ) from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()[-400:]
        raise RuntimeError(f"Could not pull embedding model '{model}': {detail or 'ollama pull failed'}")



def ensure_ollama_available() -> None:
    """Make sure the Ollama endpoint is up and the embedding model is present.

    Ingestion used to fail every document when Ollama was not already running,
    even though ``KNOWLEDGEOS_OLLAMA_AUTO_START`` and ``AUTO_PULL`` default to
    true. This preflight honours those settings once per process; concurrent
    ingestion workers serialize on the embedding lock.
    """
    if runtime.OLLAMA_MODEL_READY:
        return
    with runtime.EMBEDDING_RUNTIME_LOCK:
        if runtime.OLLAMA_MODEL_READY:
            return
        tags = _ollama_tags()
        if tags is None:
            if not SETTINGS.ollama_auto_start:
                raise RuntimeError(
                    f"Ollama is not reachable at {SETTINGS.ollama_base_url}. "
                    "Start it with `ollama serve` or run `sh backend/setup_ollama.sh`."
                )
            tags = _start_and_wait_for_ollama()
        if _ollama_model_installed(tags):
            runtime.OLLAMA_MODEL_READY = runtime.OLLAMA_MODEL_CHECKED = True
            return
        if not SETTINGS.ollama_auto_pull:
            raise RuntimeError(
                f"Embedding model '{SETTINGS.ollama_embedding_model}' is not installed at "
                f"{SETTINGS.ollama_base_url}. Run `ollama pull {SETTINGS.ollama_embedding_model}` "
                "or set KNOWLEDGEOS_OLLAMA_AUTO_PULL=true."
            )
        _pull_ollama_model()
        runtime.OLLAMA_MODEL_READY = runtime.OLLAMA_MODEL_CHECKED = True



def ollama_embed_text(text: str) -> list[float]:
    """Embed text with Ollama's current API, supporting older Ollama installs."""
    ensure_ollama_available()
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



def provider_public(row: sqlite3.Row) -> dict[str, Any]:
    return {"id": row["id"], "name": row["name"], "kind": row["kind"], "base_url": row["base_url"], "model": row["model"], "role": row["role"], "enabled": bool(row["enabled"]), "created_at": row["created_at"], "updated_at": row["updated_at"], "has_api_key": True}
