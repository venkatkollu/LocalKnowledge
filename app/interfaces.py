from __future__ import annotations

from pathlib import Path
from typing import Protocol


class EmbeddingModel(Protocol):
    model: str
    dimension: int
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class Reranker(Protocol):
    model: str
    def rerank(self, query: str, documents: list[dict], limit: int) -> list[dict]: ...


class VectorStore(Protocol):
    def search(self, vector: list[float], index: dict, principal, filters: dict, limit: int) -> list[dict]: ...
    def upsert(self, connection, **chunk) -> int: ...
    def delete(self, connection, index_id: str, document_id: int) -> None: ...


class SparseRetriever(Protocol):
    def search(self, query: str, index: dict, principal, filters: dict, limit: int) -> list[dict]: ...


class Generator(Protocol):
    model: str
    def complete(self, system: str, user: str, model: str | None = None) -> dict: ...


class Parser(Protocol):
    version: str
    def parse(self, path: Path, raw: bytes) -> list[dict]: ...


class Chunker(Protocol):
    version: str
    def split(self, structures: list[dict]) -> list[dict]: ...
