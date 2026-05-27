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


# ---- Streaming with chunk-level abort + slug validation ----
from typing import Generator, Iterable
import threading


def chat_stream(
    *,
    api_key: str,
    model: str,
    messages: list[dict],
    abort_event: threading.Event,
    tools: list[dict] | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.2,
    timeout: tuple[float, float] = (5.0, 30.0),
) -> Generator[tuple[str | None, str | None, dict | None], None, None]:
    """Stream chat completion. Yields (chunk_text, finish_reason, usage).

    finish_reason and usage are None until the terminal chunk.
    Caller MUST check abort_event between iterations; this generator
    cleanly closes the socket on next iteration after abort_event is set.

    Spec: §1.10.
    """
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": True,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    r = requests.post(
        f"{BASE_URL}/chat/completions",
        headers=_build_headers(api_key),
        json=payload,
        timeout=timeout,
        stream=True,
    )

    if r.status_code == 401: raise LLMAuthError(r.text)
    if r.status_code == 402: raise LLMNoCreditError(r.text)
    if r.status_code in (404, 422): raise LLMModelUnavailableError(r.text)
    if r.status_code == 429: raise LLMRateLimitError(r.headers.get("Retry-After", "1"))
    if r.status_code >= 500: raise LLMServerError(f"{r.status_code}: {r.text[:200]}")
    if r.status_code != 200: raise LLMError(f"{r.status_code}: {r.text[:200]}")

    try:
        for raw_line in r.iter_lines(decode_unicode=True):
            if abort_event.is_set():
                # Spec §1.10: r.raw.close() THEN r.close() for clean socket FIN
                try:
                    r.raw.close()
                except Exception:
                    pass
                r.close()
                return
            if not raw_line or not raw_line.startswith("data:"):
                continue
            data = raw_line[len("data:"):].strip()
            if data == "[DONE]":
                return
            try:
                obj = json.loads(data)
            except json.JSONDecodeError:
                continue
            choice = obj.get("choices", [{}])[0]
            delta = choice.get("delta", {})
            chunk = delta.get("content") or ""
            finish = choice.get("finish_reason")
            usage = obj.get("usage")
            if chunk or finish or usage:
                yield chunk if chunk else None, finish, usage
    finally:
        try: r.raw.close()
        except Exception: pass
        r.close()


def validate_slugs(
    *,
    api_key: str,
    expected: Iterable[str],
    timeout: float = 10.0,
) -> tuple[set[str], set[str]]:
    """Ping OpenRouter /api/v1/models. Returns (available, missing).
    On unreachable, available=set() and missing=set(expected) so caller
    can warn but proceed.
    """
    expected_set = set(expected)
    try:
        r = requests.get(
            f"{BASE_URL}/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )
        r.raise_for_status()
        ids = {m["id"] for m in r.json().get("data", []) if "id" in m}
    except Exception:
        return set(), expected_set
    available = expected_set & ids
    return available, expected_set - available
