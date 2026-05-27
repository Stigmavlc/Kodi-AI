import sys
import pytest
from unittest import mock


@pytest.fixture(autouse=True)
def mock_xbmcaddon(monkeypatch):
    fake_addon = mock.MagicMock()
    fake_addon.getSetting.side_effect = lambda k: {
        "openrouter_key": "sk-or-xxx",
        "bot_token": "12345:abc",
        "mode": "auto",
        "enabled": "true",
        "per_incident_cap_usd": "0.50",
        "triage_rate_per_min": "6",
    }.get(k, "")
    fake_xbmcaddon = mock.MagicMock()
    fake_xbmcaddon.Addon.return_value = fake_addon
    monkeypatch.setitem(sys.modules, "xbmcaddon", fake_xbmcaddon)
    # If lib.settings was already imported by a prior test, its module-level
    # `import xbmcaddon` binding still points to the FIRST test's fake.
    # Re-bind it to this test's fake, and reset the module-level cache so
    # each test runs in isolation. Same pattern used in test_state_paths.py.
    if "lib.settings" in sys.modules:
        monkeypatch.setattr(sys.modules["lib.settings"], "xbmcaddon", fake_xbmcaddon)
        monkeypatch.setattr(sys.modules["lib.settings"], "_cache", {})
    yield fake_addon


def test_get_string(mock_xbmcaddon):
    from lib import settings
    assert settings.get_string("openrouter_key") == "sk-or-xxx"


def test_get_string_missing_returns_default(mock_xbmcaddon):
    from lib import settings
    assert settings.get_string("nonexistent", default="fallback") == "fallback"


def test_get_bool_true(mock_xbmcaddon):
    from lib import settings
    assert settings.get_bool("enabled") is True


def test_get_bool_missing_returns_default(mock_xbmcaddon):
    from lib import settings
    assert settings.get_bool("nonexistent", default=False) is False


def test_get_float(mock_xbmcaddon):
    from lib import settings
    assert settings.get_float("per_incident_cap_usd") == 0.50


def test_get_int(mock_xbmcaddon):
    from lib import settings
    assert settings.get_int("triage_rate_per_min") == 6


def test_invalidate_cache_forces_reread(mock_xbmcaddon):
    from lib import settings
    settings.get_string("mode")  # cache it
    mock_xbmcaddon.getSetting.side_effect = lambda k: "manual" if k == "mode" else ""
    settings.invalidate_cache()
    assert settings.get_string("mode") == "manual"
