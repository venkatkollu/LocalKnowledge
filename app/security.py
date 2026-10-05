from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

INJECTION_PATTERNS = (
    r"ignore\s+(?:all\s+)?(?:previous|prior)\s+instructions",
    r"reveal\s+(?:the\s+)?(?:system|developer)\s+prompt",
    r"send\s+(?:all\s+)?(?:private|secret|indexed)\s+(?:documents|data)",
    r"invent\s+(?:a\s+)?citation",
    r"follow\s+these\s+instructions",
)
INJECTION_RE = re.compile("|".join(INJECTION_PATTERNS), re.I)


@dataclass(frozen=True)
class Principal:
    tenant_id: str = "local"
    owner_id: str = "local"
    permissions: frozenset[str] = frozenset()

    @property
    def admin(self) -> bool:
        return "admin" in self.permissions


def injection_detected(text: str) -> bool:
    return bool(INJECTION_RE.search(text or ""))


def evidence_is_untrusted(text: str) -> bool:
    return injection_detected(text) or bool(re.search(r"(?:system prompt|developer message|exfiltrat|attacker\.invalid)", text or "", re.I))


def acl_clause(alias: str, principal: Principal) -> tuple[str, list[str]]:
    """SQL ACL predicate. It is deliberately applied in each retrieval WHERE clause."""
    return (f"({alias}.tenant_id = ? AND ({alias}.visibility = 'public' OR {alias}.owner_id = ? OR "
            f"{alias}.visibility = 'tenant' OR EXISTS "
            f"(SELECT 1 FROM json_each({alias}.permissions) WHERE value = ?)))",
            [principal.tenant_id, principal.owner_id, principal.owner_id])


def safe_authorization(owner_id: str, tenant_id: str, visibility: str, principal: Principal) -> bool:
    return tenant_id == principal.tenant_id and (visibility in {"public", "tenant"} or owner_id == principal.owner_id)


def token_fingerprint(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
