"""Unit tests for notifier.notify_user + detect-dedupe (v0.5.0 Part 1).

notify_user(bot, chat_ids, telegram_text, toast_text=None, urgency=...) is the
locked-spec primitive: Kodi toast (ALWAYS, unconditionally first) + Telegram
(best-effort per recipient). Each leg is independent — a Telegram failure must
not stop the toast, and an empty/None bot must still toast.

Also covers the detect-dedupe helpers used by _handle_incident to suppress a
flood of "detected" toasts from one root cause (60s window OR an active session).
"""
from __future__ import annotations
import sys
import pytest
from unittest import mock


@pytest.fixture
def fake_xbmcgui(monkeypatch):
    """Register a fake xbmcgui + re-bind lib.notifier.xbmcgui if already imported.
    Same module-cache isolation pattern as test_notifier.py."""
    fake = mock.MagicMock()
    monkeypatch.setitem(sys.modules, "xbmcgui", fake)
    if "lib.notifier" in sys.modules:
        monkeypatch.setattr(sys.modules["lib.notifier"], "xbmcgui", fake)
    return fake


@pytest.fixture(autouse=True)
def reset_abort_event():
    from lib.concurrency import abort_event
    abort_event.clear()
    yield
    abort_event.clear()


@pytest.fixture(autouse=True)
def reset_detect_state():
    """notify_user's detect-dedupe keeps module-level monotonic state; reset
    it between tests so windows/active-session counters don't bleed across."""
    from lib import notifier
    if hasattr(notifier, "_reset_detect_state_for_tests"):
        notifier._reset_detect_state_for_tests()
    yield
    if hasattr(notifier, "_reset_detect_state_for_tests"):
        notifier._reset_detect_state_for_tests()


class FakeBot:
    """Bot stand-in. send_message appends to .calls; optionally raises."""
    def __init__(self, *, raises=False, ok=True):
        self.calls: list[tuple[int, str]] = []
        self._raises = raises
        self._ok = ok

    def send_message(self, chat_id, text, **kw):
        self.calls.append((chat_id, text))
        if self._raises:
            raise RuntimeError("telegram down")
        return {"ok": self._ok, "result": {}}


def _toast_calls(fake_xbmcgui):
    return fake_xbmcgui.Dialog.return_value.notification.call_args_list


# ---- A: notify_user toast always fires ----

def test_notify_user_toast_fires_without_telegram(fake_xbmcgui):
    """bot=None + empty chat_ids → toast still fires, no crash, no send."""
    from lib import notifier
    notifier.notify_user(None, [], "telegram body", toast_text="toast body")
    calls = _toast_calls(fake_xbmcgui)
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args[0] == "Kodi-AI"
    assert args[1] == "toast body"


def test_notify_user_toast_uses_telegram_text_when_no_toast_text(fake_xbmcgui):
    """toast_text=None → falls back to telegram_text for the toast body."""
    from lib import notifier
    notifier.notify_user(None, [], "the only text")
    args, _ = _toast_calls(fake_xbmcgui)[0]
    assert args[1] == "the only text"


def test_notify_user_high_urgency_plays_sound(fake_xbmcgui):
    """urgency='high' → sound=True; default urgency → sound=False."""
    from lib import notifier
    notifier.notify_user(None, [], "x", urgency="high")
    _, kwargs = _toast_calls(fake_xbmcgui)[0]
    assert kwargs.get("sound") is True

    fake_xbmcgui.Dialog.return_value.notification.reset_mock()
    notifier.notify_user(None, [], "y", urgency="medium")
    _, kwargs2 = _toast_calls(fake_xbmcgui)[0]
    assert kwargs2.get("sound") is False


def test_notify_user_truncates_long_toast(fake_xbmcgui):
    """A very long body is truncated for the toast (Kodi shows ~1 line) and the
    truncation marker stays ASCII (Kodi-toast ASCII constraint)."""
    from lib import notifier
    long_text = "A" * 5000
    notifier.notify_user(None, [], long_text, toast_text="A" * 5000)
    args, _ = _toast_calls(fake_xbmcgui)[0]
    body = args[1]
    assert len(body) < 400  # truncated to a sane length
    body.encode("ascii")  # raises if any non-ASCII char slipped in
    assert body.endswith("...")


# ---- A: Telegram leg independent of toast ----

def test_notify_user_telegram_failure_still_toasts(fake_xbmcgui):
    """bot.send_message raises → toast still fired, no exception propagates."""
    from lib import notifier
    bot = FakeBot(raises=True)
    # Must not raise.
    notifier.notify_user(bot, [42], "tg text", toast_text="toast text")
    # Toast fired despite the telegram failure.
    assert len(_toast_calls(fake_xbmcgui)) == 1
    # Telegram was at least attempted.
    assert bot.calls and bot.calls[0][0] == 42


def test_notify_user_one_bad_recipient_does_not_block_others(fake_xbmcgui, monkeypatch):
    """Each recipient is wrapped independently — a raise on the first chat must
    not prevent the send to the second chat."""
    from lib import notifier
    sent: list[int] = []

    def fake_send(bot, chat_id, text, **kw):
        sent.append(chat_id)
        if chat_id == 1:
            raise RuntimeError("boom")
        return (True, 1)

    monkeypatch.setattr(notifier, "send_message_with_retry", fake_send)
    bot = FakeBot()
    notifier.notify_user(bot, [1, 2], "body")
    assert sent == [1, 2]
    assert len(_toast_calls(fake_xbmcgui)) == 1


def test_notify_user_sends_telegram_to_each_chat(fake_xbmcgui, monkeypatch):
    """With a live bot + non-empty chat_ids, telegram_text goes to every chat."""
    from lib import notifier
    sent: list[tuple[int, str]] = []
    monkeypatch.setattr(
        notifier, "send_message_with_retry",
        lambda bot, cid, text, **kw: (sent.append((cid, text)), (True, 1))[1],
    )
    bot = FakeBot()
    notifier.notify_user(bot, [10, 20], "hello telegram")
    assert sent == [(10, "hello telegram"), (20, "hello telegram")]


def test_notify_user_toast_failure_does_not_block_telegram(monkeypatch):
    """If xbmcgui.Dialog().notification raises, the Telegram leg still runs."""
    from lib import notifier
    boom = mock.MagicMock()
    boom.Dialog.return_value.notification.side_effect = RuntimeError("no gui")
    monkeypatch.setitem(sys.modules, "xbmcgui", boom)
    monkeypatch.setattr(notifier, "xbmcgui", boom)
    sent: list[int] = []
    monkeypatch.setattr(
        notifier, "send_message_with_retry",
        lambda bot, cid, text, **kw: (sent.append(cid), (True, 1))[1],
    )
    notifier.notify_user(FakeBot(), [5], "still sends")
    assert sent == [5]


# ---- D: detect-dedupe window ----

def test_detect_dedupe_first_allows_then_suppresses(fake_xbmcgui):
    """First detect is allowed (arms the window); an immediate second is
    suppressed by the 60s window."""
    from lib import notifier
    assert notifier.detect_dedupe_check_and_arm() is True
    assert notifier.detect_dedupe_check_and_arm() is False


def test_detect_dedupe_expires_after_window(fake_xbmcgui, monkeypatch):
    """Once the window elapses (and no active session), detect is allowed again."""
    from lib import notifier
    base = [1000.0]
    monkeypatch.setattr(notifier.time, "monotonic", lambda: base[0])
    assert notifier.detect_dedupe_check_and_arm() is True
    base[0] += 61.0  # advance past the 60s window
    assert notifier.detect_dedupe_check_and_arm() is True


def test_detect_dedupe_active_session_suppresses(fake_xbmcgui, monkeypatch):
    """An active reasoner session suppresses a new detect even if the time
    window would otherwise allow it."""
    from lib import notifier
    base = [2000.0]
    monkeypatch.setattr(notifier.time, "monotonic", lambda: base[0])
    assert notifier.detect_dedupe_check_and_arm() is True
    notifier.session_started()
    base[0] += 120.0  # window long expired
    assert notifier.detect_dedupe_check_and_arm() is False
    notifier.session_ended()
    # Window also expired, no active session → allowed again.
    assert notifier.detect_dedupe_check_and_arm() is True


def test_session_counter_never_negative(fake_xbmcgui):
    """Defensive: extra session_ended() calls don't drive the counter negative
    (which would wedge dedupe into always-suppress)."""
    from lib import notifier
    notifier.session_ended()
    notifier.session_ended()
    # A fresh detect should still be allowed.
    assert notifier.detect_dedupe_check_and_arm() is True
