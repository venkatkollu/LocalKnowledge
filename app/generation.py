from __future__ import annotations

import time

import httpx

class LocalGenerator:
    def __init__(self, settings):
        self.settings = settings
        self.model = settings.generation.model

    def complete(self, system: str, user: str, model: str | None = None) -> dict:
        model = model or self.model
        started = time.perf_counter()
        errors = []
        providers = [self.settings.generation.provider]
        for provider in providers:
            try:
                if provider == "lmstudio":
                    response = httpx.post(f"{self.settings.lmstudio_url}/chat/completions", json={
                        "model": model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                        "temperature": 0.05, "max_tokens": self.settings.generation.max_tokens, "stream": False}, timeout=180, trust_env=False)
                    response.raise_for_status()
                    text = response.json().get("choices", [{}])[0].get("message", {}).get("content", "").strip()
                    usage = response.json().get("usage", {})
                elif provider == "ollama":
                    response = httpx.post(f"{self.settings.ollama_url}/api/generate", json={
                        "model": model, "prompt": f"{system}\n\n{user}", "stream": False,
                        "options": {"temperature": 0.05, "seed": 42, "num_ctx": 8192, "num_predict": self.settings.generation.max_tokens}}, timeout=180, trust_env=False)
                    response.raise_for_status()
                    payload = response.json()
                    text, usage = payload.get("response", "").strip(), {
                        "prompt_tokens": payload.get("prompt_eval_count", 0), "completion_tokens": payload.get("eval_count", 0)}
                else:
                    raise ValueError(f"Unsupported generation provider {provider}")
                if text:
                    return {"text": text, "model": model, "provider": provider,
                            "latency_ms": round((time.perf_counter() - started) * 1000, 2), "usage": usage}
                errors.append(f"{provider}: empty response")
            except Exception as exc:
                errors.append(f"{provider}: {exc}")
        raise RuntimeError("; ".join(errors))
