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
    """Fake xbmcvfs for cmd_audit + auth.current_setup_secret + budget reads,
    and a writable in-memory xbmcaddon so settings reads/writes round-trip."""
    fake = mock.MagicMock()
    fake.translatePath.side_effect = lambda p: str(tmp_path / p.replace("special://", ""))
    fake.mkdirs.side_effect = lambda p: os.makedirs(fake.translatePath(p), exist_ok=True) or True
    monkeypatch.setitem(sys.modules, "xbmcvfs", fake)
    if "lib.state_paths" in sys.modules:
        monkeypatch.setattr(sys.modules["lib.state_paths"], "xbmcvfs", fake)

    # Writable in-memory Kodi settings (same pattern as
    # test_settings_changed_handler.py). cmd_mode persists "mode" here, and
    # cmd_status / cmd_budget read caps + mode back out of it.
    fake_settings: dict[str, str] = {}

    fake_addon_inst = mock.MagicMock()
    fake_addon_inst.getSetting.side_effect = lambda k: fake_settings.get(k, "")
    fake_addon_inst.setSetting.side_effect = lambda k, v: fake_settings.__setitem__(k, v)
    fake_xbmcaddon = mock.MagicMock()
    fake_xbmcaddon.Addon.return_value = fake_addon_inst
    monkeypatch.setitem(sys.modules, "xbmcaddon", fake_xbmcaddon)

    from lib import state_paths, secrets, settings
    if "lib.settings" in sys.modules:
        monkeypatch.setattr(sys.modules["lib.settings"], "xbmcaddon", fake_xbmcaddon)
        monkeypatch.setattr(sys.modules["lib.settings"], "_cache", {})
    state_paths.ensure_dirs()
    secrets.invalidate_cache()
    settings.invalidate_cache()
    yield fake_settings


def test_cmd_help_sends_help_text():
    from lib.telegram import commands
    bot = FakeBot()
    commands.cmd_help(bot, 42, "")
    assert len(bot.sent) == 1
    assert bot.sent[0][0] == 42
    assert "Kodi-AI commands" in bot.sent[0][1]
    assert "/help" in bot.sent[0][1]


def test_cmd_status_sends_a_message(setup_paths):
    """Status must always emit a single message for the chat, even with no
    config/budget present."""
    from lib.telegram import commands
    bot = FakeBot()
    commands.cmd_status(bot, 42, "")
    assert len(bot.sent) == 1
    assert bot.sent[0][0] == 42
    assert bot.sent[0][1]  # non-empty


def test_cmd_mode_persists_setting(setup_paths):
    """cmd_mode('auto'|'manual') must actually persist mode to settings.
    Garbage must NOT write and must echo usage + current mode."""
    from lib.telegram import commands
    from lib import settings
    bot = FakeBot()

    commands.cmd_mode(bot, 1, "auto")
    assert settings.get_string("mode") == "auto"
    assert setup_paths.get("mode") == "auto"
    assert "Mode set to" in bot.sent[0][1]
    assert "auto" in bot.sent[0][1]

    commands.cmd_mode(bot, 1, "manual")
    assert settings.get_string("mode") == "manual"
    assert setup_paths.get("mode") == "manual"
    assert "manual" in bot.sent[1][1]

    # Garbage → usage message, NO write (mode stays "manual").
    commands.cmd_mode(bot, 1, "garbage")
    assert settings.get_string("mode") == "manual"  # unchanged
    assert "Usage:" in bot.sent[2][1]
    assert "/mode auto|manual" in bot.sent[2][1]
    assert "manual" in bot.sent[2][1]  # current mode echoed

    # Empty → usage message too.
    commands.cmd_mode(bot, 1, "")
    assert "Usage:" in bot.sent[3][1]
    assert settings.get_string("mode") == "manual"


def test_cmd_status_reports_real_mode_and_caps(setup_paths):
    """Status must reflect the real persisted mode + the real daily cap, not
    the old hardcoded placeholder text."""
    from lib.telegram import commands
    from lib import settings
    setup_paths["mode"] = "manual"
    setup_paths["daily_cap_usd"] = "12.50"
    settings.invalidate_cache()

    bot = FakeBot()
    commands.cmd_status(bot, 42, "")
    msg = bot.sent[0][1]
    assert "manual" in msg
    assert "12.50" in msg
    # Must NOT be the old placeholder.
    assert "Detailed status: V2" not in msg


def test_cmd_status_no_secret_leak(setup_paths):
    """Status reports 'configured' yes/no but never prints the secret values."""
    from lib.telegram import commands
    from lib import secrets
    secrets.set_secret("bot_token", "123456:SUPERSECRETTOKENVALUE")
    secrets.set_secret("openrouter_key", "sk-or-SECRETKEYVALUE12345")

    bot = FakeBot()
    commands.cmd_status(bot, 42, "")
    msg = bot.sent[0][1]
    assert "SUPERSECRETTOKENVALUE" not in msg
    assert "123456:SUPERSECRETTOKENVALUE" not in msg
    assert "sk-or-SECRETKEYVALUE12345" not in msg
    assert "SECRETKEYVALUE" not in msg
    # Should still indicate configured state.
    assert "yes" in msg.lower()


def test_cmd_status_handles_missing_budget_state(setup_paths):
    """No budget_counters.json on disk → status still returns a message, no
    crash, and shows $0.00 spent."""
    from lib.telegram import commands
    from lib import state_paths
    # Ensure no budget file exists.
    p = state_paths.profile_path("budget_counters.json")
    if os.path.exists(p):
        os.remove(p)

    bot = FakeBot()
    commands.cmd_status(bot, 42, "")
    assert len(bot.sent) == 1
    assert bot.sent[0][1]
    assert "0.00" in bot.sent[0][1]


def test_cmd_budget_reads_real_caps(setup_paths):
    """Budget must reflect the real per_incident/daily/monthly caps, not the
    old hardcoded '$0.50/$5/$30' placeholder."""
    from lib.telegram import commands
    from lib import settings
    setup_paths["per_incident_cap_usd"] = "1.25"
    setup_paths["daily_cap_usd"] = "7.00"
    setup_paths["monthly_cap_usd"] = "42.00"
    settings.invalidate_cache()

    bot = FakeBot()
    commands.cmd_budget(bot, 42, "")
    msg = bot.sent[0][1]
    assert "1.25" in msg
    assert "7.00" in msg
    assert "42.00" in msg
    # Defaults must NOT appear as the reported caps when overridden.
    assert "$0.50, daily=$5, monthly=$30" not in msg


def test_cmd_budget_shows_real_spend(setup_paths):
    """Budget shows persisted daily + monthly spend from budget_counters.json."""
    from lib.telegram import commands
    from lib import settings
    from lib.llm.budget import BudgetGuard
    setup_paths["daily_cap_usd"] = "5.00"
    setup_paths["monthly_cap_usd"] = "30.00"
    settings.invalidate_cache()
    # Seed a persisted budget.
    bg = BudgetGuard(per_incident_cap=0.5, daily_cap=5.0, monthly_cap=30.0)
    bg.record_actual(2.34)
    bg.persist()

    bot = FakeBot()
    commands.cmd_budget(bot, 42, "")
    msg = bot.sent[0][1]
    assert "2.34" in msg


def test_cmd_budget_defaults_when_unset(setup_paths):
    """With no cap settings, budget falls back to documented defaults."""
    from lib.telegram import commands
    bot = FakeBot()
    commands.cmd_budget(bot, 42, "")
    msg = bot.sent[0][1]
    assert "0.50" in msg
    assert "5.00" in msg
    assert "30.00" in msg


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
