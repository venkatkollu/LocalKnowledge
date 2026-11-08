"""OpenAI-compatible model profile endpoints."""
from __future__ import annotations

import sqlite3
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from .. import providers
from ..auth import Principal, principal
from ..db import db
from ..models import ProviderCreate, ProviderUpdate
from ..providers import choose_provider, provider_public, provider_row
from ..security import encrypt_key
from ..utils import now_ms

router = APIRouter()


@router.get("/api/models/profiles")
def list_providers(p: Principal = Depends(principal)) -> list[dict[str, Any]]:
    with db() as connection:
        return [provider_public(row) for row in connection.execute("SELECT * FROM provider_profiles WHERE workspace_id=? ORDER BY created_at", (p.workspace_id,)).fetchall()]



@router.post("/api/models/profiles", status_code=201)
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



@router.patch("/api/models/profiles/{provider_id}")
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



@router.delete("/api/models/profiles/{provider_id}", status_code=204)
def delete_provider(provider_id: str, p: Principal = Depends(principal)) -> None:
    with db() as connection:
        result = connection.execute("DELETE FROM provider_profiles WHERE id=? AND workspace_id=?", (provider_id, p.workspace_id))
        if result.rowcount == 0:
            raise HTTPException(404, "Provider not found")



@router.post("/api/models/profiles/{provider_id}/test")
def test_provider(provider_id: str, p: Principal = Depends(principal)) -> dict[str, Any]:
    with db() as connection:
        row = provider_row(connection, p.workspace_id, provider_id)
    if row is None:
        raise HTTPException(404, "Provider not found")
    try:
        result = providers.provider_request(row, "/models", {}, timeout=15, method="GET")
        return {"ok": True, "provider_id": provider_id, "models": result.get("data", result.get("models", []))}
    except RuntimeError as exc:
        return {"ok": False, "provider_id": provider_id, "detail": str(exc)}



@router.get("/v1/models")
def v1_models(p: Principal = Depends(principal)) -> dict[str, Any]:
    """OpenAI-compatible model list.

    Some clients and probes expect the standard ``/v1/models`` path on the
    configured generation provider. The backend does not proxy arbitrary
    provider traffic, so this returns the locally configured generation model
    instead of 404ing.
    """
    with db() as connection:
        row = choose_provider(connection, p.workspace_id, "Generation")
    if row is None:
        return {"object": "list", "data": []}
    return {
        "object": "list",
        "data": [
            {
                "id": row["model"],
                "object": "model",
                "owned_by": row["kind"],
                "created": int(row["created_at"]),
            }
        ],
    }
