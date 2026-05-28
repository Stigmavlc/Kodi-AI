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
) -> Generator[tuple[str | None, str | None, dict | None, list | None], None, None]:
    """Stream chat completion. Yields (chunk_text, finish_reason, usage, tool_calls).

    finish_reason and usage are None until the terminal chunk. tool_calls is
    None on every chunk EXCEPT the terminal one: real OpenAI-compatible streaming
    (OpenRouter) FRAGMENTS each tool call across many chunks — the first delta for
    a call carries index/id/function.name + a PARTIAL function.arguments, and
    later deltas carry the SAME index with more arguments fragments (usually no
    id/name). This generator merges those fragments BY INDEX and surfaces the
    fully-assembled, ordered list of COMPLETE tool calls exactly once, on the
    terminal chunk (finish_reason set / [DONE]). Each surfaced call has the
    OpenAI shape {id, type:"function", function:{name, arguments}} with arguments
    concatenated into one valid JSON string — so the reasoner never sees a
    truncated arg blob or an empty tool_name. (HIGH-2.)

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

    # Tool-call defragmentation buffer (HIGH-2). Keyed by the delta's `index` so
    # fragments of the same call merge; insertion order is preserved so we can
    # emit ordered-by-index at the end. Each value is the OpenAI tool-call shape.
    tc_buffer: dict[int, dict] = {}
    tool_calls_emitted = False

    def _accumulate_tool_call_deltas(deltas: list) -> None:
        for d in deltas or []:
            if not isinstance(d, dict):
                continue
            idx = d.get("index")
            if idx is None:
                # Some providers omit index when there is a single tool call;
                # fold everything into slot 0 in that case.
                idx = 0
            slot = tc_buffer.get(idx)
            if slot is None:
                slot = {"id": None, "type": "function",
                        "function": {"name": None, "arguments": ""}}
                tc_buffer[idx] = slot
            if d.get("id"):
                slot["id"] = d["id"]
            if d.get("type"):
                slot["type"] = d["type"]
            fn = d.get("function") or {}
            if fn.get("name"):
                slot["function"]["name"] = fn["name"]
            frag = fn.get("arguments")
            if frag:
                slot["function"]["arguments"] += frag

    def _assembled_tool_calls() -> list | None:
        if not tc_buffer:
            return None
        out_calls: list[dict] = []
        for idx in sorted(tc_buffer):
            slot = tc_buffer[idx]
            out_calls.append({
                "id": slot.get("id") or "",
                "type": slot.get("type") or "function",
                "function": {
                    "name": slot["function"].get("name") or "",
                    "arguments": slot["function"].get("arguments") or "",
                },
            })
        return out_calls

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
                # Stream end without an explicit finish_reason chunk carrying the
                # tool_calls — flush any buffered (assembled) calls now so the
                # caller still receives complete tool calls (once).
                if not tool_calls_emitted:
                    assembled = _assembled_tool_calls()
                    if assembled:
                        tool_calls_emitted = True
                        yield (None, "tool_calls", None, assembled)
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
            # Accumulate tool-call fragments; do NOT surface them yet. They are
            # emitted COMPLETE on the terminal chunk below.
            _accumulate_tool_call_deltas(delta.get("tool_calls"))
            # The terminal chunk (finish_reason present) is where we surface the
            # fully-assembled tool calls — exactly once. For text-only streams
            # `assembled` is None, preserving the prior contract.
            assembled = None
            if finish and not tool_calls_emitted:
                assembled = _assembled_tool_calls()
                if assembled:
                    tool_calls_emitted = True
            if chunk or finish or usage or assembled:
                yield (chunk if chunk else None, finish, usage, assembled)
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
