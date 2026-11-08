"""Workspace principals and request authentication."""
from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass

from fastapi import Header, HTTPException

from .config import SETTINGS
from .db import db
from .utils import now_ms


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
