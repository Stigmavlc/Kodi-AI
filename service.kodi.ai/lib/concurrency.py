"""Cross-thread state for the 4-thread service architecture.

This module is the single home for everything threads share:
  - abort_event: shutdown signal (set by Main on Monitor.abortRequested()).
  - startup_complete_event: T4 sets after boot pass; T2/T3 wait on it.
  - work_queue: PriorityQueue draining to T4. Use enqueue() helper ONLY.
  - active_cluster_ids + coalesce_lock: T2-side dedup at enqueue time.
  - drop_counter: T2 increments on backpressure.
  - paused_sessions + paused_sessions_lock: in-memory primary for sessions.

ActiveCalls + MonotonicBudget added in Tasks 1.4 and 1.5.

Spec: §1.2.
"""
from __future__ import annotations
import threading
import queue
import itertools
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal


# ---- Events / shutdown ----
abort_event = threading.Event()
startup_complete_event = threading.Event()


# ---- AtomicCounter ----
class AtomicCounter:
    """Thread-safe int counter."""
    def __init__(self):
        self._v = 0
        self._lock = threading.Lock()
    def inc(self) -> None:
        with self._lock:
            self._v += 1
    def get(self) -> int:
        with self._lock:
            return self._v
    def reset_and_get(self) -> int:
        with self._lock:
            v, self._v = self._v, 0
            return v


drop_counter = AtomicCounter()


# ---- Work queue + payload types ----
@dataclass(frozen=True, order=False)
class LogIncident:
    cluster_id: str
    first_seen: datetime | None
    last_seen: datetime | None
    occurrences: int
    raw_lines: list[str]
    severity_hint: str
    likely_addon: str | None
    likely_action: str | None
    backdated: bool
    from_previous_session: bool
    triage_deferred: bool


@dataclass(frozen=True, order=False)
class UserMsg:
    chat_id: int
    text: str
    message_id: int
    reply_to_message_id: int | None


@dataclass(frozen=True, order=False)
class ResumeWork:
    session_id: str
    user_reply: Any  # str | bool — see spec §1.7


WorkItem = LogIncident | UserMsg | ResumeWork


# PriorityQueue items are (priority_int, monotonic_seq, payload).
# monotonic_seq breaks ties and avoids comparing payloads (@dataclass(order=False)
# would otherwise raise TypeError on tuple comparison).
_seq = itertools.count()
work_queue: "queue.PriorityQueue[tuple[int, int, Any]]" = queue.PriorityQueue(maxsize=500)

_PRIORITIES = {
    "ResumeWork": 0,
    "UserMsg": 5,
    "LogIncident": 10,
}


def enqueue(payload: WorkItem) -> None:
    """Only API for putting items on work_queue. Asserts known type."""
    name = type(payload).__name__
    if name not in _PRIORITIES:
        raise KeyError(f"enqueue: unknown payload type {name}")
    work_queue.put((_PRIORITIES[name], next(_seq), payload))


# ---- Coalescing (T2-side dedup at enqueue time) ----
coalesce_lock = threading.Lock()
active_cluster_ids: set[str] = set()


# ---- Paused session registry (T4-owned; T3 reads under lock via callbacks) ----
paused_sessions: dict[str, Any] = {}  # session_id -> SessionState (defined later)
paused_sessions_lock = threading.Lock()
