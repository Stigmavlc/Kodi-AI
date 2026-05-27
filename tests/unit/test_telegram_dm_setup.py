"""End-to-end DM setup flow tests for v0.3.0 inline-setup pivot.

Covers the Telegram bot DM state machine driven through TelegramBot._handle_update:

  1. /start <secret> → if no openrouter_key, send key prompt + AWAITING_OR_KEY.
  2. AWAITING_OR_KEY + valid key text → validate (mock llm_client) → save key
     + delete user's message + send mode keyboard + AWAITING_MODE.
  3. callback_query setup_mode:auto → settings.mode='auto' + edit message + DONE.
  4. callback_query setup_mode:manual → settings.mode='manual' + DONE.
  5. AWAITING_MODE + plain message → bot tells user to tap a button.
  6. AWAITING_OR_KEY + invalid key (auth error) → stays AWAITING_OR_KEY.
  7. AWAITING_OR_KEY + format-reject (too short) → friendly hint, stays.

All Telegram API calls are mocked. llm_client.chat is mocked.
"""
from __future__ import annotations
import os
import sys
from unittest import mock

import pytest


class FakeRespOk:
    """Minimal fake requests response for sendMessage/editMessage/deleteMessage."""
    def __init__(self, **kw):
        self._body = {"ok": True, "result": kw}
    def json(self):
        return self._body


@pytest.fixture
def setup_paths(tmp_path, monkeypatch):
    """Fake xbmcvfs + invalidate caches so tests share no state."""
    fake = mock.MagicMock()
    fake.translatePath.side_effect = lambda p: str(tmp_path / p.replace("special://", ""))
    fake.mkdirs.side_effect = lambda p: os.makedirs(fake.translatePath(p), exist_ok=True) or True
    monkeypatch.setitem(sys.modules, "xbmcvfs", fake)
    if "lib.state_paths" in sys.modules:
        monkeypatch.setattr(sys.modules["lib.state_paths"], "xbmcvfs", fake)
    from lib import state_paths, secrets
    from lib.telegram import setup_dm_state
    state_paths.ensure_dirs()
    secrets.invalidate_cache()
    setup_dm_state.invalidate_cache()
    yield tmp_path
    secrets.invalidate_cache()
    setup_dm_state.invalidate_cache()


@pytest.fixture
def fake_xbmcaddon(monkeypatch):
    """xbmcaddon stub so settings.set_string works (mode persistence)."""
    fake_settings: dict[str, str] = {}
    fake_addon_inst = mock.MagicMock()
    fake_addon_inst.getSetting.side_effect = lambda k: fake_settings.get(k, "")
    fake_addon_inst.setSetting.side_effect = (
        lambda k, v: fake_settings.__setitem__(k, v)
    )
    fake_xbmcaddon_module = mock.MagicMock()
    fake_xbmcaddon_module.Addon.return_value = fake_addon_inst
    monkeypatch.setitem(sys.modules, "xbmcaddon", fake_xbmcaddon_module)
    if "lib.settings" in sys.modules:
        monkeypatch.setattr(
            sys.modules["lib.settings"], "xbmcaddon", fake_xbmcaddon_module,
        )
        monkeypatch.setattr(sys.modules["lib.settings"], "_cache", {})
    return fake_settings


@pytest.fixture
def captured_sends(monkeypatch):
    """Intercept requests.post calls from bot.py — captures sendMessage,
    editMessageText, deleteMessage, answerCallbackQuery payloads.
    """
    calls: list[tuple[str, dict]] = []
    def fake_post(url, json=None, timeout=None):
        calls.append((url, json or {}))
        return FakeRespOk()
    import lib.telegram.bot as bot_mod
    monkeypatch.setattr(bot_mod.requests, "post", fake_post)
    return calls


def _seed_setup_secret_and_paired(chat_id: int, secret: str = "S3CR3T"):
    """Helper: install a setup_secret so /start <secret> authorizes."""
    from lib.telegram import auth
    from lib import secrets
    secrets.set_secret("setup_secret", secret)
    return secret


# -------------------- Tests --------------------


def test_start_no_or_key_prompts_for_key_and_sets_awaiting(
    setup_paths, fake_xbmcaddon, captured_sends,
):
    """Fresh /start <secret> when no openrouter_key set → bot DMs asking
    for key + state becomes AWAITING_OR_KEY."""
    secret = _seed_setup_secret_and_paired(chat_id=42)
    from lib.telegram import bot as bot_mod, setup_dm_state, auth
    b = bot_mod.TelegramBot(bot_token="123:abc")
    upd = {
        "message": {
            "chat": {"id": 42}, "text": f"/start {secret}", "message_id": 1,
        }
    }
    b._handle_update(upd)
    assert auth.is_authorized(42)
    assert setup_dm_state.get_state(42) == setup_dm_state.AWAITING_OR_KEY
    # Most recent sendMessage should be the OR-key prompt.
    send_msgs = [c for c in captured_sends if c[0].endswith("/sendMessage")]
    assert send_msgs
    last_text = send_msgs[-1][1]["text"]
    assert "OpenRouter" in last_text
    assert "sk-or-" in last_text


def test_start_with_or_key_already_set_greets_and_marks_done(
    setup_paths, fake_xbmcaddon, captured_sends,
):
    """If openrouter_key is already set (e.g. /reset_owner flow), pairing
    just greets and marks the chat DONE."""
    from lib import secrets
    secrets.set_secret("openrouter_key", "sk-or-already-here")
    secret = _seed_setup_secret_and_paired(chat_id=42)
    from lib.telegram import bot as bot_mod, setup_dm_state
    b = bot_mod.TelegramBot(bot_token="123:abc")
    b._handle_update({
        "message": {"chat": {"id": 42}, "text": f"/start {secret}", "message_id": 1},
    })
    assert setup_dm_state.get_state(42) == setup_dm_state.DONE
    send_msgs = [c for c in captured_sends if c[0].endswith("/sendMessage")]
    assert any("ready" in c[1]["text"].lower() for c in send_msgs)


def test_awaiting_or_key_valid_key_promotes_deletes_and_asks_mode(
    setup_paths, fake_xbmcaddon, captured_sends, monkeypatch,
):
    """AWAITING_OR_KEY + valid-looking key + mock llm_client.chat returns
    successfully → key saved, user message deleted, mode keyboard sent,
    state → AWAITING_MODE."""
    from lib.telegram import bot as bot_mod, setup_dm_state, auth
    from lib import secrets
    from lib.llm import client as llm_client
    # Pair manually (skip /start).
    auth._save_allowlist([42])
    setup_dm_state.set_state(42, setup_dm_state.AWAITING_OR_KEY)
    # llm_client.chat returns OK.
    monkeypatch.setattr(
        llm_client, "chat",
        lambda **kw: mock.MagicMock(text="pong", tokens_in=0, tokens_out=1),
    )
    b = bot_mod.TelegramBot(bot_token="123:abc")
    b._handle_update({
        "message": {
            "chat": {"id": 42},
            "text": "sk-or-thisisavalidkey1234567890",
            "message_id": 55,
        },
    })
    # Secret saved.
    assert secrets.get_secret("openrouter_key") == "sk-or-thisisavalidkey1234567890"
    # Delete + mode keyboard sent.
    delete_calls = [c for c in captured_sends if c[0].endswith("/deleteMessage")]
    assert delete_calls and delete_calls[0][1]["message_id"] == 55
    keyboard_calls = [
        c for c in captured_sends
        if c[0].endswith("/sendMessage") and "reply_markup" in c[1]
    ]
    assert keyboard_calls
    kb = keyboard_calls[-1][1]["reply_markup"]
    # Two buttons with setup_mode callback_data.
    cbs = [b["callback_data"] for b in kb["inline_keyboard"][0]]
    assert "setup_mode:auto" in cbs
    assert "setup_mode:manual" in cbs
    assert setup_dm_state.get_state(42) == setup_dm_state.AWAITING_MODE


def test_awaiting_or_key_invalid_key_stays_in_state(
    setup_paths, fake_xbmcaddon, captured_sends, monkeypatch,
):
    """LLMAuthError → bot says 'invalid' + state remains AWAITING_OR_KEY."""
    from lib.telegram import bot as bot_mod, setup_dm_state, auth
    from lib import secrets
    from lib.llm import client as llm_client
    auth._save_allowlist([42])
    setup_dm_state.set_state(42, setup_dm_state.AWAITING_OR_KEY)
    def boom(**kw):
        raise llm_client.LLMAuthError("401")
    monkeypatch.setattr(llm_client, "chat", boom)
    b = bot_mod.TelegramBot(bot_token="123:abc")
    b._handle_update({
        "message": {
            "chat": {"id": 42},
            "text": "sk-or-totallyfakeskeyvalue123",
            "message_id": 56,
        },
    })
    # No openrouter_key saved.
    assert secrets.get_secret("openrouter_key") in (None, "")
    # State unchanged.
    assert setup_dm_state.get_state(42) == setup_dm_state.AWAITING_OR_KEY
    # Sent an "Invalid key" message.
    send_msgs = [c for c in captured_sends if c[0].endswith("/sendMessage")]
    assert any("invalid" in c[1]["text"].lower() for c in send_msgs)


def test_awaiting_or_key_too_short_friendly_hint(
    setup_paths, fake_xbmcaddon, captured_sends, monkeypatch,
):
    """Pre-validation: too-short input → friendly hint, no llm_client call."""
    from lib.telegram import bot as bot_mod, setup_dm_state, auth
    from lib.llm import client as llm_client
    auth._save_allowlist([42])
    setup_dm_state.set_state(42, setup_dm_state.AWAITING_OR_KEY)
    called = []
    monkeypatch.setattr(llm_client, "chat", lambda **kw: called.append(1) or None)
    b = bot_mod.TelegramBot(bot_token="123:abc")
    b._handle_update({
        "message": {"chat": {"id": 42}, "text": "tooshort", "message_id": 60},
    })
    assert called == []
    send_msgs = [c for c in captured_sends if c[0].endswith("/sendMessage")]
    assert any("sk-or-" in c[1]["text"] for c in send_msgs)
    # State unchanged.
    assert setup_dm_state.get_state(42) == setup_dm_state.AWAITING_OR_KEY


def test_awaiting_mode_plain_message_advises_tap_button(
    setup_paths, fake_xbmcaddon, captured_sends,
):
    """If state is AWAITING_MODE and the user types text instead of tapping
    the keyboard, the bot replies pointing at the button."""
    from lib.telegram import bot as bot_mod, setup_dm_state, auth
    auth._save_allowlist([42])
    setup_dm_state.set_state(42, setup_dm_state.AWAITING_MODE)
    b = bot_mod.TelegramBot(bot_token="123:abc")
    b._handle_update({
        "message": {"chat": {"id": 42}, "text": "auto pls", "message_id": 1},
    })
    send_msgs = [c for c in captured_sends if c[0].endswith("/sendMessage")]
    assert any("button" in c[1]["text"].lower() or "tap" in c[1]["text"].lower()
               for c in send_msgs)


def test_setup_mode_callback_auto_persists_mode_and_marks_done(
    setup_paths, fake_xbmcaddon, captured_sends,
):
    """callback_query setup_mode:auto → settings.mode='auto', edit message,
    state DONE, setup_secret cleared."""
    from lib.telegram import bot as bot_mod, setup_dm_state, auth
    from lib import secrets
    auth._save_allowlist([42])
    secrets.set_secret("setup_secret", "ABCD")
    setup_dm_state.set_state(42, setup_dm_state.AWAITING_MODE)
    b = bot_mod.TelegramBot(bot_token="123:abc")
    b._handle_update({
        "callback_query": {
            "id": "cb1",
            "data": "setup_mode:auto",
            "message": {"chat": {"id": 42}, "message_id": 100},
        }
    })
    assert fake_xbmcaddon.get("mode") == "auto"
    assert setup_dm_state.get_state(42) == setup_dm_state.DONE
    assert secrets.get_secret("setup_secret") in (None, "")
    edit_calls = [c for c in captured_sends if c[0].endswith("/editMessageText")]
    assert edit_calls
    assert "Setup complete" in edit_calls[-1][1]["text"]


def test_setup_mode_callback_manual_persists_mode(
    setup_paths, fake_xbmcaddon, captured_sends,
):
    from lib.telegram import bot as bot_mod, setup_dm_state, auth
    auth._save_allowlist([42])
    setup_dm_state.set_state(42, setup_dm_state.AWAITING_MODE)
    b = bot_mod.TelegramBot(bot_token="123:abc")
    b._handle_update({
        "callback_query": {
            "id": "cb1",
            "data": "setup_mode:manual",
            "message": {"chat": {"id": 42}, "message_id": 100},
        }
    })
    assert fake_xbmcaddon.get("mode") == "manual"


def test_setup_mode_callback_from_unauthorized_chat_ignored(
    setup_paths, fake_xbmcaddon, captured_sends,
):
    """Unauthorized chat sending setup_mode:auto must NOT change settings."""
    from lib.telegram import bot as bot_mod, setup_dm_state, auth
    # Don't authorize chat 99.
    setup_dm_state.set_state(99, setup_dm_state.AWAITING_MODE)
    b = bot_mod.TelegramBot(bot_token="123:abc")
    b._handle_update({
        "callback_query": {
            "id": "cb1",
            "data": "setup_mode:auto",
            "message": {"chat": {"id": 99}, "message_id": 100},
        }
    })
    assert fake_xbmcaddon.get("mode", "") == ""


def test_done_state_routes_to_normal_userMsg_flow(
    setup_paths, fake_xbmcaddon, captured_sends,
):
    """Once state is DONE, regular messages enqueue UserMsg (the reasoner
    is then expected to handle them via T4)."""
    from lib import concurrency
    from lib.telegram import bot as bot_mod, setup_dm_state, auth
    auth._save_allowlist([42])
    setup_dm_state.set_state(42, setup_dm_state.DONE)
    while not concurrency.work_queue.empty():
        concurrency.work_queue.get_nowait()
    b = bot_mod.TelegramBot(bot_token="123:abc")
    b._handle_update({
        "message": {"chat": {"id": 42}, "text": "hello", "message_id": 1},
    })
    found = False
    while not concurrency.work_queue.empty():
        _, _, item = concurrency.work_queue.get_nowait()
        if hasattr(item, "chat_id") and item.chat_id == 42:
            found = True
    assert found
