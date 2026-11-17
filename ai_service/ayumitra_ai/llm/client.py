"""
Client for any OpenAI-compatible chat server.

Local (CPU): llama.cpp `llama-server` running the official Qwen2.5-3B-Instruct Q4_K_M GGUF.
GPU host:    vLLM serving Qwen/Qwen2.5-3B-Instruct with bitsandbytes 4-bit (NF4) quantisation.
Only the base URL changes between the two.
"""

from __future__ import annotations

import httpx


class LLMError(RuntimeError):
    pass


class LLMClient:
    def __init__(self, base_url: str, model: str, api_key: str = "", timeout_s: float = 240.0,
                 temperature: float = 0.1, max_tokens: int = 700):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature, self.max_tokens = temperature, max_tokens
        self._http = httpx.Client(timeout=timeout_s, headers={"Authorization": f"Bearer {api_key}"} if api_key else {})

    def health(self) -> bool:
        try:
            return self._http.get(f"{self.base_url}/models", timeout=5).status_code == 200
        except httpx.HTTPError:
            return False

    def complete(self, messages: list[dict], *, json_schema: dict | None = None, max_tokens: int | None = None,
                 temperature: float | None = None) -> str:
        body: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature if temperature is None else temperature,
            "max_tokens": max_tokens or self.max_tokens,
            "seed": 7,
        }
        if json_schema is not None:
            # Grammar-constrained decoding: the server can only emit JSON matching the schema.
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "response", "strict": True, "schema": json_schema},
            }
        try:
            resp = self._http.post(f"{self.base_url}/chat/completions", json=body)
        except httpx.HTTPError as exc:
            raise LLMError(f"LLM server unreachable at {self.base_url}: {exc}") from exc
        if resp.status_code != 200:
            raise LLMError(f"LLM server returned {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise LLMError(f"Unexpected LLM response: {str(data)[:300]}") from exc
