from __future__ import annotations

import hashlib
import math
import re

import httpx


def tokenize(text: str) -> list[str]:
    # Split qualified symbols/underscores as well as preserve identifier tokens.
    words = re.findall(r"[\w]+(?:[.+#-][\w]+)*", text.lower())
    return words + [part for word in words if "_" in word or "." in word for part in re.split(r"[_.]", word) if part]


def validate_vectors(vectors, count: int, dimension: int | None = None) -> int:
    if len(vectors) != count or not vectors:
        raise ValueError("Embedding count mismatch")
    dimension = dimension or len(vectors[0])
    if dimension < 1:
        raise ValueError("Empty embedding")
    for vector in vectors:
        if len(vector) != dimension or not all(isinstance(v, (float, int)) and math.isfinite(v) for v in vector):
            raise ValueError("Invalid embedding dimension or non-finite value")
        if not any(vector):
            raise ValueError("Zero embedding vector")
    return dimension


class HashEmbedding:
    model = "local-hash-v2"
    provider = "hash"

    def __init__(self, dimension: int = 384, model: str = "local-hash-v2"):
        self.dimension, self.model = dimension, model

    def embed(self, texts: list[str]) -> list[list[float]]:
        output = []
        for text in texts:
            vector = [0.0] * self.dimension
            for token in tokenize(text):
                digest = hashlib.blake2b(token.encode(), digest_size=8).digest()
                vector[int.from_bytes(digest[:4], "little") % self.dimension] += 1 if digest[4] & 1 else -1
            norm = math.sqrt(sum(x * x for x in vector)) or 1.0
            output.append([x / norm for x in vector])
        return output


class LocalEmbedding:
    def __init__(self, settings, provider: str, model: str, dimension: int | None = None, revision: str | None = None):
        self.settings, self.provider, self.model, self.dimension = settings, provider, model, dimension
        self.expected_revision = revision
        self.revision_checked = False

    def revision(self):
        if self.provider != "ollama":
            return None
        response = httpx.get(f"{self.settings.ollama_url}/api/tags", timeout=10, trust_env=False)
        response.raise_for_status()
        names = {self.model, self.model + ":latest"}
        return next((item.get("digest") for item in response.json().get("models", []) if item.get("name") in names), None)

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if self.expected_revision and not self.revision_checked:
            if self.revision() != self.expected_revision:
                raise ValueError("Embedding model digest changed; build a new index")
            self.revision_checked = True
        if self.provider == "ollama":
            response = httpx.post(f"{self.settings.ollama_url}/api/embed", json={"model": self.model, "input": texts}, timeout=120, trust_env=False)
            response.raise_for_status()
            vectors = response.json()["embeddings"]
        else:
            response = httpx.post(f"{self.settings.lmstudio_url}/embeddings", json={"model": self.model, "input": texts}, timeout=120, trust_env=False)
            response.raise_for_status()
            data = sorted(response.json()["data"], key=lambda item: item["index"])
            vectors = [item["embedding"] for item in data]
        self.dimension = validate_vectors(vectors, len(texts), self.dimension)
        return vectors


def embedding_for(settings, index: dict):
    if index["embedding_provider"] == "hash":
        return HashEmbedding(index["embedding_dimension"], index["embedding_model"])
    return LocalEmbedding(settings, index["embedding_provider"], index["embedding_model"], index["embedding_dimension"], index["config"]["registry"].get("embedding_revision"))


def cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        raise ValueError("Incompatible embedding dimensions")
    return sum(x * y for x, y in zip(a, b)) / ((math.sqrt(sum(x * x for x in a)) or 1) * (math.sqrt(sum(x * x for x in b)) or 1))
