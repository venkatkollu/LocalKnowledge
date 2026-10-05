from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

from pydantic import BaseModel, Field, model_validator
import yaml

ROOT = Path(__file__).resolve().parents[1]


class ContextualChunking(BaseModel):
    enabled: bool = True
    mode: str = "structure"
    model: str = "qwen3:4b"


class RetrievalConfig(BaseModel):
    dense_k: int = Field(50, ge=1, le=1000)
    sparse_k: int = Field(50, ge=1, le=1000)
    candidate_k: int = Field(100, ge=1, le=1000)
    rerank_k: int = Field(20, ge=1, le=100)
    rrf_k: int = Field(60, ge=1)
    dense_weight: float = Field(1.0, ge=0)
    sparse_weight: float = Field(1.0, ge=0)
    parent_expansion: bool = True
    parent_max_chars: int = Field(2400, ge=100)
    max_context_chars: int = Field(10000, ge=500)
    contextual_chunking: ContextualChunking = Field(default_factory=ContextualChunking)


class ExpansionConfig(BaseModel):
    enabled: bool = False
    num_queries: int = Field(3, ge=1, le=5)
    min_query_words: int = Field(6, ge=1)


class QueryConfig(BaseModel):
    expansion: ExpansionConfig = Field(default_factory=ExpansionConfig)
    hyde: bool = False


class EmbeddingConfig(BaseModel):
    provider: str = "ollama"
    model: str = "nomic-embed-text"
    dimension: int = Field(384, ge=8)
    allow_initial_hash_fallback: bool = True
    batch_size: int = Field(32, ge=1, le=512)


class RerankerConfig(BaseModel):
    provider: str = "heuristic"
    model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    model_path: str | None = None
    device: str = "cpu"


class GenerationConfig(BaseModel):
    provider: str = "ollama"
    model: str = "qwen3:4b"
    allow_extractive_fallback: bool = True
    max_tokens: int = Field(1024, ge=32)


class SecurityConfig(BaseModel):
    auth_mode: str = "local"
    credentials_file: Path | None = None
    max_upload_bytes: int = Field(20 * 1024 * 1024, ge=1024)
    block_suspicious_evidence: bool = True


class EvidenceConfig(BaseModel):
    min_query_coverage: float = Field(0.25, ge=0, le=1)
    min_dense_score: float = Field(0.2, ge=-1, le=1)
    min_claim_support: float = Field(0.8, ge=0, le=1)


class Settings(BaseModel):
    data_dir: Path = ROOT / "data"
    knowledge_dir: Path = ROOT / "data" / "knowledge"
    db_path: Path = ROOT / "data" / "knowledgeos.db"
    ollama_url: str = "http://127.0.0.1:11434"
    lmstudio_url: str = "http://127.0.0.1:1234/v1"
    auto_sync: bool = True
    workers: int = Field(2, ge=1, le=16)
    queue_capacity: int = Field(16, ge=1)
    chunk_size: int = Field(900, ge=100)
    chunk_overlap: int = Field(120, ge=0)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    query: QueryConfig = Field(default_factory=QueryConfig)
    embeddings: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    reranker: RerankerConfig = Field(default_factory=RerankerConfig)
    generation: GenerationConfig = Field(default_factory=GenerationConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    evidence: EvidenceConfig = Field(default_factory=EvidenceConfig)

    @model_validator(mode="after")
    def validate_settings(self):
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        for value in (self.ollama_url, self.lmstudio_url):
            parsed = urlparse(value)
            if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
                raise ValueError("Model endpoints must be loopback HTTP URLs for local-first mode")
        if self.embeddings.provider not in {"hash", "ollama", "lmstudio"}:
            raise ValueError("Unknown embedding provider")
        if self.generation.provider not in {"extractive", "ollama", "lmstudio"}:
            raise ValueError("Unknown generation provider")
        if self.reranker.provider not in {"heuristic", "cross_encoder"}:
            raise ValueError("Unknown reranker provider")
        if self.retrieval.contextual_chunking.mode not in {"structure", "llm"}:
            raise ValueError("Unknown contextualization mode")
        if self.security.auth_mode not in {"local", "token"}:
            raise ValueError("Unknown auth mode")
        if self.security.auth_mode == "token" and not self.security.credentials_file:
            raise ValueError("token mode requires credentials_file")
        return self

    @classmethod
    def load(cls):
        filename = Path(os.getenv("KNOWLEDGEOS_CONFIG", ROOT / "config.yaml"))
        values = yaml.safe_load(filename.read_text()) if filename.exists() else {}
        values = values or {}
        data = Path(os.getenv("KNOWLEDGEOS_DATA", values.get("data_dir", ROOT / "data")))
        values.update(data_dir=data,
                      knowledge_dir=os.getenv("KNOWLEDGEOS_KNOWLEDGE", values.get("knowledge_dir", data / "knowledge")),
                      db_path=os.getenv("KNOWLEDGEOS_DB", values.get("db_path", data / "knowledgeos.db")))
        for env, key in (("OLLAMA_URL", "ollama_url"), ("LMSTUDIO_URL", "lmstudio_url")):
            if env in os.environ:
                values[key] = os.environ[env]
        if "KNOWLEDGEOS_AUTO_SYNC" in os.environ:
            values["auto_sync"] = os.environ["KNOWLEDGEOS_AUTO_SYNC"] == "1"
        for section in ("generation", "embeddings"):
            values.setdefault(section, {})
        provider = os.getenv("LLM_PROVIDER")
        if provider:
            values["generation"]["provider"] = provider
            if provider == "lmstudio":
                values["embeddings"].update(provider="lmstudio", model=os.getenv("LMSTUDIO_EMBED_MODEL", "text-embedding-nomic-embed-text-v1.5"))
                values["generation"]["model"] = os.getenv("LMSTUDIO_MODEL", "qwen/qwen3-0.6b")
        model_env = "LMSTUDIO_MODEL" if provider == "lmstudio" else "OLLAMA_MODEL"
        if model_env in os.environ:
            values["generation"]["model"] = os.environ[model_env]
        if "EMBED_MODEL" in os.environ:
            values["embeddings"]["model"] = os.environ["EMBED_MODEL"]
        if "EMBED_DIM" in os.environ:
            values["embeddings"]["dimension"] = int(os.environ["EMBED_DIM"])
        if os.getenv("KNOWLEDGEOS_OFFLINE") == "1":
            values["embeddings"].update(provider="hash", model="local-hash-v2")
            values["generation"].update(provider="extractive", model="local-extractive-v2")
        return cls.model_validate(values)
