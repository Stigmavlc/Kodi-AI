"""Unit tests for lib.telegram.callbacks — pause-msg registry + resolution."""
from __future__ import annotations
import time
import pytest

from dataclasses import dataclass


@dataclass
class StubSessionState:
    """Minimal stand-in for reasoner_state.SessionState — only paused_at is read
    by the most-recent fallback in callbacks._most_recent_paused_for."""
    session_id: str
    paused_at: float


@pytest.fixture(autouse=True)
def clear_state():
    """Reset module-level state between tests."""
    from lib.telegram import callbacks
    from lib.concurrency import paused_sessions, paused_sessions_lock
    callbacks._msg_id_to_session.clear()
    with paused_sessions_lock:
        paused_sessions.clear()
    yield
    callbacks._msg_id_to_session.clear()
    with paused_sessions_lock:
        paused_sessions.clear()


def test_register_pause_message_populates_index():
    from lib.telegram import callbacks
    callbacks.register_pause_message(chat_id=42, message_id=100, session_id="sess-abc")
    assert callbacks._msg_id_to_session[100] == "sess-abc"


def test_resolve_for_callback_via_reply_to_message_id():
    """callback_query.message.reply_to_message.message_id known → returns its sid."""
    from lib.telegram import callbacks
    callbacks.register_pause_message(chat_id=42, message_id=100, session_id="sess-via-reply")
    cq = {
        "id": "cb1",
        "message": {
            "chat": {"id": 42},
            "message_id": 200,
            "reply_to_message": {"message_id": 100},
        },
    }
    assert callbacks.resolve_session_for_callback(cq) == "sess-via-reply"


def test_resolve_for_callback_falls_back_to_most_recent_paused_within_1h():
    """No reply_to → most recently paused session (within 1h TTL) wins."""
    from lib.telegram import callbacks
    from lib.concurrency import paused_sessions, paused_sessions_lock
    now = time.time()
    with paused_sessions_lock:
        paused_sessions["old"] = StubSessionState("old", paused_at=now - 1800)  # 30 min ago
        paused_sessions["recent"] = StubSessionState("recent", paused_at=now - 60)  # 1 min ago
        paused_sessions["expired"] = StubSessionState("expired", paused_at=now - 7200)  # 2 h ago
    cq = {"id": "cb2", "message": {"chat": {"id": 42}, "message_id": 200}}
    # No reply_to_message → fallback to most-recent-within-1h → "recent"
    assert callbacks.resolve_session_for_callback(cq) == "recent"


def test_resolve_for_reply_uses_reply_to_when_known_else_fallback():
    """resolve_session_for_reply mirrors resolve_session_for_callback for plain messages."""
    from lib.telegram import callbacks
    from lib.concurrency import paused_sessions, paused_sessions_lock
    callbacks.register_pause_message(chat_id=42, message_id=500, session_id="sid-by-reply")
    msg = {"chat": {"id": 42}, "message_id": 600, "reply_to_message": {"message_id": 500}}
    assert callbacks.resolve_session_for_reply(msg) == "sid-by-reply"
    # No reply_to + empty paused_sessions → None
    msg2 = {"chat": {"id": 42}, "message_id": 700}
    assert callbacks.resolve_session_for_reply(msg2) is None
