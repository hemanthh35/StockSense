"""Thin client for Groq's OpenAI-compatible chat API (model: gpt-oss). Everything else in the assistant talks to
this small interface, so tests can swap in a scripted fake and the provider could be replaced without touching the rest."""
import logging

import httpx

from ..config import settings

log = logging.getLogger("stocksense.assistant")


class LLMError(Exception):
    """The AI service failed. `status` is the HTTP status it answered with (0 = couldn't reach it)."""

    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status


class GroqClient:
    def __init__(self, api_key: str | None = None, model: str | None = None, base_url: str | None = None):
        self.api_key = api_key or settings.groq_api_key
        self.model = model or settings.groq_model
        self.base_url = (base_url or settings.groq_base_url).rstrip("/")

    def chat(self, messages: list[dict], tools: list[dict]) -> dict:
        """One chat-completion round. Returns the provider's JSON (`choices[0].message` holds text and/or tool calls)."""
        payload: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": 1200,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        if "gpt-oss" in self.model:
            payload["reasoning_effort"] = "low"  # short thinking keeps answers quick; the tools do the heavy lifting
        try:
            r = httpx.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                timeout=45,
            )
        except httpx.HTTPError as e:
            log.error("AI service unreachable: %s", type(e).__name__)
            raise LLMError("Couldn't reach the AI service.", 0)
        if r.status_code != 200:
            log.error("AI service answered %s: %s", r.status_code, r.text[:300])
            raise LLMError(f"AI service error {r.status_code}", r.status_code)
        try:
            return r.json()
        except ValueError:
            raise LLMError("The AI service sent an unreadable answer.", r.status_code)


def get_llm() -> GroqClient | None:
    """FastAPI dependency. None means the assistant isn't configured (no API key)."""
    return GroqClient() if settings.groq_api_key else None
