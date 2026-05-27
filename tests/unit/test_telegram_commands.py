"""Unit tests for lib.telegram.commands — V1 dispatch + handlers."""
from __future__ import annotations
import os
import sys
import pytest
from unittest import mock


class FakeBot:
    def __init__(self):
        self.sent: list[tuple[int, str]] = []

    def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text))
        return {"ok": True}


@pytest.fixture(autouse=True)
def setup_paths(tmp_path, monkeypatch):
    """Fake xbmcvfs for cmd_audit + auth.current_setup_secret tests."""
    fake = mock.MagicMock()
    fake.translatePath.side_effect = lambda p: str(tmp_path / p.replace("special://", ""))
    fake.mkdirs.side_effect = lambda p: os.makedirs(fake.translatePath(p), exist_ok=True) or True
    monkeypatch.setitem(sys.modules, "xbmcvfs", fake)
    if "lib.state_paths" in sys.modules:
        monkeypatch.setattr(sys.modules["lib.state_paths"], "xbmcvfs", fake)
    from lib import state_paths, secrets
    state_paths.ensure_dirs()
    secrets.invalidate_cache()
    yield


def test_cmd_help_sends_help_text():
    from lib.telegram import commands
    bot = FakeBot()
    commands.cmd_help(bot, 42, "")
    assert len(bot.sent) == 1
    assert bot.sent[0][0] == 42
    assert "Kodi-AI commands" in bot.sent[0][1]
    assert "/help" in bot.sent[0][1]


def test_cmd_status_sends_running():
    from lib.telegram import commands
    bot = FakeBot()
    commands.cmd_status(bot, 42, "")
    assert "running" in bot.sent[0][1]


def test_cmd_mode_accepts_auto_or_manual_rejects_others():
    from lib.telegram import commands
    bot = FakeBot()
    commands.cmd_mode(bot, 1, "auto")
    commands.cmd_mode(bot, 1, "manual")
    commands.cmd_mode(bot, 1, "garbage")
    assert "Mode set to: auto" in bot.sent[0][1]
    assert "Mode set to: manual" in bot.sent[1][1]
    assert "Usage: /mode auto|manual" in bot.sent[2][1]


def test_dispatch_routes_known_command_and_returns_true():
    """dispatch('/help') → True + cmd_help called."""
    from lib.telegram import commands
    bot = FakeBot()
    assert commands.dispatch(bot, 5, "/help") is True
    assert "Kodi-AI commands" in bot.sent[0][1]
    # Unknown command → False, nothing sent
    bot2 = FakeBot()
    assert commands.dispatch(bot2, 5, "/nope") is False
    assert bot2.sent == []
    # Non-slash → False
    assert commands.dispatch(bot2, 5, "hello") is False
    # Stubbed command returns True + emits placeholder
    bot3 = FakeBot()
    assert commands.dispatch(bot3, 5, "/undo") is True
    assert "not yet implemented" in bot3.sent[0][1]
