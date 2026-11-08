"""Environment configuration and validated runtime settings."""
from __future__ import annotations

import os
import re
import secrets
import sys
from pathlib import Path

from cryptography.fernet import Fernet

from .security import (
    PRIVATE_DIR_MODE,
    PRIVATE_FILE_MODE,
    ensure_private_dir,
    legacy_encryption_key,
    load_or_create_secret,
    set_private_mode,
)


APP_VERSION = "1.0.0"



PROMPT_VERSION = "knowledgeos-answer-v3"



JOB_STAGES = ("parsing", "structure", "chunking", "contextualizing", "embedding", "indexing", "validating")


ROUTER_LLM_ENABLED = os.getenv("KNOWLEDGEOS_ROUTER_LLM", "auto").lower() in {"1", "true", "yes", "auto"}



MAX_UPLOAD_BYTES = int(os.getenv("KNOWLEDGEOS_MAX_UPLOAD_BYTES", str(512 * 1024 * 1024)))



MAX_BATCH_FILES = int(os.getenv("KNOWLEDGEOS_MAX_BATCH_FILES", "10000"))



CHUNK_SIZE = int(os.getenv("KNOWLEDGEOS_CHUNK_SIZE", "1200"))



CHUNK_OVERLAP = int(os.getenv("KNOWLEDGEOS_CHUNK_OVERLAP", "180"))



MAX_ANSWER_TOKENS = int(os.getenv("KNOWLEDGEOS_MAX_ANSWER_TOKENS", "1024"))



CACHE_TTL_SECONDS = int(os.getenv("KNOWLEDGEOS_CACHE_TTL_SECONDS", str(7 * 86400)))



SEMANTIC_CACHE_THRESHOLD = float(os.getenv("KNOWLEDGEOS_CACHE_SIMILARITY", "0.92"))



RERANK_TIMEOUT_MS = int(os.getenv("KNOWLEDGEOS_RERANK_TIMEOUT_MS", "80"))



SQLITE_BUSY_TIMEOUT_MS = int(os.getenv("KNOWLEDGEOS_SQLITE_BUSY_TIMEOUT_MS", "60000"))



EMBEDDING_API_KEY = os.getenv("KNOWLEDGEOS_EMBEDDING_API_KEY", os.getenv("OPENAI_API_KEY", "")).strip()



EMBEDDING_API_BASE_URL = os.getenv("KNOWLEDGEOS_EMBEDDING_API_BASE_URL", "https://api.openai.com/v1").rstrip("/")



EMBEDDING_API_MODEL = os.getenv("KNOWLEDGEOS_EMBEDDING_API_MODEL", "BAAI/bge-m3")



OLLAMA_BASE_URL = os.getenv("KNOWLEDGEOS_OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")



OLLAMA_EMBEDDING_MODEL = os.getenv("KNOWLEDGEOS_OLLAMA_EMBEDDING_MODEL", "nomic-embed-text")



OLLAMA_AUTO_START = os.getenv("KNOWLEDGEOS_OLLAMA_AUTO_START", "true").lower() in {"1", "true", "yes"}



OLLAMA_AUTO_PULL = os.getenv("KNOWLEDGEOS_OLLAMA_AUTO_PULL", "true").lower() in {"1", "true", "yes"}



OLLAMA_PULL_TIMEOUT_SECONDS = int(os.getenv("KNOWLEDGEOS_OLLAMA_PULL_TIMEOUT_SECONDS", "1800"))



LMSTUDIO_BASE_URL = os.getenv("KNOWLEDGEOS_LMSTUDIO_BASE_URL", "http://127.0.0.1:1234/v1").rstrip("/")



LMSTUDIO_EMBEDDING_MODEL = os.getenv("KNOWLEDGEOS_LMSTUDIO_EMBEDDING_MODEL", "").strip()



LOCAL_BGE_MODEL = os.getenv("KNOWLEDGEOS_LOCAL_BGE_MODEL", "BAAI/bge-small-en-v1.5")



LOCAL_BGE_AUTO_LOAD = os.getenv("KNOWLEDGEOS_LOCAL_BGE_AUTO_LOAD", "true").lower() in {"1", "true", "yes"}



ALLOW_HASH_EMBEDDING_FALLBACK = os.getenv("KNOWLEDGEOS_ALLOW_HASH_EMBEDDING_FALLBACK", "false").lower() in {"1", "true", "yes"}



ABSTAIN_THRESHOLD = float(os.getenv("KNOWLEDGEOS_ABSTAIN_THRESHOLD", "0.6"))



NLI_ENABLED = os.getenv("KNOWLEDGEOS_NLI_ENABLED", "true").lower() in {"1", "true", "yes"}



NLI_THRESHOLD = float(os.getenv("KNOWLEDGEOS_NLI_THRESHOLD", "0.5"))



NLI_MAX_CLAIMS = int(os.getenv("KNOWLEDGEOS_NLI_MAX_CLAIMS", "20"))



CACHE_DISABLED_DURING_EVAL = os.getenv("KNOWLEDGEOS_CACHE_DISABLED_DURING_EVAL", "true").lower() in {"1", "true", "yes"}



SEMANTIC_CACHE_ENABLED = os.getenv("KNOWLEDGEOS_CACHE_SEMANTIC_ENABLED", "false").lower() in {"1", "true", "yes"}



PROMPT_INJECTION_GUARD = os.getenv("KNOWLEDGEOS_PROMPT_INJECTION_GUARD", "true").lower() in {"1", "true", "yes"}



INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(?:all\s+)?(?:previous|above|prior)\s+instructions", re.I),
    re.compile(r"disregard\s+(?:all\s+)?(?:previous|above|prior)\s+instructions", re.I),
    re.compile(r"you\s+are\s+now\s+(?:a|an|the)", re.I),
    re.compile(r"^\s*system\s*:", re.I | re.M),
    re.compile(r"<\|?(?:system|assistant|user)\|?>", re.I),
    re.compile(r"###\s*(?:instruction|system)", re.I),
    re.compile(r"forget\s+(?:all\s+)?(?:your|the)\s+(?:previous\s+)?instructions", re.I),
]



INGEST_EXTENSIONS = {
    "pdf", "md", "txt", "py", "js", "ts", "tsx", "jsx", "json", "yaml", "yml", "csv", "sql", "go", "rs",
    "html", "htm", "css", "xml", "log", "docx", "xlsx", "pptx", "png", "jpg", "jpeg", "tif", "tiff",
}



CHUNK_TYPES = ("text", "heading", "table", "figure", "list", "code", "equation")



LEGACY_AUTH_SECRET = "local-development-secret"



PROTECTED_DATA_DIRS = {
    Path("/"), Path("/tmp"), Path("/var"), Path("/etc"), Path("/usr"),
    Path("/home"), Path("/root"), Path("/opt"), Path("/srv"), Path("/mnt"),
    Path("/media"), Path("/boot"), Path("/dev"), Path("/proc"), Path("/sys"),
}



class Settings:
    def __init__(self) -> None:
        self.data_dir = Path(os.getenv("KNOWLEDGEOS_DATA_DIR", "data")).expanduser()
        resolved_data_dir = self.data_dir.resolve()
        if resolved_data_dir in PROTECTED_DATA_DIRS or resolved_data_dir in {Path.home().resolve(), Path.cwd().resolve()}:
            raise RuntimeError("KNOWLEDGEOS_DATA_DIR must point to a dedicated data directory, not a system directory or the project root")
        ensure_private_dir(self.data_dir)
        self.db_path = self.data_dir / "knowledgeos.sqlite3"
        self.files_dir = self.data_dir / "files"
        ensure_private_dir(self.files_dir)
        for child in self.files_dir.iterdir():
            if child.is_dir() and not child.is_symlink():
                set_private_mode(child, PRIVATE_DIR_MODE)
        if self.db_path.exists():
            set_private_mode(self.db_path, PRIVATE_FILE_MODE)
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
        self.abstain_threshold = float(os.getenv("KNOWLEDGEOS_ABSTAIN_THRESHOLD", "0.6"))
        self.allow_anonymous = os.getenv("KNOWLEDGEOS_ALLOW_ANONYMOUS", "true").lower() in {"1", "true", "yes"}
        auth_secret_value = load_or_create_secret(
            "KNOWLEDGEOS_AUTH_SECRET",
            self.data_dir / ".auth_secret",
            lambda: secrets.token_hex(32),
        )
        self.auth_secret = auth_secret_value.encode()
        if auth_secret_value == LEGACY_AUTH_SECRET:
            message = "KNOWLEDGEOS_AUTH_SECRET is set to the known development default; set a strong unique value before exposing this instance"
            if not self.allow_anonymous:
                raise RuntimeError(message)
            print(f"WARNING: {message}", file=sys.stderr)
        if not self.allow_anonymous and len(self.auth_secret) < 16:
            raise RuntimeError("Set a strong KNOWLEDGEOS_AUTH_SECRET (at least 16 characters) when anonymous access is disabled")
        encryption_key_value = load_or_create_secret(
            "KNOWLEDGEOS_ENCRYPTION_KEY",
            self.data_dir / ".encryption_key",
            lambda: Fernet.generate_key().decode(),
        )
        self.encryption_key = encryption_key_value.encode()
        try:
            self.fernet = Fernet(self.encryption_key)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("KNOWLEDGEOS_ENCRYPTION_KEY must be a valid Fernet key (44 url-safe base64 characters)") from exc
        self.legacy_fernets = [
            Fernet(legacy_encryption_key(value))
            for value in dict.fromkeys((self.auth_secret, LEGACY_AUTH_SECRET.encode()))
        ]



SETTINGS = Settings()
