"""Unit tests for lib.telegram.bot — send_message payload + _handle_update dispatch."""
from __future__ import annotations
import json
import sys
import pytest
from unittest import mock


@pytest.fixture(autouse=True)
def setup_paths(tmp_path, monkeypatch):
    """Required so auth.is_authorized / chat_allowlist do not blow up on
    state_paths access during _handle_update test paths."""
    fake = mock.MagicMock()
    fake.translatePath.side_effect = lambda p: str(tmp_path / p.replace("special://", ""))
    fake.mkdirs.side_effect = lambda p: __import__("os").makedirs(fake.translatePath(p), exist_ok=True) or True
    monkeypatch.setitem(sys.modules, "xbmcvfs", fake)
    if "lib.state_paths" in sys.modules:
        monkeypatch.setattr(sys.modules["lib.state_paths"], "xbmcvfs", fake)
    from lib import state_paths, secrets
    state_paths.ensure_dirs()
    secrets.invalidate_cache()
    yield


def test_send_message_payload_structure():
    """Verify send_message constructs the right payload."""
    from lib.telegram import auth, bot
    # Stub requests
    import lib.telegram.bot as bot_mod
    orig_post = bot_mod.requests.post
    captured = {}
    def fake_post(url, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        return mock.MagicMock(json=lambda: {"ok": True, "result": {}})
    bot_mod.requests.post = fake_post
    try:
        b = bot.TelegramBot(bot_token="123:abc")
        b.send_message(chat_id=42, text="hello")
        assert "sendMessage" in captured["url"]
        assert captured["json"]["chat_id"] == 42
        assert captured["json"]["text"] == "hello"
        assert captured["json"]["parse_mode"] == "HTML"
    finally:
        bot_mod.requests.post = orig_post


def test_handle_update_authorized_message_enqueues(monkeypatch, tmp_path):
    """Authorized chat → UserMsg enqueued."""
    from lib import concurrency
    import lib.telegram.bot as bot_mod
    import lib.telegram.auth as auth
    monkeypatch.setattr(auth, "is_authorized", lambda cid: True)
    monkeypatch.setattr(auth, "try_authorize_first_start", lambda cid, s: False)
    # Drain queue
    while not concurrency.work_queue.empty():
        concurrency.work_queue.get_nowait()
    b = bot_mod.TelegramBot(bot_token="123:abc")
    b._handle_update({"message": {"chat": {"id": 42}, "text": "hello", "message_id": 1}})
    # UserMsg should be enqueued
    found = False
    while not concurrency.work_queue.empty():
        _, _, item = concurrency.work_queue.get_nowait()
        if hasattr(item, "chat_id") and item.chat_id == 42:
            found = True
    assert found


def test_handle_update_callback_query_authorized_enqueues_resume(monkeypatch):
    """callback_query with data 'resume:<sid>:<reply>' from authorized chat → ResumeWork."""
    from lib import concurrency
    import lib.telegram.bot as bot_mod
    import lib.telegram.auth as auth
    monkeypatch.setattr(auth, "is_authorized", lambda cid: True)
    # Stub answer_callback_query so it doesn't actually call requests.post
    monkeypatch.setattr(bot_mod.TelegramBot, "answer_callback_query",
                        lambda self, callback_id, text="": None)
    while not concurrency.work_queue.empty():
        concurrency.work_queue.get_nowait()
    b = bot_mod.TelegramBot(bot_token="123:abc")
    b._handle_update({
        "callback_query": {
            "id": "cb1",
            "data": "resume:sess-abc:yes",
            "message": {"chat": {"id": 42}, "message_id": 10},
        }
    })
    found = False
    while not concurrency.work_queue.empty():
        _, _, item = concurrency.work_queue.get_nowait()
        if hasattr(item, "session_id") and item.session_id == "sess-abc":
            assert item.user_reply == "yes"
            found = True
    assert found


def test_start_no_setup_in_progress_gives_gentle_message(monkeypatch):
    """BLOCKER 1 belt-and-suspenders: /start <secret> when NO setup_secret is
    stored (no pairing in progress) gets a gentle 'start setup on your TV'
    message, not a flat 'Invalid secret'."""
    import lib.telegram.bot as bot_mod
    import lib.telegram.auth as auth
    monkeypatch.setattr(auth, "try_authorize_first_start", lambda cid, s: False)
    monkeypatch.setattr(auth, "current_setup_secret", lambda: None)
    sent = []
    monkeypatch.setattr(bot_mod.TelegramBot, "send_message",
                        lambda self, chat_id, text, **kw: sent.append(text))
    b = bot_mod.TelegramBot(bot_token="123:abc")
    b._handle_update({"message": {"chat": {"id": 9}, "text": "/start oldsecret", "message_id": 1}})
    assert sent, "expected a reply"
    assert "no pairing in progress" in sent[0].lower()
    assert "set up via phone" in sent[0].lower() or "tv" in sent[0].lower()


def test_start_wrong_secret_gives_invalid_message(monkeypatch):
    """When a setup_secret IS stored but the provided one is wrong, keep the
    stricter 'Invalid secret - check the code.' message."""
    import lib.telegram.bot as bot_mod
    import lib.telegram.auth as auth
    monkeypatch.setattr(auth, "try_authorize_first_start", lambda cid, s: False)
    monkeypatch.setattr(auth, "current_setup_secret", lambda: "the-real-secret")
    sent = []
    monkeypatch.setattr(bot_mod.TelegramBot, "send_message",
                        lambda self, chat_id, text, **kw: sent.append(text))
    b = bot_mod.TelegramBot(bot_token="123:abc")
    b._handle_update({"message": {"chat": {"id": 9}, "text": "/start wrongsecret", "message_id": 1}})
    assert sent, "expected a reply"
    assert "invalid secret" in sent[0].lower()


def test_handle_update_unauthorized_message_does_not_enqueue(monkeypatch):
    """Unauthorized message → bot replies prompting /start, does NOT enqueue UserMsg."""
    from lib import concurrency
    import lib.telegram.bot as bot_mod
    import lib.telegram.auth as auth
    monkeypatch.setattr(auth, "is_authorized", lambda cid: False)
    monkeypatch.setattr(auth, "try_authorize_first_start", lambda cid, s: False)
    sent = []
    monkeypatch.setattr(bot_mod.TelegramBot, "send_message",
                        lambda self, chat_id, text, **kw: sent.append((chat_id, text)))
    while not concurrency.work_queue.empty():
        concurrency.work_queue.get_nowait()
    b = bot_mod.TelegramBot(bot_token="123:abc")
    b._handle_update({"message": {"chat": {"id": 7}, "text": "hello", "message_id": 1}})
    assert concurrency.work_queue.empty()
    assert sent and sent[0][0] == 7
