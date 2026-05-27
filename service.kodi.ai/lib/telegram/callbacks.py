"""Callback resolution: reply_to_message_id → session_id; fallback to
most-recent paused session for chat_id within 1h TTL.

Spec §5.7.
"""
from __future__ import annotations
import time
from .. import reasoner_state
from ..concurrency import paused_sessions, paused_sessions_lock


_msg_id_to_session: dict[int, str] = {}  # populated by bot when sending pause msgs


def register_pause_message(chat_id: int, message_id: int, session_id: str):
    """Called when a pause prompt is sent. Maps msg_id → session_id."""
    _msg_id_to_session[message_id] = session_id


def resolve_session_for_callback(callback_query: dict) -> str | None:
    """Try reply_to_message_id first, fall back to most recent paused."""
    msg = callback_query.get("message", {})
    reply_to_id = (msg.get("reply_to_message") or {}).get("message_id")
    if reply_to_id and reply_to_id in _msg_id_to_session:
        return _msg_id_to_session[reply_to_id]
    chat_id = msg.get("chat", {}).get("id")
    return _most_recent_paused_for(chat_id)


def resolve_session_for_reply(message: dict) -> str | None:
    reply_to_id = (message.get("reply_to_message") or {}).get("message_id")
    if reply_to_id and reply_to_id in _msg_id_to_session:
        return _msg_id_to_session[reply_to_id]
    chat_id = message.get("chat", {}).get("id")
    return _most_recent_paused_for(chat_id)


def _most_recent_paused_for(chat_id) -> str | None:
    """Within last 1h."""
    now = time.time()
    best_sid = None
    best_ts = 0
    with paused_sessions_lock:
        for sid, state in paused_sessions.items():
            if (now - state.paused_at) > 3600:
                continue
            if state.paused_at > best_ts:
                best_ts = state.paused_at
                best_sid = sid
    return best_sid
