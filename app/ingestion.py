from __future__ import annotations

import json
from pathlib import Path
import threading
import time

from app.chunking import StructuredChunker, describe_chunk, sha256
from app.config import Settings
from app.embeddings import embedding_for, validate_vectors
from app.generation import LocalGenerator
from app.parsing import StructuredParser, SUPPORTED
from app.security import Principal
from app.storage import SQLiteVectorStore


class Ingestor:
    """Atomic per-document commits with network/model work outside write locks."""
    def __init__(self, settings, storage):
        self.settings, self.storage = settings, storage
        self.parser = StructuredParser()
        self.vector = SQLiteVectorStore(storage)
        # Serialize per-process document updates and index lifecycle operations.
        # SQLite remains the inter-process integrity boundary; one API worker is
        # the supported deployment until a durable external worker is supplied.
        self.lock = threading.RLock()

    def index_file(self, path: Path, index: dict, principal: Principal = Principal(), repository: str | None = None,
                   stage=lambda name: None) -> dict:
        with self.lock:
            return self._index_file(path, index, principal, repository, stage)

    def _index_file(self, path, index, principal, repository, stage):
        index = self.storage.get_index(index["id"])
        if index["status"] == "retired":
            return {"path": str(path), "filename": path.name, "status": "failed", "error": "Retired index is read-only"}
        if path.suffix.lower() not in SUPPORTED:
            return {"path": str(path), "status": "skipped"}
        if path.is_symlink():
            return {"path": str(path), "filename": path.name, "status": "failed", "error": "Symlink ingestion is disabled"}
        cfg = Settings.model_validate({key: value for key, value in index["config"].items() if key != "registry"})
        pipeline_hash = self.storage.pipeline_hash(index)
        started = time.perf_counter()
        try:
            registry = index["config"]["registry"]
            if registry["parser_version"] != self.parser.version or registry["chunker_version"] != StructuredChunker.version:
                raise ValueError("Parser/chunker runtime changed; create a new index before ingestion")
            stage("parsing")
            raw, stat = path.read_bytes(), path.stat()
            if len(raw) > self.settings.security.max_upload_bytes:
                raise ValueError("File exceeds configured size limit")
            content_hash = sha256(raw)
            with self.storage.connect() as con:
                old = con.execute("SELECT * FROM documents WHERE path=?", (str(path),)).fetchone()
                if old and (old["tenant_id"], old["owner_id"]) != (principal.tenant_id, principal.owner_id):
                    raise PermissionError("Document belongs to a different principal")
                # Skip only the version present in this specific index, and only
                # if bytes and the entire ingestion pipeline match.
                member = con.execute("SELECT v.content_hash,v.pipeline_hash,v.version,count(*) n FROM rag_members m JOIN rag_chunks c ON c.id=m.chunk_id JOIN document_versions v ON v.id=c.version_id WHERE m.index_id=? AND c.document_id=? GROUP BY v.id", (index["id"], old["id"] if old else -1)).fetchone()
                if member and member["content_hash"] == content_hash and member["pipeline_hash"] == pipeline_hash:
                    return {"path": str(path), "filename": path.name, "status": "unchanged", "change_type": "unchanged", "version": member["version"],
                            "chunks_before": member["n"], "chunks_after": member["n"], "reused_embeddings": member["n"], "new_embeddings": 0, "added_chunks": 0, "removed_chunks": 0}
                prior = con.execute("SELECT contextual_content,embedding,chunk_hash FROM rag_chunks WHERE document_id=? AND pipeline_hash=? ORDER BY id DESC", (old["id"] if old else -1, pipeline_hash)).fetchall()
            reusable = {row["contextual_content"]: row["embedding"] for row in prior}
            structures = self.parser.parse(path, raw)
            if repository:
                for structure in structures:
                    structure["repository"] = repository
                    structure["file"] = str(path)
                    if structure.get("language") == "python":
                        structure["module"] = ".".join(path.with_suffix("").parts[-3:])
            stage("structure_extraction")
            stage("chunking")
            parts = StructuredChunker(cfg.chunk_size, cfg.chunk_overlap).split(structures)
            if not parts:
                raise ValueError("No extractable text (scanned PDFs require an OCR adapter)")
            stage("contextualizing")
            local_generator = LocalGenerator(cfg)
            for part in parts:
                description, contextual = describe_chunk(part, path.name, cfg.retrieval.contextual_chunking, local_generator)
                part.update(contextual_description=description, contextual_content=contextual,
                            chunk_hash=sha256(part["raw_content"].encode()))
            stage("embedding")
            embedder = embedding_for(self.settings, index)
            missing = [part for part in parts if part["contextual_content"] not in reusable]
            fresh = {}
            for offset in range(0, len(missing), cfg.embeddings.batch_size):
                batch = missing[offset:offset + cfg.embeddings.batch_size]
                vectors = embedder.embed([part["contextual_content"] for part in batch])
                validate_vectors(vectors, len(batch), index["embedding_dimension"])
                fresh.update({part["contextual_content"]: json.dumps(vector) for part, vector in zip(batch, vectors)})
            stage("indexing")
            with self.storage.connect() as con:
                if index["status"] == "retired":
                    raise ValueError("Retired index is read-only; create a migration index")
                if old:
                    document_id, version = old["id"], old["version"] + 1
                    con.execute("UPDATE documents SET content_hash=?,size=?,modified=?,version=?,status='indexed',error=NULL,updated_at=? WHERE id=?",
                                (content_hash, len(raw), stat.st_mtime, version, time.time(), document_id))
                else:
                    version = 1
                    document_id = con.execute("INSERT INTO documents(path,filename,content_hash,size,modified,version,status,updated_at,tenant_id,owner_id,visibility,permissions,repository) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (str(path), path.name, content_hash, len(raw), stat.st_mtime, version, "indexed", time.time(), principal.tenant_id, principal.owner_id, "private", "[]", repository)).lastrowid
                version_id = con.execute("INSERT INTO document_versions(document_id,version,content_hash,size,parser_version,chunker_version,embedding_model,created_at,pipeline_hash,index_id) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (document_id, version, content_hash, len(raw), self.parser.version, StructuredChunker.version, index["embedding_model"], time.time(), pipeline_hash, index["id"])).lastrowid
                parents = {}
                for part in parts:
                    p = part["parent_index"]
                    if p not in parents:
                        structure = structures[p]
                        parents[p] = con.execute("INSERT INTO rag_parents(version_id,content,metadata) VALUES(?,?,?)", (version_id, structure["content"], json.dumps({key: val for key, val in structure.items() if key != "content"}))).lastrowid
                self.vector.delete(con, index["id"], document_id)
                for ordinal, part in enumerate(parts):
                    metadata = {**part["metadata"], "source": path.name, "chunk_ordinal": ordinal}
                    chunk_id = self.vector.upsert(con, document_id=document_id, version_id=version_id, parent_id=parents[part["parent_index"]], ordinal=ordinal,
                        chunk_hash=part["chunk_hash"], raw_content=part["raw_content"], contextual_content=part["contextual_content"],
                        contextual_description=part["contextual_description"], metadata=json.dumps(metadata),
                        embedding=reusable.get(part["contextual_content"], fresh.get(part["contextual_content"])),
                        embedding_model=index["embedding_model"], embedding_dimension=index["embedding_dimension"], pipeline_hash=pipeline_hash)
                    con.execute("INSERT INTO rag_members VALUES(?,?)", (index["id"], chunk_id))
                    con.execute("INSERT INTO rag_fts(rowid,contextual_content,filename,section) VALUES(?,?,?,?)", (chunk_id, part["contextual_content"], path.name, metadata.get("section", "Document")))
                con.execute("UPDATE rag_indexes SET validated=0,validation=NULL,revision=revision+1 WHERE id=?", (index["id"],))
            stage("validating")
            old_hashes = {row["chunk_hash"] for row in prior}
            new_hashes = {part["chunk_hash"] for part in parts}
            return {"path": str(path), "filename": path.name, "status": "indexed", "change_type": "changed" if old else "added", "version": version,
                    "chunks_before": member["n"] if member else 0, "chunks_after": len(parts), "new_embeddings": len(missing),
                    "reused_embeddings": len(parts) - len(missing), "added_chunks": len(new_hashes - old_hashes), "removed_chunks": len(old_hashes - new_hashes),
                    "embedding_model": index["embedding_model"], "latency_ms": (time.perf_counter() - started) * 1000}
        except Exception as exc:
            # The last committed index remains searchable after a failed update.
            return {"path": str(path), "filename": path.name, "status": "failed", "error": str(exc)}

    def scan(self, index, principal=Principal(), stage=lambda name: None, progress=lambda completed, failed, total: None, root: Path | None = None):
        root = (root or self.settings.knowledge_dir).resolve()
        paths = sorted(path for path in root.rglob("*") if path.is_file() and not path.is_symlink() and path.suffix.lower() in SUPPORTED and root in path.resolve().parents)
        results = []
        for path in paths:
            results.append(self.index_file(path, index, principal, stage=stage))
            progress(len(results), sum(result["status"] == "failed" for result in results), len(paths))
        deleted = []
        with self.lock, self.storage.connect() as con:
            rows = con.execute("SELECT id,path FROM documents WHERE tenant_id=? AND owner_id=? AND status != 'deleted'", (principal.tenant_id, principal.owner_id)).fetchall()
            current = {str(path) for path in paths}
            for row in rows:
                if root in Path(row["path"]).resolve().parents and row["path"] not in current:
                    self.vector.delete(con, index["id"], row["id"])
                    con.execute("UPDATE documents SET status='deleted' WHERE id=?", (row["id"],))
                    deleted.append(row["path"])
            if deleted:
                con.execute("UPDATE rag_indexes SET validated=0,revision=revision+1 WHERE id=?", (index["id"],))
        summary = {"documents_scanned": len(paths), "documents_deleted": deleted}
        for kind in ("added", "changed", "unchanged"):
            summary[f"documents_{kind}"] = [result["filename"] for result in results if result.get("change_type") == kind]
        summary["documents_failed"] = [result["filename"] for result in results if result["status"] == "failed"]
        for key in ("chunks_before", "chunks_after", "new_embeddings", "reused_embeddings", "added_chunks", "removed_chunks"):
            summary[key] = sum(result.get(key, 0) for result in results)
        return {"results": results, "summary": summary, "files": len(paths), "deleted": len(deleted), "index_id": index["id"]}
