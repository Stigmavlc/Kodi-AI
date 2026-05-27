"""Per-chat setup DM state machine for v0.3.0 inline-setup flow.

States (string constants):
  AWAITING_OR_KEY  — user just paired; bot asked for OpenRouter key, waiting
                     for the message containing 'sk-or-...'.
  AWAITING_MODE    — OpenRouter key validated; bot sent inline keyboard for
                     auto|manual; waiting for the callback_data click.
  DONE             — full setup complete; bot routes regular messages
                     through the normal reasoner flow.

Persisted to addon_data/setup_dm_state.json with envelope:
  {"schema_version": 1, "states": {"<chat_id>": "<state>"}}

Schema version is checked on load — incompatible versions wipe + return
empty state (acceptable for V1: the DM-flow is reissued by the bot on
next /start anyway).

Concurrency:
  Module-level RLock guards both in-memory cache and the JSON file. T3
  is the only writer in practice (its update handler calls set/clear).

Spec: v0.3.0 settings-inline setup pivot, §E.
"""
from __future__ import annotations
import json
import os
import threading
from typing import Optional

from .. import state_paths

SCHEMA_VERSION = 1

AWAITING_OR_KEY = "AWAITING_OR_KEY"
AWAITING_MODE = "AWAITING_MODE"
DONE = "DONE"

_VALID_STATES = {AWAITING_OR_KEY, AWAITING_MODE, DONE}

_LOCK = threading.RLock()
_cache: Optional[dict[str, str]] = None


def _path() -> str:
    return state_paths.profile_path("setup_dm_state.json")


def _load() -> dict[str, str]:
    """Return the chat_id -> state map (string keys, string values).

    chat_id is serialized as string in JSON (JSON object keys can only be
    strings). Public API converts to int on read.
    """
    global _cache
    if _cache is not None:
        return _cache
    p = _path()
    if not os.path.exists(p):
        _cache = {}
        return _cache
    try:
        with open(p, "r", encoding="utf-8") as f:
            blob = json.load(f)
    except (json.JSONDecodeError, OSError):
        _cache = {}
        return _cache
    if not isinstance(blob, dict):
        _cache = {}
        return _cache
    if blob.get("schema_version") != SCHEMA_VERSION:
        # Future incompatible version → wipe (DM flow is re-issuable, no
        # harm beyond the user having to re-pick mode if they were mid-flow
        # during an upgrade).
        _cache = {}
        return _cache
    states = blob.get("states") or {}
    if not isinstance(states, dict):
        _cache = {}
        return _cache
    # Filter any malformed entries.
    _cache = {
        k: v for k, v in states.items()
        if isinstance(k, str) and isinstance(v, str) and v in _VALID_STATES
    }
    return _cache


def _persist(states: dict[str, str]) -> None:
    """Atomic-write the state map under the envelope."""
    envelope = {"schema_version": SCHEMA_VERSION, "states": states}
    blob = json.dumps(envelope, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    state_paths.atomic_write(_path(), blob)


def get_state(chat_id: int) -> Optional[str]:
    """Return the current setup state for chat_id, or None if no state."""
    with _LOCK:
        return _load().get(str(chat_id))


def set_state(chat_id: int, state: str) -> None:
    """Persist the state for chat_id. Raises ValueError on unknown state."""
    if state not in _VALID_STATES:
        raise ValueError(f"setup_dm_state.set_state: unknown state {state!r}")
    with _LOCK:
        states = dict(_load())
        states[str(chat_id)] = state
        _persist(states)
        global _cache
        _cache = states


def clear_state(chat_id: int) -> None:
    """Remove any state for chat_id. Idempotent."""
    with _LOCK:
        states = dict(_load())
        if str(chat_id) in states:
            del states[str(chat_id)]
            _persist(states)
            global _cache
            _cache = states


def invalidate_cache() -> None:
    """Force re-read on next access (test helper + post-process-restart)."""
    with _LOCK:
        global _cache
        _cache = None
