"""Cheap-LLM triage: classify a log cluster as CRITICAL/ADVISORY/IGNORE.

Rate-limited via TokenBucket (default 6/min, burst 3). T4 enforces budget
at call time (T2 never blocks).

Spec: §1.6.
"""
from __future__ import annotations
import time
import threading
from typing import Literal

Verdict = Literal["CRITICAL", "ADVISORY", "IGNORE"]


class TokenBucket:
    def __init__(self, *, rate_per_min: int, burst: int):
        self.rate_per_sec = rate_per_min / 60.0
        self.burst = burst
        self._tokens = float(burst)
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def try_consume(self, n: float = 1.0) -> bool:
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(self.burst, self._tokens + elapsed * self.rate_per_sec)
            self._last_refill = now
            if self._tokens >= n:
                self._tokens -= n
                return True
            return False

    def next_token_wait_s(self) -> float:
        with self._lock:
            if self._tokens >= 1:
                return 0.0
            need = 1.0 - self._tokens
            return need / self.rate_per_sec


def _parse_verdict(text: str) -> Verdict:
    up = text.upper().strip()
    for tok in ("CRITICAL", "ADVISORY", "IGNORE"):
        if tok in up.split():
            return tok  # type: ignore[return-value]
    return "IGNORE"


def classify(llm_module, *, api_key: str, model: str, cluster_text: str) -> Verdict:
    """Single triage call. Returns verdict (IGNORE on any failure)."""
    from .llm.prompts import load
    from .llm.client import LLMError
    system = load("triage_system").body
    try:
        res = llm_module.chat(
            api_key=api_key,
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": f"Cluster:\n{cluster_text[:4000]}"},
            ],
            max_tokens=10,
            temperature=0.0,
        )
    except LLMError:
        return "IGNORE"  # safe default
    except Exception:
        return "IGNORE"
    return _parse_verdict(res.text)
