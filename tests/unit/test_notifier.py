"""Unit tests for lib.notifier — retry success/failure paths + shutdown short-path."""
from __future__ import annotations
import sys
import pytest
from unittest import mock


@pytest.fixture
def fake_xbmcgui(monkeypatch):
    """Register a fake xbmcgui module + re-bind lib.notifier.xbmcgui if module already imported.
    Same pattern as state_paths fixture (HANDOVER §4 #15 — module-cache isolation)."""
    fake = mock.MagicMock()
    monkeypatch.setitem(sys.modules, "xbmcgui", fake)
    if "lib.notifier" in sys.modules:
        monkeypatch.setattr(sys.modules["lib.notifier"], "xbmcgui", fake)
    return fake


@pytest.fixture(autouse=True)
def reset_abort_event():
    """abort_event is module-level; reset between tests so prior-test
    is_set() state doesn't bleed into shutdown short-path tests."""
    from lib.concurrency import abort_event
    abort_event.clear()
    yield
    abort_event.clear()


class FakeBot:
    """Bot stand-in. responses is a list of {"ok": bool} dicts; raises if exhausted."""
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[tuple[int, str]] = []

    def send_message(self, chat_id, text, **kw):
        self.calls.append((chat_id, text))
        if not self.responses:
            raise RuntimeError("FakeBot: no more responses queued")
        return self.responses.pop(0)


def test_retry_success_on_first_attempt_returns_ok(fake_xbmcgui, monkeypatch):
    """abort_event not set + bot returns ok → no backoff sleep, ok=True, retries=1."""
    # Patch abort_event.wait so test doesn't actually sleep when delay>0
    from lib import concurrency
    monkeypatch.setattr(concurrency.abort_event, "wait", lambda s: False)
    from lib import notifier
    bot = FakeBot([{"ok": True, "result": {}}])
    ok, retries = notifier.send_message_with_retry(bot, 42, "hello")
    assert ok is True
    assert retries == 1
    assert bot.calls == [(42, "hello")]


def test_retry_failure_then_toast_via_notify_or_toast(fake_xbmcgui, monkeypatch):
    """All 3 send attempts fail → notify_or_toast triggers kodi_toast fallback."""
    from lib import concurrency
    monkeypatch.setattr(concurrency.abort_event, "wait", lambda s: False)
    from lib import notifier
    # 3 retries, each ok=False
    bot = FakeBot([{"ok": False}, {"ok": False}, {"ok": False}])
    ok = notifier.notify_or_toast(bot, 7, "<b>Boom</b>")
    assert ok is False
    assert len(bot.calls) == 3
    # Toast called with stripped HTML
    fake_xbmcgui.Dialog.return_value.notification.assert_called_once()
    args, kwargs = fake_xbmcgui.Dialog.return_value.notification.call_args
    assert args[0] == "Kodi-AI"
    assert args[1] == "Boom"  # <b></b> stripped
    assert kwargs.get("time") == 5000


def test_shutdown_short_path_does_single_attempt(fake_xbmcgui, monkeypatch):
    """abort_event already set at entry → 1 attempt with shutdown timeout, no retries."""
    from lib import concurrency
    concurrency.abort_event.set()
    monkeypatch.setattr(concurrency.abort_event, "wait", lambda s: False)
    from lib import notifier
    bot = FakeBot([{"ok": False}])
    ok, retries = notifier.send_message_with_retry(bot, 42, "shutdown msg")
    assert ok is False
    # Shutdown short-path: backoffs=[0.0] → exactly 1 attempt
    assert retries == 1
    assert len(bot.calls) == 1
