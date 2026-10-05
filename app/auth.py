from __future__ import annotations

import json
from urllib.parse import urlparse

from fastapi import HTTPException

from app.security import Principal, token_fingerprint


class Authenticator:
    def __init__(self, settings):
        self.settings = settings
        self.credentials = {}
        if settings.security.auth_mode == "token":
            self.credentials = json.loads(settings.security.credentials_file.read_text())
            if not isinstance(self.credentials, dict) or not self.credentials:
                raise ValueError("Credentials must map SHA-256 token digests to principals")

    def authenticate(self, request) -> Principal:
        if self.settings.security.auth_mode == "local":
            peer = request.client.host if request.client else ""
            if peer not in {"127.0.0.1", "::1", "localhost", "testclient"}:
                raise HTTPException(403, "Local mode accepts only loopback clients")
            # Prevent a browser visiting an unrelated site from driving a local
            # unauthenticated server. The terminal and curl omit Origin.
            origin = request.headers.get("origin")
            host = request.url.hostname
            if host not in {"localhost", "127.0.0.1", "::1", "testserver"}:
                raise HTTPException(403, "Local mode rejects non-loopback Host headers")
            if origin and urlparse(origin).netloc != request.headers.get("host"):
                raise HTTPException(403, "Cross-origin local request rejected")
            return Principal(permissions=frozenset({"admin"}))
        authorization = request.headers.get("authorization", "")
        if not authorization.startswith("Bearer "):
            raise HTTPException(401, "Bearer token required")
        credential = self.credentials.get(token_fingerprint(authorization[7:]))
        if not credential:
            raise HTTPException(401, "Invalid bearer token")
        return Principal(credential["tenant_id"], credential["owner_id"], frozenset(credential.get("permissions", [])))
