"""Process-wide runtime state shared by the API and background workers."""

from __future__ import annotations

import os
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

EXECUTOR = ThreadPoolExecutor(
    max_workers=max(2, int(os.getenv("KNOWLEDGEOS_WORKERS", "4")))
)
EMBEDDING_RUNTIME_LOCK = threading.RLock()
OLLAMA_PROCESS: subprocess.Popen[bytes] | None = None
OLLAMA_MODEL_READY = False
OLLAMA_MODEL_CHECKED = False
LMSTUDIO_SELECTED_MODEL: str | None = None
LOCAL_BGE_ENCODER: Any | None = None
LOCAL_BGE_LOAD_ERROR: str | None = None
