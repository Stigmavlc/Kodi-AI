"""OpenRouter HTTP client (OpenAI-compatible).

Non-streaming chat() for simple calls (triage, preflight).
Streaming chat_stream() with chunk-level abort + mid-stream budget check —
see Task 3.5.

Spec: §1.10, §4.5.
"""
from __future__ import annotations
import json
from dataclasses import dataclass
from typing import Any
import requests

DEFAULT_PREFLIGHT_MODEL = "google/gemini-2.0-flash-001"
BASE_URL = "https://openrouter.ai/api/v1"


class LLMError(Exception):
    """Base for LLM client errors."""


class LLMAuthError(LLMError):
    """401 — invalid API key."""


class LLMNoCreditError(LLMError):
    """402 — insufficient credit."""


class LLMModelUnavailableError(LLMError):
    """404 / 422 — model not found or schema invalid. Route to fallback."""


class LLMRateLimitError(LLMError):
    """429 — caller should backoff (honor Retry-After)."""


class LLMServerError(LLMError):
    """5xx — caller should backoff + maybe fallback."""


@dataclass(frozen=True)
class ChatResponse:
    text: str
    model: str
    tokens_in: int
    tokens_out: int
    finish_reason: str
    tool_calls: list[dict] | None = None
    raw: dict | None = None


def _build_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/<user>/kodi-ai",
        "X-Title": "Kodi-AI",
    }


def chat(
    api_key: str,
    model: str,
    messages: list[dict],
    *,
    tools: list[dict] | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.2,
    timeout: tuple[float, float] = (5.0, 30.0),
) -> ChatResponse:
    """Non-streaming chat completion. Use for triage + simple calls."""
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    try:
        r = requests.post(
            f"{BASE_URL}/chat/completions",
            headers=_build_headers(api_key),
            json=payload,
            timeout=timeout,
        )
    except requests.exceptions.Timeout as e:
        raise LLMServerError(f"timeout: {e}") from e
    except requests.exceptions.ConnectionError as e:
        raise LLMServerError(f"connection: {e}") from e

    if r.status_code == 401:
        raise LLMAuthError(r.text)
    if r.status_code == 402:
        raise LLMNoCreditError(r.text)
    if r.status_code in (404, 422):
        raise LLMModelUnavailableError(r.text)
    if r.status_code == 429:
        retry_after = r.headers.get("Retry-After")
        raise LLMRateLimitError(retry_after or "1")
    if r.status_code >= 500:
        raise LLMServerError(f"{r.status_code}: {r.text[:200]}")
    if r.status_code != 200:
        raise LLMError(f"{r.status_code}: {r.text[:200]}")

    body = r.json()
    choice = body["choices"][0]
    msg = choice["message"]
    usage = body.get("usage", {})
    return ChatResponse(
        text=msg.get("content") or "",
        model=body.get("model", model),
        tokens_in=usage.get("prompt_tokens", 0),
        tokens_out=usage.get("completion_tokens", 0),
        finish_reason=choice.get("finish_reason", "stop"),
        tool_calls=msg.get("tool_calls"),
        raw=body,
    )
