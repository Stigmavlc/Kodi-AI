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


# ---- FairnessTracker — prevent ResumeWork starvation of LogIncident ----
class FairnessTracker:
    """Counts ResumeWork drains; after N consecutive (without a LogIncident
    drained in between), should_force_log_incident() returns True until the
    next LogIncident is actually drained.

    Spec: §1.12.
    """
    def __init__(self, resume_threshold: int = 10):
        self._resume_count = 0
        self._threshold = resume_threshold
        self._lock = threading.Lock()

    def note_drained(self, payload) -> None:
        with self._lock:
            name = type(payload).__name__
            if name == "ResumeWork":
                self._resume_count += 1
            elif name == "LogIncident":
                self._resume_count = 0
            # UserMsg: no effect on fairness counter

    def should_force_log_incident(self) -> bool:
        with self._lock:
            return self._resume_count >= self._threshold


# Module-level instance used by T4 dispatch (lib.service)
fairness_tracker = FairnessTracker()


def has_pending_logincident() -> bool:
    """Peek work_queue for any LogIncident at any position.

    CPython PriorityQueue exposes ._queue (heap list). Acceptable use here
    (Kodi pins to CPython 3.x; spec §1.2 documents this version pin).
    Returns True if any LogIncident is queued, regardless of priority.
    """
    try:
        with work_queue.mutex:
            for prio, _, payload in list(work_queue.queue):
                if type(payload).__name__ == "LogIncident":
                    return True
    except Exception:
        return False
    return False


# ---- MonotonicBudget — wall-clock cap with pause/resume across ask_user ----
from enum import Enum, auto
import time


class BudgetStateError(RuntimeError):
    """Illegal MonotonicBudget state transition."""


class BudgetState(Enum):
    IDLE = auto()
    RUNNING = auto()
    PAUSED = auto()


class MonotonicBudget:
    """Wall-clock budget that pauses across ask_user.

    Only PAUSED state is ever persisted (only RUNNING crashes lose the session).
    On rehydrate, restored as PAUSED with elapsed_baseline preserved;
    .resume() reads time.monotonic() fresh.

    Spec: §1.8.
    """
    def __init__(self, limit_s: float):
        self.limit_s = limit_s
        self.elapsed_baseline = 0.0
        self.state = BudgetState.IDLE
        self.started_at: float | None = None

    def start(self) -> None:
        if self.state != BudgetState.IDLE:
            raise BudgetStateError(f"start: state is {self.state.name}, expected IDLE")
        self.state = BudgetState.RUNNING
        self.started_at = time.monotonic()

    def pause(self) -> None:
        if self.state != BudgetState.RUNNING:
            raise BudgetStateError(f"pause: state is {self.state.name}, expected RUNNING")
        assert self.started_at is not None
        self.elapsed_baseline += time.monotonic() - self.started_at
        self.started_at = None
        self.state = BudgetState.PAUSED

    def resume(self) -> None:
        if self.state != BudgetState.PAUSED:
            raise BudgetStateError(f"resume: state is {self.state.name}, expected PAUSED")
        self.started_at = time.monotonic()
        self.state = BudgetState.RUNNING

    def stop(self) -> None:
        if self.state != BudgetState.RUNNING:
            raise BudgetStateError(f"stop: state is {self.state.name}, expected RUNNING")
        assert self.started_at is not None
        self.elapsed_baseline += time.monotonic() - self.started_at
        self.started_at = None
        self.state = BudgetState.IDLE

    def elapsed(self) -> float:
        if self.state == BudgetState.RUNNING:
            assert self.started_at is not None
            return self.elapsed_baseline + (time.monotonic() - self.started_at)
        return self.elapsed_baseline

    def exceeded(self) -> bool:
        return self.elapsed() >= self.limit_s

    def to_dict(self) -> dict:
        """Serialize for disk persistence (only PAUSED state persisted in practice)."""
        return {
            "limit_s": self.limit_s,
            "elapsed_baseline": self.elapsed_baseline,
            "state": self.state.name,
        }

    @classmethod
    def from_dict(cls, blob: dict) -> "MonotonicBudget":
        """Rehydrate from disk. state typically PAUSED."""
        b = cls(limit_s=blob["limit_s"])
        b.elapsed_baseline = blob["elapsed_baseline"]
        b.state = BudgetState[blob["state"]]
        # started_at intentionally None on rehydrate — resume() will set it.
        return b
