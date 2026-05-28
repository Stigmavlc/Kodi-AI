"""Unit tests for default.setup_manual (v0.4.0 no-phone fallback).

setup_manual lets a user type the bot token on the TV when they can't/won't
use the phone relay. It validates via getMe, stores the token, generates the
setup_secret, and nudges the service process to start T3.

Coverage:
  - happy path: input token -> getMe ok -> stores token, generates secret,
    sets bot_username, bumps _pairing_nudge, shows pairing instruction.
  - empty input -> no-op (nothing stored, no call).
  - invalid token (getMe ok:false) -> error dialog, nothing stored.
  - network error -> redacted, error dialog, nothing stored.
  - getMe URL/token never leaks into xbmc.log on the error path.
"""
from __future__ import annotations
import os
import sys
from unittest import mock

import pytest


@pytest.fixture
def setup_paths(tmp_path, monkeypatch):
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
def fake_settings(monkeypatch):
    store: dict[str, str] = {}
    inst = mock.MagicMock()
    inst.getSetting.side_effect = lambda k: store.get(k, "")
    inst.setSetting.side_effect = lambda k, v: store.__setitem__(k, v)
    mod = mock.MagicMock()
    mod.Addon.return_value = inst
    monkeypatch.setitem(sys.modules, "xbmcaddon", mod)
    if "lib.settings" in sys.modules:
        monkeypatch.setattr(sys.modules["lib.settings"], "xbmcaddon", mod)
        monkeypatch.setattr(sys.modules["lib.settings"], "_cache", {})
    return store


_DIALOG_LOG: list[tuple] = []


class FakeDialog:
    input_result = ""

    def ok(self, heading, message):
        _DIALOG_LOG.append(("ok", heading, message))
        return True

    def input(self, heading, *a, **kw):
        return FakeDialog.input_result

    def notification(self, *a, **kw):
        return None


class FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


@pytest.fixture
def kodi_ui(monkeypatch):
    _DIALOG_LOG.clear()
    FakeDialog.input_result = ""
    import default as default_mod
    monkeypatch.setattr(default_mod.xbmcgui, "Dialog", FakeDialog)
    return default_mod


@pytest.fixture
def patch_requests(monkeypatch):
    import default as default_mod

    class Recorder:
        def __init__(self):
            self.get_response = {"ok": True, "result": {"username": "manualbot"}}
            self.get_raises = None
            self.calls: list[tuple] = []

        def get(self, url, timeout=None):
            self.calls.append(("GET", url))
            if self.get_raises is not None:
                raise self.get_raises
            return FakeResp(self.get_response)

    rec = Recorder()
    monkeypatch.setattr(default_mod, "requests", rec)
    return rec


def test_happy_path_stores_token_secret_and_nudges(
    setup_paths, fake_settings, kodi_ui, patch_requests,
):
    default_mod = kodi_ui
    from lib import secrets, settings
    from lib.telegram import auth as tg_auth

    FakeDialog.input_result = "123456:MANUALTOKEN"

    default_mod.setup_manual()

    assert secrets.get_secret("bot_token") == "123456:MANUALTOKEN"
    assert tg_auth.current_setup_secret() is not None
    settings.invalidate_cache()
    assert settings.get_string("bot_username") == "manualbot"
    assert fake_settings.get("_pairing_nudge", "")
    # Pairing instruction shown.
    oks = [m for (kind, h, m) in _DIALOG_LOG if kind == "ok"]
    assert any("/start" in m for m in oks)


def test_empty_input_is_noop(
    setup_paths, fake_settings, kodi_ui, patch_requests,
):
    default_mod = kodi_ui
    from lib import secrets
    FakeDialog.input_result = ""

    default_mod.setup_manual()

    assert secrets.get_secret("bot_token") in (None, "")
    assert patch_requests.calls == []
    assert fake_settings.get("_pairing_nudge", "") == ""


def test_invalid_token_shows_error_stores_nothing(
    setup_paths, fake_settings, kodi_ui, patch_requests,
):
    default_mod = kodi_ui
    from lib import secrets
    FakeDialog.input_result = "bogus"
    patch_requests.get_response = {"ok": False, "error_code": 401}

    default_mod.setup_manual()

    assert secrets.get_secret("bot_token") in (None, "")
    assert fake_settings.get("_pairing_nudge", "") == ""
    oks = [m for (kind, h, m) in _DIALOG_LOG if kind == "ok"]
    assert any("did not validate" in m.lower() or "botfather" in m.lower() for m in oks)


def test_network_error_redacted_no_token_leak(
    setup_paths, fake_settings, kodi_ui, patch_requests, monkeypatch,
):
    default_mod = kodi_ui
    from lib import secrets
    # Realistic BotFather token shape (35-char body) so the redactor's
    # URL-aware Telegram pattern engages, matching the real leak vector.
    leaky_token = "1234567890:ABCdefGHIjklMNOpqrSTUvwxYZabcdefgHI"
    FakeDialog.input_result = leaky_token

    import requests as real_requests
    leaky_url = f"https://api.telegram.org/bot{leaky_token}/getMe"

    class LeakyError(real_requests.exceptions.RequestException):
        def __repr__(self):
            return f"LeakyError('connect fail for {leaky_url}')"

    patch_requests.get_raises = LeakyError()

    logs: list[str] = []
    monkeypatch.setattr(default_mod.xbmc, "log", lambda msg, lvl=0: logs.append(msg))

    default_mod.setup_manual()

    assert secrets.get_secret("bot_token") in (None, "")
    # The token must not appear raw in any log line.
    for msg in logs:
        assert leaky_token not in msg, f"TOKEN LEAK: {msg!r}"
    # A user-facing error dialog was shown.
    oks = [m for (kind, h, m) in _DIALOG_LOG if kind == "ok"]
    assert any("telegram" in m.lower() or "connection" in m.lower() for m in oks)
