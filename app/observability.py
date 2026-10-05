from __future__ import annotations

from contextlib import contextmanager
import json
import logging
import time
import uuid

logger = logging.getLogger("knowledgeos.traces")


class Trace:
    """OTel-shaped spans, with content-free persisted metadata by default."""
    def __init__(self):
        self.trace_id = uuid.uuid4().hex
        self.started = time.perf_counter()
        self.spans = []
        self.attributes = {}

    @contextmanager
    def span(self, name: str):
        start = time.perf_counter()
        attributes = {}
        status = "ok"
        try:
            yield attributes
        except Exception as exc:
            status = "error"
            attributes["error_type"] = type(exc).__name__
            raise
        finally:
            self.spans.append({"name": name, "span_id": uuid.uuid4().hex[:16], "status": status,
                               "duration_ms": (time.perf_counter() - start) * 1000, "attributes": attributes})

    def as_dict(self) -> dict:
        return {"trace_id": self.trace_id, "latency_ms": (time.perf_counter() - self.started) * 1000,
                "spans": self.spans, "attributes": self.attributes}

    def persist(self, storage, principal, index_id: str):
        payload = self.as_dict()
        with storage.connect() as con:
            con.execute("INSERT INTO rag_traces VALUES(?,?,?,?,?,?)", (self.trace_id, principal.tenant_id, principal.owner_id, index_id, json.dumps(payload), time.time()))
        logger.info(json.dumps(payload))
        return payload
