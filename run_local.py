from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import threading
import time
from urllib.parse import urlparse

import httpx
import uvicorn


def port_open(url: str) -> bool:
    parsed = urlparse(url)
    try:
        with socket.create_connection((parsed.hostname or "127.0.0.1", parsed.port or 80), timeout=0.4):
            return True
    except OSError:
        return False


def wait_for_api(base_url: str, seconds: int = 20) -> dict:
    deadline = time.time() + seconds
    last_error = "API did not become ready"
    while time.time() < deadline:
        try:
            response = httpx.get(f"{base_url}/health", timeout=2)
            if response.is_success:
                return response.json()
        except Exception as exc:
            last_error = str(exc)
        time.sleep(0.25)
    raise RuntimeError(last_error)


def print_health(health: dict) -> None:
    print("\nKnowledgeOS is ready")
    print(f"  Documents: {health.get('documents', 0)} | Embedded chunks: {health.get('embedded_chunks', 0)}")
    print(f"  LLM provider: {health.get('llm_provider')} | Model: {health.get('lmstudio_model') or health.get('generation_model')}")
    if health.get("llm_provider") == "lmstudio":
        if health.get("lmstudio_available"):
            print(f"  LM Studio: connected at {health.get('lmstudio_url')}")
        else:
            print(f"  LM Studio: NOT CONNECTED at {health.get('lmstudio_url')}")
            print("  Start LM Studio -> Developer -> Start Server, then run this command again.")
            if health.get("lmstudio_error"):
                print(f"  Connection detail: {health['lmstudio_error']}")
    print("\nCommands: /sync  /health  /help  /quit")


def print_result(data: dict) -> None:
    print("\n" + "=" * 78)
    print("ANSWER")
    print("=" * 78)
    print(data.get("answer", "No answer returned."))
    if data.get("provider_error"):
        print(f"\n[LLM connection warning] {data['provider_error']}")
    print("\n" + "-" * 78)
    print("RETRIEVAL EVALUATION")
    print("-" * 78)
    stats = data.get("stats", {})
    labels = [("Dense candidates", "dense_candidates"), ("BM25 candidates", "bm25_candidates"), ("RRF candidates", "rrf_candidates"), ("Reranked", "reranked"), ("Final context", "final_context"), ("Retrieval latency", "retrieval_ms"), ("Generation latency", "generation_ms"), ("Total latency", "latency_ms")]
    for label, key in labels:
        suffix = " ms" if key.endswith("_ms") else ""
        print(f"{label:<22} {stats.get(key, '—')}{suffix}")
    print(f"Model used             {data.get('model', '—')}")
    print("\nSOURCES")
    for citation in data.get("citations", []):
        print(f"[{citation['index']}] {citation['filename']} | {citation.get('section') or 'Document'} | version {citation.get('version', 1)}")
        print(f"    {citation.get('excerpt', '').replace(chr(10), ' ')[:180]}")
    print()


def wait_for_sync(base_url: str, job_id: str) -> None:
    print(f"Sync job {job_id[:8]} started. Waiting for chunk-level changes…")
    deadline = time.time() + 300
    while time.time() < deadline:
        status = httpx.get(f"{base_url}/jobs/{job_id}", timeout=10).json()
        if status.get("status") in {"completed", "failed"}:
            print(json.dumps(status.get("summary") or {"status": status.get("status"), "error": status.get("error")}, indent=2))
            return
        time.sleep(0.5)
    print("Sync is still running. Use the API job endpoint to inspect it.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Start KnowledgeOS and use it from the terminal.")
    parser.add_argument("--host", default=os.getenv("KNOWLEDGEOS_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("KNOWLEDGEOS_PORT", "8000")))
    args = parser.parse_args()
    base_url = f"http://{args.host}:{args.port}"
    server_thread = None
    server = None
    owns_server = not port_open(base_url)
    if owns_server:
        config = uvicorn.Config("app:app", host=args.host, port=args.port, log_level="warning")
        server = uvicorn.Server(config)
        server_thread = threading.Thread(target=server.run, daemon=True)
        server_thread.start()
    try:
        health = wait_for_api(base_url)
        print_health(health)
        while True:
            try:
                prompt = input("\nYou> ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nGoodbye.")
                break
            if not prompt:
                continue
            command = prompt.lower()
            if command in {"/quit", "/exit", "quit", "exit"}:
                break
            if command == "/help":
                print("Enter a question. /sync queues indexing, /health checks LM Studio, /quit exits.")
                continue
            if command == "/health":
                print_health(httpx.get(f"{base_url}/health", timeout=5).json())
                continue
            if command == "/sync":
                response = httpx.post(f"{base_url}/documents/sync", timeout=10)
                payload = response.json()
                print(json.dumps(payload, indent=2))
                wait_for_sync(base_url, payload["job_id"])
                continue
            response = httpx.post(f"{base_url}/chat", json={"query": prompt, "top_k": 6}, timeout=240)
            if not response.is_success:
                print(f"Request failed ({response.status_code}): {response.text}")
                continue
            print_result(response.json())
    finally:
        if server is not None:
            server.should_exit = True
            if server_thread:
                server_thread.join(timeout=3)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
