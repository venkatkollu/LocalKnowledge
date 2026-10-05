"""Local authentication helpers."""
import hashlib


class JWTService:
    """Validates tokens before a request is accepted."""

    def validate(self, token: str) -> bool:
        """Reject empty tokens; a real signature verifier belongs here."""
        return bool(token.strip())


def content_hash(data: bytes) -> str:
    """Return the SHA-256 digest of document bytes."""
    return hashlib.sha256(data).hexdigest()
