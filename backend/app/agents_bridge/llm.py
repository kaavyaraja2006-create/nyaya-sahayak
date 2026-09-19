"""LLM providers satisfying the agents' minimal protocol.

    generate(*, system_prompt: str, user_prompt: str) -> str

Two implementations:

* `GeminiLLMProvider` — a real call over HTTP, used when an API key is set.
* `UnavailableLLMProvider` — raises on every call. Used when no key is
  configured. Every agent treats a provider failure as a degraded run with an
  explicit warning, so an unconfigured deployment produces empty, clearly
  flagged results rather than invented ones.
"""
from __future__ import annotations

import logging

import httpx

from ..config import settings

log = logging.getLogger("nyayasahayak.agents_bridge.llm")


class LLMUnavailable(RuntimeError):
    pass


class UnavailableLLMProvider:
    """Fails loudly. Never fabricates an answer to keep a pipeline green."""

    mode = "unavailable"

    def generate(self, *, system_prompt: str, user_prompt: str) -> str:
        raise LLMUnavailable(
            "No AI provider is configured (set GEMINI_API_KEY). "
            "No claims, findings or citations were generated this run."
        )


class GeminiLLMProvider:
    """Google Generative Language API, called synchronously.

    The agents run inside a worker thread, so a blocking client is correct
    here and avoids an async/sync split across the agent package.
    """

    mode = "gemini"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self.api_key = api_key or settings.gemini_api_key
        self.model = model or settings.ai_model
        self.base_url = (base_url or settings.gemini_base_url).rstrip("/")
        self.timeout = timeout or settings.ai_timeout_seconds

    def generate(self, *, system_prompt: str, user_prompt: str) -> str:
        url = f"{self.base_url}/models/{self.model}:generateContent"
        payload = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": {"temperature": 0.0, "responseMimeType": "application/json"},
        }
        try:
            response = httpx.post(
                url,
                json=payload,
                params={"key": self.api_key},
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
        except Exception as exc:  # noqa: BLE001 - surfaced to the agent as a failure
            raise LLMUnavailable(f"Gemini request failed: {type(exc).__name__}: {exc}") from exc

        candidates = data.get("candidates") or []
        if not candidates:
            raise LLMUnavailable("Gemini returned no candidates.")
        parts = (candidates[0].get("content") or {}).get("parts") or []
        text = "".join(part.get("text", "") for part in parts)
        if not text.strip():
            raise LLMUnavailable("Gemini returned an empty response.")
        return text


def build_llm_provider():
    """Pick a provider from settings. Never raises at construction time."""
    if settings.ai_configured:
        return GeminiLLMProvider()
    log.warning(
        "AI provider not configured (provider=%s, key set=%s); "
        "the pipeline will run in degraded mode.",
        settings.ai_provider,
        bool(settings.gemini_api_key),
    )
    return UnavailableLLMProvider()
