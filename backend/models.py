"""Request payload models shared by the HTTP layer."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


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
    document_id: str | None = Field(default=None, min_length=1, max_length=128)
    document_ids: list[str] | None = Field(default=None, max_length=64)
    filters: dict[str, Any] | None = None
    disable_cache: bool = False



class GoldenSetItem(BaseModel):
    question: str = Field(min_length=1, max_length=20_000)
    expected_document_id: str | None = None
    expected_chunk_id: str | None = None



class FeedbackRequest(BaseModel):
    trace_id: str
    rating: int = Field(ge=-1, le=1)
    comment: str | None = Field(default=None, max_length=2000)



class VerifyRequest(BaseModel):
    answer: str = Field(min_length=1, max_length=20_000)
    citation_chunk_ids: list[str] = Field(min_length=1, max_length=20)



class SyncRequest(BaseModel):
    document_id: str | None = None



class IndexCreate(BaseModel):
    embedding: str | None = None
    notes: str | None = None
