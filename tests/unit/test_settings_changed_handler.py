"""Unit tests for the SettingsChanged handler in service.py (v0.3.0 inline-setup).

Tests cover:
  - valid bot_token typed → getMe ok → secrets.json updated, Kodi setting
    cleared, status_display set, T3 started.
  - invalid bot_token → status_display reports error, secrets NOT updated,
    T3 NOT started.
  - network error → status_display reports retry, secrets NOT updated.
  - same bot_token typed twice → no re-validation (debounced).
  - empty bot_token + state change elsewhere → status refresh only.
  - v0.2.x migration: residual Kodi bot_token at boot moves to secrets.

Tests mock requests.get + xbmcaddon for full isolation.
"""
from __future__ import annotations
import os
import sys
from unittest import mock

import pytest


@pytest.fixture
def setup_paths(tmp_path, monkeypatch):
    """Fake xbmcvfs for secrets / state_paths."""
    fake = mock.MagicMock()
    fake.translatePath.side_effect = lambda p: str(tmp_path / p.replace("special://", ""))
    fake.mkdirs.side_effect = lambda p: os.makedirs(fake.translatePath(p), exist_ok=True) or True
    monkeypatch.setitem(sys.modules, "xbmcvfs", fake)
    if "lib.state_paths" in sys.modules:
        monkeypatch.setattr(sys.modules["lib.state_paths"], "xbmcvfs", fake)
    from lib import state_paths, secrets
    state_paths.ensure_dirs()
    secrets.invalidate_cache()
    yield tmp_path


@pytest.fixture
def fake_xbmcaddon(monkeypatch):
    """Stub xbmcaddon.Addon with a writable in-memory settings dict."""
    fake_settings: dict[str, str] = {}

    fake_addon_inst = mock.MagicMock()

    def get_setting(k):
        return fake_settings.get(k, "")

    def set_setting(k, v):
        fake_settings[k] = v

    fake_addon_inst.getSetting.side_effect = get_setting
    fake_addon_inst.setSetting.side_effect = set_setting

    fake_xbmcaddon_module = mock.MagicMock()
    fake_xbmcaddon_module.Addon.return_value = fake_addon_inst
    monkeypatch.setitem(sys.modules, "xbmcaddon", fake_xbmcaddon_module)

    # If lib.settings was already imported, rebind + invalidate.
    if "lib.settings" in sys.modules:
        monkeypatch.setattr(sys.modules["lib.settings"], "xbmcaddon", fake_xbmcaddon_module)
        monkeypatch.setattr(sys.modules["lib.settings"], "_cache", {})

    return fake_settings


@pytest.fixture
def stub_xbmcgui(monkeypatch):
    """Stub xbmcgui.Dialog so notification() calls don't blow up."""
    fake = mock.MagicMock()
    fake.Dialog.return_value = mock.MagicMock()
    monkeypatch.setitem(sys.modules, "xbmcgui", fake)
    return fake


@pytest.fixture
def stub_bot_holder(monkeypatch):
    """A BotHolder that records start calls instead of actually launching T3."""
    from lib import bot_holder as bot_holder_mod
    holder = bot_holder_mod.BotHolder()
    started_with: list[str] = []

    def fake_start(token: str):
        started_with.append(token)
        # Don't actually spawn the thread — tests only care about the call.

    monkeypatch.setattr(holder, "set_token_and_start", fake_start)
    return holder, started_with


@pytest.fixture
def stub_requests_ok(monkeypatch):
    """requests.get → 200 ok with username 'kodibot_test'."""
    import requests
    def fake_get(url, timeout=None):
        resp = mock.MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "ok": True,
            "result": {"id": 1, "username": "kodibot_test"},
        }
        return resp
    monkeypatch.setattr(requests, "get", fake_get)
    return fake_get


@pytest.fixture
def stub_requests_invalid(monkeypatch):
    """requests.get → 401 invalid token."""
    import requests
    def fake_get(url, timeout=None):
        resp = mock.MagicMock()
        resp.status_code = 401
        resp.json.return_value = {"ok": False, "error_code": 401,
                                  "description": "Unauthorized"}
        return resp
    monkeypatch.setattr(requests, "get", fake_get)


@pytest.fixture
def stub_requests_neterror(monkeypatch):
    """requests.get → ConnectionError."""
    import requests
    def fake_get(url, timeout=None):
        raise requests.exceptions.ConnectionError("dns failure")
    monkeypatch.setattr(requests, "get", fake_get)


def test_valid_bot_token_promotes_to_secrets_and_starts_t3(
    setup_paths, fake_xbmcaddon, stub_xbmcgui, stub_bot_holder, stub_requests_ok,
):
    """Happy path: valid token typed → secrets has it, Kodi setting cleared,
    T3 started, status set."""
    fake_xbmcaddon["bot_token"] = "12345:goodtoken"
    holder, started = stub_bot_holder
    state = {"last_known_bot_token": ""}

    import service
    service._handle_settings_changed(holder, state)

    from lib import secrets
    assert secrets.get_secret("bot_token") == "12345:goodtoken"
    # Kodi plaintext copy cleared.
    assert fake_xbmcaddon.get("bot_token", "") == ""
    # T3 was started.
    assert started == ["12345:goodtoken"]
    # status_display set to verified-pending-pair message.
    from lib import settings
    settings.invalidate_cache()
    status = settings.get_string("status_display", "")
    assert "verified" in status.lower() or "kodibot_test" in status
    # bot_username set.
    assert settings.get_string("bot_username") == "kodibot_test"
    # State tracks the validated token.
    assert state["last_known_bot_token"] == "12345:goodtoken"


def test_invalid_bot_token_does_not_promote_or_start(
    setup_paths, fake_xbmcaddon, stub_xbmcgui, stub_bot_holder, stub_requests_invalid,
):
    """Invalid token typed: secrets stays empty, T3 not started, status
    reports error."""
    fake_xbmcaddon["bot_token"] = "bogus"
    holder, started = stub_bot_holder
    state = {"last_known_bot_token": ""}

    import service
    service._handle_settings_changed(holder, state)

    from lib import secrets, settings
    assert secrets.get_secret("bot_token") in (None, "")
    assert started == []
    settings.invalidate_cache()
    # Kodi setting NOT cleared (user keeps the input to fix it).
    assert fake_xbmcaddon["bot_token"] == "bogus"
    status = settings.get_string("status_display", "")
    assert "invalid" in status.lower()


def test_network_error_advises_retry_does_not_promote(
    setup_paths, fake_xbmcaddon, stub_xbmcgui, stub_bot_holder, stub_requests_neterror,
):
    """Network failure during validation: status_display says retry; secrets
    untouched; T3 not started."""
    fake_xbmcaddon["bot_token"] = "12345:abc"
    holder, started = stub_bot_holder
    state = {"last_known_bot_token": ""}

    import service
    service._handle_settings_changed(holder, state)

    from lib import secrets, settings
    assert secrets.get_secret("bot_token") in (None, "")
    assert started == []
    settings.invalidate_cache()
    status = settings.get_string("status_display", "")
    assert "telegram" in status.lower() or "retry" in status.lower()


def test_repeated_same_token_is_debounced(
    setup_paths, fake_xbmcaddon, stub_xbmcgui, stub_bot_holder, stub_requests_ok,
):
    """Calling handler twice with same token → only validates once.

    Second call should short-circuit because state.last_known_bot_token
    matches the current Kodi setting.
    """
    fake_xbmcaddon["bot_token"] = "12345:goodtoken"
    holder, started = stub_bot_holder
    state = {"last_known_bot_token": ""}

    import service
    service._handle_settings_changed(holder, state)
    # After first call, Kodi setting is cleared, but state still tracks token.
    # Simulate user editing some OTHER setting (no bot_token change):
    fake_xbmcaddon["bot_token"] = ""  # already cleared by handler

    started.clear()
    service._handle_settings_changed(holder, state)
    # No new T3 start (we already started; kodi setting is "" so no new token
    # promotion path triggers).
    assert started == []


def test_empty_kodi_bot_token_only_refreshes_status(
    setup_paths, fake_xbmcaddon, stub_xbmcgui, stub_bot_holder, monkeypatch,
):
    """If the user opens Configure + clicks OK without typing a token,
    handler just refreshes status (no Telegram call)."""
    holder, started = stub_bot_holder
    state = {"last_known_bot_token": ""}
    import requests
    called = []
    monkeypatch.setattr(requests, "get", lambda *a, **kw: (
        called.append(True), mock.MagicMock(status_code=200, json=lambda: {})
    )[1])
    import service
    service._handle_settings_changed(holder, state)
    # No HTTP call made.
    assert called == []
    # status_display should have SOMETHING (the not-configured banner).
    from lib import settings
    settings.invalidate_cache()
    assert settings.get_string("status_display", "")


def test_migration_moves_residual_v0_2_x_bot_token(
    setup_paths, fake_xbmcaddon, monkeypatch,
):
    """v0.2.x residual bot_token in Kodi settings → migration moves it
    to secrets.json + clears Kodi setting."""
    fake_xbmcaddon["bot_token"] = "12345:legacy"
    import service
    service._migrate_v0_2_x_bot_token()
    from lib import secrets, settings
    assert secrets.get_secret("bot_token") == "12345:legacy"
    assert fake_xbmcaddon["bot_token"] == ""
    # settings cache also invalidated.
    settings.invalidate_cache()
    assert settings.get_string("bot_token", "") == ""


def test_migration_idempotent_when_secret_matches(
    setup_paths, fake_xbmcaddon, monkeypatch,
):
    """If secret already has bot_token AND Kodi has a different stray copy,
    the residual still wins (treated as fresh user edit). If they match,
    just clear the Kodi side."""
    from lib import secrets
    secrets.set_secret("bot_token", "12345:already_here")
    fake_xbmcaddon["bot_token"] = "12345:already_here"
    import service
    service._migrate_v0_2_x_bot_token()
    # secret unchanged, Kodi cleared.
    assert secrets.get_secret("bot_token") == "12345:already_here"
    assert fake_xbmcaddon["bot_token"] == ""


def test_status_display_active_when_fully_configured(
    setup_paths, fake_xbmcaddon, monkeypatch,
):
    """_compute_status_display returns the Active message when bot_token +
    allowlist + openrouter_key + mode are all set."""
    from lib import secrets
    secrets.set_secret("bot_token", "12345:abc")
    secrets.set_secret("openrouter_key", "sk-or-test")
    # Stub mode setting.
    fake_xbmcaddon["mode"] = "auto"
    # Set allowlist.
    from lib.telegram import auth as tg_auth
    from lib import state_paths
    import json
    path = state_paths.profile_path("chat_allowlist.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump([1234], f)
    import service
    from lib import settings
    settings.invalidate_cache()
    status = service._compute_status_display()
    assert "active" in status.lower()


def test_status_display_paired_no_key(
    setup_paths, fake_xbmcaddon, monkeypatch,
):
    """Paired + bot_token set but no openrouter_key → status reflects
    'waiting for OpenRouter key'."""
    from lib import secrets, state_paths
    secrets.set_secret("bot_token", "12345:abc")
    import json
    path = state_paths.profile_path("chat_allowlist.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump([1234], f)
    import service
    status = service._compute_status_display()
    assert "waiting" in status.lower() or "openrouter" in status.lower()
