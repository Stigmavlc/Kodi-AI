"""Executes the 4-step pause sequence per spec §1.7 (round-7 strict ordering).

Step 1: paused_sessions[sid] = state (memory)
Step 2: MonotonicBudget.pause() (memory; updates elapsed_baseline)
Step 3: Atomic disk write — captures post-pause budget state
Step 4: Telegram send with 15s deadline
   - Success: return True
   - Fail: mark pause_notify_failed terminal state, persist, return False
     (boot watchdog retries on next startup)
"""
from __future__ import annotations
import time
from .concurrency import paused_sessions, paused_sessions_lock, MonotonicBudget
from . import reasoner_state


TELEGRAM_SEND_DEADLINE_S = 15.0


def pause_and_persist(
    *,
    state: reasoner_state.SessionState,
    budget: MonotonicBudget,
    telegram_send_callable,
) -> bool:
    """Execute the 4-step pause sequence. Returns True if Telegram sent OK,
    False if pause_notify_failed terminal state."""
    # Step 1: in-memory primary
    with paused_sessions_lock:
        paused_sessions[state.session_id] = state
    # Step 2: budget pause (memory; updates elapsed_baseline)
    if budget.state.name == "RUNNING":
        budget.pause()
    # Reflect new budget state in serialized blob BEFORE disk write
    state.budget_blob = budget.to_dict()
    state.paused_at = time.time()
    state.terminal_state = "paused"
    # Step 3: atomic disk write
    reasoner_state.persist(state)
    # Step 4: Telegram with deadline
    deadline = time.monotonic() + TELEGRAM_SEND_DEADLINE_S
    try:
        ok = bool(telegram_send_callable())
    except Exception:
        ok = False
    if ok and time.monotonic() <= deadline:
        return True
    # Fail path
    state.terminal_state = "pause_notify_failed"
    reasoner_state.persist(state)
    return False
