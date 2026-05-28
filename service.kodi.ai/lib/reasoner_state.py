"""SessionState dataclass + atomic persistence under sessions/<sid>.json.

Pause sequence step 1-3 per spec §1.7:
  1. paused_sessions[sid] = state (memory)
  2. MonotonicBudget.pause() (memory)
  3. atomic disk write — captures post-pause budget state

This module owns step 3. Pure I/O — no Kodi imports beyond state_paths.

Terminal states (spec §5.7): paused | fix_complete_notify_pending |
  pause_notify_failed | notify_failed | fix_complete | expired.
Boot recovery dispatches based on terminal_state (see lib/recovery.py).

Spec: §1.7, §5.7.
"""
from __future__ import annotations
import json
import os
from dataclasses import dataclass, asdict, field
from typing import Any
from . import state_paths


@dataclass(frozen=False)  # mutable for in-memory updates
class SessionState:
    session_id: str
    messages: list[dict]  # conversation history (redacted before LLM send)
    tool_history: list[dict]  # tools called this session with results
    pending_tool: dict | None  # tool awaiting user confirmation
    snapshot_ids: list[str]  # snapshots created this session (for /undo)
    terminal_state: str  # paused | fix_complete_notify_pending | ...
    paused_at: float  # epoch seconds when paused
    budget_blob: dict  # MonotonicBudget.to_dict()
    cluster_id: str | None  # originating LogIncident cluster (None for chat-init)
    # v0.6.0 Part 2 (criterion F): for a CHAT-initiated session that paused on a
    # confirm-gate, this is the Telegram chat_id to reply back to on resume. None
    # for incident-initiated sessions (those resolve via the allowlist broadcast).
    # Defaulted so older serialized states (no key) still load via from_dict.
    origin_chat_id: int | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, blob: dict) -> "SessionState":
        return cls(**blob)


def _path(session_id: str) -> str:
    return state_paths.profile_path(f"sessions/{session_id}.json")


def persist(state: SessionState) -> None:
    blob = json.dumps(state.to_dict(), separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    state_paths.atomic_write(_path(state.session_id), blob)


def load(session_id: str) -> SessionState | None:
    p = _path(session_id)
    if not os.path.exists(p):
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            return SessionState.from_dict(json.load(f))
    except (json.JSONDecodeError, OSError, TypeError):
        # Corrupt → move aside, return None (recovery handled by lib/recovery.py)
        corrupt_dir = state_paths.profile_path("sessions/.corrupt")
        try:
            os.makedirs(corrupt_dir, exist_ok=True)
            os.rename(p, os.path.join(corrupt_dir, f"{session_id}.json.bak"))
        except OSError:
            pass
        return None


def unlink(session_id: str) -> None:
    try:
        os.remove(_path(session_id))
    except FileNotFoundError:
        pass


def list_all() -> list[str]:
    base = state_paths.profile_path("sessions")
    if not os.path.exists(base):
        return []
    return [f[:-5] for f in os.listdir(base) if f.endswith(".json")]
