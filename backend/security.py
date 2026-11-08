"""Private file permissions, secret lifecycle and Fernet helpers."""
from __future__ import annotations

import base64
import hashlib
import os
import sys
from pathlib import Path
from typing import Callable

from cryptography.fernet import InvalidToken
from fastapi import HTTPException

PRIVATE_DIR_MODE = 0o700
PRIVATE_FILE_MODE = 0o600


def set_private_mode(path: Path, mode: int) -> bool:
    """Best-effort chmod; failures are reported by callers that require privacy."""
    try:
        path.chmod(mode)
        return True
    except OSError:
        return False



def ensure_private_dir(path: Path, harden: bool = True) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=PRIVATE_DIR_MODE)
    if harden and not set_private_mode(path, PRIVATE_DIR_MODE):
        print(f"WARNING: could not restrict permissions on {path}", file=sys.stderr)



def read_secret_file(path: Path) -> str:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RuntimeError(f"Secret file is not readable: {path}") from exc
    if not value:
        raise RuntimeError(f"Secret file is empty: {path}")
    return value



def write_secret_file(path: Path, value: str, harden_parent: bool = True) -> None:
    if harden_parent:
        ensure_private_dir(path.parent)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, PRIVATE_FILE_MODE)
    except FileExistsError:
        return
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        set_private_mode(path, PRIVATE_FILE_MODE)
    except Exception:
        path.unlink(missing_ok=True)
        raise



def load_or_create_secret(name: str, default_path: Path, generator: Callable[[], str]) -> str:
    """Resolve NAME or NAME_FILE, otherwise create a persistent private secret.

    Explicit environment variables win over files. A configured *_FILE path is
    created with mode 600 when missing so containers and service managers can
    mount a stable path without shipping a secret in the image.
    """
    value = os.getenv(name, "").strip()
    if value:
        return value
    configured_file = os.getenv(f"{name}_FILE", "").strip()
    path = Path(configured_file).expanduser() if configured_file else default_path
    if path.exists():
        if path.stat().st_size == 0:
            if configured_file:
                raise RuntimeError(f"Secret file is empty: {path}")
            path.unlink(missing_ok=True)
        else:
            return read_secret_file(path)
    write_secret_file(path, generator(), harden_parent=not configured_file)
    print(f"Generated persistent secret at {path} with mode 600", file=sys.stderr)
    return read_secret_file(path)



def legacy_encryption_key(auth_secret: bytes) -> bytes:
    """Reproduce the pre-0.1 key derivation so existing provider keys migrate."""
    return base64.urlsafe_b64encode(hashlib.sha256(auth_secret + b"/provider-keys").digest())


def encrypt_key(value: str) -> str:
    from .config import SETTINGS

    return SETTINGS.fernet.encrypt(value.encode()).decode()


def decrypt_key(value: str) -> str:
    from .config import SETTINGS

    try:
        return SETTINGS.fernet.decrypt(value.encode()).decode()
    except InvalidToken as exc:
        raise HTTPException(500, "Provider key cannot be decrypted") from exc
