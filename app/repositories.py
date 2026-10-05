from __future__ import annotations

from pathlib import Path
import subprocess
from urllib.parse import urlparse

from app.chunking import sha256
from app.parsing import SUPPORTED


class GitIngestor:
    def __init__(self, settings, storage, ingestor):
        self.settings, self.storage, self.ingestor = settings, storage, ingestor

    @staticmethod
    def command(args, cwd=None):
        # No hooks, interactive credential prompts or submodule recursion.
        import os
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
        return subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-c", "protocol.file.allow=never", *args], cwd=cwd, env=env,
                              check=True, capture_output=True, timeout=300).stdout

    def ingest(self, repository, branch, index, principal, stage, progress):
        stage("processing")
        parsed = urlparse(repository)
        if parsed.scheme:
            if parsed.scheme != "https" or parsed.username or parsed.password:
                raise ValueError("Git URL must be HTTPS without embedded credentials")
            root = self.settings.data_dir / "repositories" / sha256(repository.encode())[:24]
            if not root.exists():
                root.parent.mkdir(parents=True, exist_ok=True)
                args = ["clone", "--depth", "1", "--no-recurse-submodules"]
                if branch:
                    if branch.startswith("-"):
                        raise ValueError("Invalid branch")
                    args += ["--branch", branch]
                self.command([*args, "--", repository, str(root)])
            else:
                self.command(["fetch", "--depth", "1", "origin", branch or "HEAD"], root)
                self.command(["reset", "--hard", "FETCH_HEAD"], root)
        else:
            root = Path(repository).resolve()
            if not (root / ".git").exists():
                raise ValueError("Expected a local Git checkout")
        paths = self.command(["ls-files", "-z"], root).decode().split("\0")
        paths = [root / name for name in paths if name and (root / name).suffix.lower() in SUPPORTED]
        results, current = [], set()
        for path in paths:
            if path.is_symlink() or root not in path.resolve().parents:
                continue
            current.add(str(path))
            if path.is_file():
                results.append(self.ingestor.index_file(path, index, principal, repository, stage))
                progress(len(results), sum(result["status"] == "failed" for result in results), len(paths))
        deleted = []
        with self.ingestor.lock, self.storage.connect() as con:
            rows = con.execute("SELECT id,path FROM documents WHERE repository=? AND tenant_id=? AND owner_id=?", (repository, principal.tenant_id, principal.owner_id)).fetchall()
            for row in rows:
                if row["path"] not in current:
                    self.ingestor.vector.delete(con, index["id"], row["id"])
                    con.execute("UPDATE documents SET status='deleted' WHERE id=?", (row["id"],))
                    deleted.append(row["path"])
            if deleted:
                con.execute("UPDATE rag_indexes SET validated=0,revision=revision+1 WHERE id=?", (index["id"],))
        commit = self.command(["rev-parse", "HEAD"], root).decode().strip()
        return {"summary": {"repository": repository, "commit": commit, "documents_scanned": len(results), "documents_deleted": deleted,
                            "documents_failed": [result["filename"] for result in results if result["status"] == "failed"],
                            "new_embeddings": sum(result.get("new_embeddings", 0) for result in results),
                            "reused_embeddings": sum(result.get("reused_embeddings", 0) for result in results)}, "results": results}
