from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import threading
import time
import uuid


class QueueFull(RuntimeError):
    pass


class JobManager:
    def __init__(self, settings, storage):
        self.storage = storage
        self.executor = ThreadPoolExecutor(max_workers=settings.workers, thread_name_prefix="ingestion")
        self.capacity = threading.BoundedSemaphore(settings.queue_capacity)

    def recover(self):
        with self.storage.connect() as con:
            con.execute("UPDATE ingestion_jobs SET status='failed',stage='failed',error='Interrupted by process restart; resubmit job',finished_at=? WHERE status NOT IN ('completed','failed')", (time.time(),))

    def update(self, job_id, **values):
        with self.storage.connect() as con:
            con.execute(f"UPDATE ingestion_jobs SET {','.join(key + '=?' for key in values)} WHERE id=?", [json.dumps(value) if isinstance(value, (dict, list)) else value for value in values.values()] + [job_id])

    def stage(self, job_id, name):
        with self.storage.connect() as con:
            row = con.execute("SELECT stage_history FROM ingestion_jobs WHERE id=?", (job_id,)).fetchone()
            history = json.loads(row[0])
            history.append({"stage": name, "timestamp": time.time()})
            con.execute("UPDATE ingestion_jobs SET status=?,stage=?,stage_history=? WHERE id=?", (name, name, json.dumps(history), job_id))

    def submit(self, kind, principal, payload, operation):
        if not self.capacity.acquire(blocking=False):
            raise QueueFull("Ingestion queue is full")
        job_id = str(uuid.uuid4())
        try:
            with self.storage.connect() as con:
                con.execute("INSERT INTO ingestion_jobs(id,kind,status,stage,tenant_id,owner_id,payload,created_at) VALUES(?,?,?,?,?,?,?,?)",
                    (job_id, kind, "queued", "queued", principal.tenant_id, principal.owner_id, json.dumps(payload), time.time()))
            self.executor.submit(self._run, job_id, operation)
        except Exception:
            self.capacity.release()
            raise
        return {"job_id": job_id, "status": "queued"}

    def _run(self, job_id, operation):
        try:
            self.update(job_id, status="processing", stage="processing", started_at=time.time())
            result = operation(lambda stage: self.stage(job_id, stage),
                               lambda completed, failed, total: self.update(job_id, completed=completed, failed=failed, total=total))
            failed = result.get("status") == "failed" or bool(result.get("summary", {}).get("documents_failed"))
            self.update(job_id, status="failed" if failed else "completed", stage="failed" if failed else "completed",
                        summary=result.get("summary", result), error=result.get("error"), finished_at=time.time())
        except Exception as exc:
            self.update(job_id, status="failed", stage="failed", error=str(exc), finished_at=time.time())
        finally:
            self.capacity.release()
