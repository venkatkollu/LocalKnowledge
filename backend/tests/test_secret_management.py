"""Secret lifecycle tests.

Run with: python3 -m unittest discover -s backend/tests -v
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CLEARED_ENV = (
    "KNOWLEDGEOS_AUTH_SECRET",
    "KNOWLEDGEOS_AUTH_SECRET_FILE",
    "KNOWLEDGEOS_ENCRYPTION_KEY",
    "KNOWLEDGEOS_ENCRYPTION_KEY_FILE",
    "KNOWLEDGEOS_ALLOW_ANONYMOUS",
)


class SecretManagementTests(unittest.TestCase):
    def run_snippet(self, snippet: str, data_dir: Path, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        env = {key: value for key, value in os.environ.items() if key not in CLEARED_ENV}
        env["KNOWLEDGEOS_DATA_DIR"] = str(data_dir)
        env["PYTHONPATH"] = str(REPO_ROOT)
        env.update(extra_env or {})
        return subprocess.run(
            [sys.executable, "-c", snippet],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )

    def assert_success(self, result: subprocess.CompletedProcess[str]) -> None:
        self.assertEqual(result.returncode, 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}")

    def test_fresh_start_generates_private_secrets(self) -> None:
        snippet = r"""
import os, sqlite3
from pathlib import Path
import backend.main as m

data = Path(os.environ["KNOWLEDGEOS_DATA_DIR"])
m.init_db()

def mode(path):
    return path.stat().st_mode & 0o777

if os.name == "posix":
    assert mode(data) == 0o700, mode(data)
    assert mode(data / "files") == 0o700
    assert mode(data / ".auth_secret") == 0o600
    assert mode(data / ".encryption_key") == 0o600
    assert mode(data / "knowledgeos.sqlite3") == 0o600
assert m.SETTINGS.auth_secret != b"local-development-secret"
assert len(m.SETTINGS.auth_secret) >= 32
assert m.decrypt_key(m.encrypt_key("round-trip")) == "round-trip"
with sqlite3.connect(m.SETTINGS.db_path) as connection:
    assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
print("OK")
"""
        with tempfile.TemporaryDirectory(prefix="lkos-secret-fresh-") as directory:
            result = self.run_snippet(snippet, Path(directory))
            self.assert_success(result)
            self.assertIn("OK", result.stdout)

    def test_legacy_default_key_is_reencrypted_with_backup(self) -> None:
        snippet = r"""
import base64, hashlib, os, sqlite3, uuid
from pathlib import Path
from cryptography.fernet import Fernet, InvalidToken
import backend.main as m

data = Path(os.environ["KNOWLEDGEOS_DATA_DIR"])
legacy = Fernet(base64.urlsafe_b64encode(hashlib.sha256(b"local-development-secret/provider-keys").digest()))
plaintext = "sk-legacy-test-key"
token = legacy.encrypt(plaintext.encode()).decode()

with sqlite3.connect(m.SETTINGS.db_path) as connection:
    connection.executescript(m.SCHEMA)
    connection.execute("INSERT OR IGNORE INTO workspaces(id,name,created_at) VALUES ('default','Default workspace',0)")
    connection.execute(
        "INSERT INTO provider_profiles(id,workspace_id,name,kind,base_url,model,role,encrypted_key,enabled,failure_count,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,1,0,0,0)",
        (str(uuid.uuid4()), "default", "legacy", "OpenAI", "https://example.invalid/v1", "test", "Generation", token),
    )
    connection.commit()

m.init_db()
with sqlite3.connect(m.SETTINGS.db_path) as connection:
    migrated = connection.execute("SELECT encrypted_key FROM provider_profiles").fetchone()[0]
assert migrated != token
assert m.decrypt_key(migrated) == plaintext

backups = sorted((data / "backups").glob("*.sqlite3"))
assert len(backups) == 1, backups
if os.name == "posix":
    assert backups[0].stat().st_mode & 0o777 == 0o600
with sqlite3.connect(backups[0]) as connection:
    backup_token = connection.execute("SELECT encrypted_key FROM provider_profiles").fetchone()[0]
assert backup_token == migrated
assert m.decrypt_key(backup_token) == plaintext
try:
    legacy.decrypt(backup_token.encode())
    raise AssertionError("legacy key must not decrypt the rewritten backup")
except InvalidToken:
    pass

m.init_db()
assert len(list((data / "backups").glob("*.sqlite3"))) == 1
print("OK")
"""
        with tempfile.TemporaryDirectory(prefix="lkos-secret-legacy-") as directory:
            result = self.run_snippet(snippet, Path(directory))
            self.assert_success(result)
            self.assertIn("OK", result.stdout)

    def test_custom_auth_secret_is_preserved_and_key_is_independent(self) -> None:
        snippet = r"""
import base64, hashlib, os
from pathlib import Path
import backend.main as m

data = Path(os.environ["KNOWLEDGEOS_DATA_DIR"])
auth = b"custom-secret-that-is-long-enough-123"
derived = base64.urlsafe_b64encode(hashlib.sha256(auth + b"/provider-keys").digest())
assert m.SETTINGS.auth_secret == auth
assert m.SETTINGS.encryption_key != derived
assert not (data / ".auth_secret").exists()
if os.name == "posix":
    assert (data / ".encryption_key").stat().st_mode & 0o777 == 0o600
print("OK")
"""
        with tempfile.TemporaryDirectory(prefix="lkos-secret-custom-") as directory:
            result = self.run_snippet(
                snippet,
                Path(directory),
                {"KNOWLEDGEOS_AUTH_SECRET": "custom-secret-that-is-long-enough-123"},
            )
            self.assert_success(result)
            self.assertIn("OK", result.stdout)

    def test_api_never_returns_provider_key(self) -> None:
        snippet = r"""
import os
from fastapi.testclient import TestClient
import backend.main as m

with TestClient(m.app) as client:
    assert client.get("/api/health").status_code == 200
    created = client.post(
        "/api/models/profiles",
        json={
            "name": "Local test",
            "kind": "OpenAI-compatible",
            "base_url": "http://127.0.0.1:9/v1",
            "model": "test",
            "role": "Generation",
            "api_key": "sk-test-must-not-leak",
        },
    )
    assert created.status_code == 201, created.text
    assert "sk-test-must-not-leak" not in created.text
    assert "encrypted_key" not in created.text
    listed = client.get("/api/models/profiles")
    assert listed.status_code == 200
    assert "sk-test-must-not-leak" not in listed.text
    assert "encrypted_key" not in listed.text
print("OK")
"""
        with tempfile.TemporaryDirectory(prefix="lkos-secret-api-") as directory:
            result = self.run_snippet(snippet, Path(directory))
            self.assert_success(result)
            self.assertIn("OK", result.stdout)

    def test_known_default_auth_secret_fails_closed_when_auth_required(self) -> None:
        snippet = r"""
import backend.main
print("SHOULD_NOT_START")
"""
        with tempfile.TemporaryDirectory(prefix="lkos-secret-closed-") as directory:
            result = self.run_snippet(
                snippet,
                Path(directory),
                {
                    "KNOWLEDGEOS_AUTH_SECRET": "local-development-secret",
                    "KNOWLEDGEOS_ALLOW_ANONYMOUS": "false",
                },
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("SHOULD_NOT_START", result.stdout)
            self.assertIn("development default", result.stderr)

    def test_invalid_encryption_key_fails_closed(self) -> None:
        snippet = r"""
import backend.main
print("SHOULD_NOT_START")
"""
        with tempfile.TemporaryDirectory(prefix="lkos-secret-invalid-") as directory:
            result = self.run_snippet(
                snippet,
                Path(directory),
                {"KNOWLEDGEOS_ENCRYPTION_KEY": "not-a-fernet-key"},
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("SHOULD_NOT_START", result.stdout)
            self.assertIn("valid Fernet key", result.stderr)


if __name__ == "__main__":
    unittest.main()
