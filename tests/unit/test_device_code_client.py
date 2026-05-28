"""Unit tests for default.setup_via_phone (v0.4.0 device-code client).

The device-code flow runs in the Kodi SCRIPT process (default.py). These
tests mock `requests` + a fake DialogProgress / Dialog / Monitor so we can
exercise the full state machine without a real Kodi or network.

Coverage:
  - happy path: new -> poll pending -> poll ready -> username-confirm Yes ->
    stores bot_token + openrouter_key + mode + bot_username + setup_secret,
    bumps the cross-process _pairing_nudge.
  - user cancels the progress dialog -> NOTHING stored, no nudge.
  - username-confirm No -> NOTHING stored (secrets stay empty), no nudge.
  - timeout (>=300s elapsed) -> friendly "Code expired" error, nothing stored.
  - relay returns status:"expired" -> friendly error, nothing stored.
  - network error on /api/device/new -> redacted error dialog, nothing stored.
  - empty / non-https relay_url -> "set relay_url" dialog, no network call.
  - poll uses device_code in the Authorization header (NOT the URL).
"""
from __future__ import annotations
import os
import sys
from unittest import mock

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def setup_paths(tmp_path, monkeypatch):
    """Fake xbmcvfs so lib.state_paths / secrets / auth use tmp_path."""
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
    """In-memory Kodi settings dict behind xbmcaddon.Addon + lib.settings."""
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


class FakeProgress:
    """Stand-in for xbmcgui.DialogProgress with scriptable cancellation."""

    def __init__(self):
        self.created = False
        self.closed = False
        self.updates: list[tuple[int, str]] = []
        self._cancel_after = None  # int: cancel once update count reaches this
        self._canceled = False

    def create(self, heading, message=""):
        self.created = True

    def update(self, percent, message=""):
        self.updates.append((percent, message))
        if self._cancel_after is not None and len(self.updates) >= self._cancel_after:
            self._canceled = True

    def iscanceled(self):
        return self._canceled

    def close(self):
        self.closed = True


class FakeMonitor:
    """Stand-in for xbmc.Monitor — never aborts, waitForAbort returns fast."""

    def __init__(self):
        pass

    def abortRequested(self):
        return False

    def waitForAbort(self, timeout=0):
        return False


class FakeDialog:
    """Records ok() calls, scriptable yesno()/input()."""

    yesno_result = True
    input_result = ""

    def __init__(self):
        pass

    def ok(self, heading, message):
        _DIALOG_LOG.append(("ok", heading, message))
        return True

    def yesno(self, heading, message, yeslabel="", nolabel="", **kw):
        _DIALOG_LOG.append(("yesno", heading, message))
        return FakeDialog.yesno_result

    def input(self, heading, *a, **kw):
        _DIALOG_LOG.append(("input", heading, ""))
        return FakeDialog.input_result

    def notification(self, *a, **kw):
        return None


_DIALOG_LOG: list[tuple] = []


@pytest.fixture
def kodi_ui(monkeypatch):
    """Patch default.py's xbmcgui/xbmc references to our fakes."""
    _DIALOG_LOG.clear()
    FakeDialog.yesno_result = True
    FakeDialog.input_result = ""
    import default as default_mod

    progress = FakeProgress()
    monkeypatch.setattr(default_mod.xbmcgui, "DialogProgress", lambda: progress)
    monkeypatch.setattr(default_mod.xbmcgui, "Dialog", FakeDialog)
    monkeypatch.setattr(default_mod.xbmc, "Monitor", FakeMonitor)
    # Make sleeps instant.
    monkeypatch.setattr(default_mod.time, "sleep", lambda s: None)
    return default_mod, progress


class FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


@pytest.fixture
def patch_requests(monkeypatch):
    """Install a scriptable fake `requests` into default.py. Returns a helper
    object with .post_payloads (a callable per call), .poll_sequence (list of
    poll responses consumed in order), and .calls (recorded)."""
    import default as default_mod

    class Recorder:
        def __init__(self):
            self.new_response = {"user_code": "AB3D-7K2M", "device_code": "DEVCODE123"}
            self.new_raises = None
            self.poll_sequence: list = []
            self.calls: list[tuple] = []

        def post(self, url, json=None, timeout=None):
            self.calls.append(("POST", url, json))
            if url.endswith("/api/device/new"):
                if self.new_raises is not None:
                    raise self.new_raises
                return FakeResp(self.new_response)
            raise AssertionError(f"unexpected POST {url}")

        def get(self, url, headers=None, timeout=None):
            self.calls.append(("GET", url, headers))
            if url.endswith("/api/device/poll"):
                if self.poll_sequence:
                    nxt = self.poll_sequence.pop(0)
                else:
                    nxt = {"status": "pending"}
                if isinstance(nxt, Exception):
                    raise nxt
                return FakeResp(nxt)
            raise AssertionError(f"unexpected GET {url}")

    rec = Recorder()
    monkeypatch.setattr(default_mod, "requests", rec)
    return rec


READY_PAYLOAD = {
    "status": "ready",
    "data": {
        "bot_token": "123456:REALTOKEN",
        "openrouter_key": "sk-or-realkey-123",
        "mode": "auto",
        "bot_username": "mykodibot",
    },
    "setup_secret": None,  # filled per-test to match Kodi's generated secret
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_happy_path_stores_secrets_and_nudges(
    setup_paths, fake_settings, kodi_ui, patch_requests,
):
    default_mod, progress = kodi_ui
    from lib import settings, secrets
    from lib.telegram import auth as tg_auth

    fake_settings["relay_url"] = "https://kodi-ai-relay.example.workers.dev"
    settings.invalidate_cache()

    # Poll: pending, then ready. ready.setup_secret matches whatever Kodi
    # generated (we capture it by making the ready payload echo it).
    # Easiest: leave setup_secret None so the mismatch branch is skipped only
    # if equal; instead set it dynamically below.
    pending = {"status": "pending"}

    # We can't know the generated secret in advance, so use a ready payload
    # whose setup_secret we leave as None (treated as "no returned secret" ->
    # no mismatch warning, uses ours).
    ready = dict(READY_PAYLOAD)
    ready["setup_secret"] = None
    patch_requests.poll_sequence = [pending, ready]

    default_mod.setup_via_phone()

    # Secrets stored.
    assert secrets.get_secret("bot_token") == "123456:REALTOKEN"
    assert secrets.get_secret("openrouter_key") == "sk-or-realkey-123"
    # setup_secret was generated + persisted (Kodi owns it).
    assert tg_auth.current_setup_secret() is not None
    # mode + username stored.
    settings.invalidate_cache()
    assert settings.get_string("mode") == "auto"
    assert settings.get_string("bot_username") == "mykodibot"
    # Cross-process nudge bumped.
    assert fake_settings.get("_pairing_nudge", "")
    # Progress dialog was closed.
    assert progress.closed


def test_poll_uses_authorization_header_not_url(
    setup_paths, fake_settings, kodi_ui, patch_requests,
):
    """BLOCKER 3 — device_code must travel in the Authorization header so it
    never lands in Cloudflare's URL access logs."""
    default_mod, progress = kodi_ui
    from lib import settings
    fake_settings["relay_url"] = "https://relay.example.workers.dev"
    settings.invalidate_cache()

    ready = dict(READY_PAYLOAD)
    ready["setup_secret"] = None
    patch_requests.poll_sequence = [ready]

    default_mod.setup_via_phone()

    poll_calls = [c for c in patch_requests.calls if c[0] == "GET"]
    assert poll_calls, "expected at least one poll GET"
    for _, url, headers in poll_calls:
        assert "DEVCODE123" not in url, "device_code leaked into the poll URL"
        assert headers.get("Authorization") == "Bearer DEVCODE123"


def test_user_cancels_progress_no_secrets_written(
    setup_paths, fake_settings, kodi_ui, patch_requests,
):
    default_mod, progress = kodi_ui
    from lib import settings, secrets
    fake_settings["relay_url"] = "https://relay.example.workers.dev"
    settings.invalidate_cache()

    # Cancel as soon as the first progress.update fires (before ready).
    progress._cancel_after = 1
    patch_requests.poll_sequence = [{"status": "pending"}, {"status": "pending"}]

    default_mod.setup_via_phone()

    assert secrets.get_secret("bot_token") in (None, "")
    assert secrets.get_secret("openrouter_key") in (None, "")
    assert fake_settings.get("_pairing_nudge", "") == ""
    assert progress.closed


def test_username_confirm_no_aborts_without_storing(
    setup_paths, fake_settings, kodi_ui, patch_requests,
):
    """BLOCKER 2b — if the user says the received bot is NOT theirs, store
    nothing."""
    default_mod, progress = kodi_ui
    from lib import secrets, settings
    fake_settings["relay_url"] = "https://relay.example.workers.dev"
    settings.invalidate_cache()
    FakeDialog.yesno_result = False  # "No, cancel"

    ready = dict(READY_PAYLOAD)
    ready["setup_secret"] = None
    patch_requests.poll_sequence = [ready]

    default_mod.setup_via_phone()

    assert secrets.get_secret("bot_token") in (None, "")
    assert secrets.get_secret("openrouter_key") in (None, "")
    assert fake_settings.get("_pairing_nudge", "") == ""


def test_timeout_friendly_error_no_secrets(
    setup_paths, fake_settings, kodi_ui, patch_requests, monkeypatch,
):
    """When >=300s elapse without a ready, show 'Code expired' and store
    nothing. We fast-forward the clock via a monkeypatched time.time."""
    default_mod, progress = kodi_ui
    from lib import secrets, settings
    fake_settings["relay_url"] = "https://relay.example.workers.dev"
    settings.invalidate_cache()

    # Clock: first call (start) = 0, every subsequent call jumps past TTL.
    times = iter([0.0] + [10_000.0] * 50)
    monkeypatch.setattr(default_mod.time, "time", lambda: next(times))

    patch_requests.poll_sequence = [{"status": "pending"}] * 10

    default_mod.setup_via_phone()

    assert secrets.get_secret("bot_token") in (None, "")
    # An "expired"/"try again" dialog was shown.
    oks = [m for (kind, h, m) in _DIALOG_LOG if kind == "ok"]
    assert any("expired" in m.lower() or "try again" in m.lower() for m in oks)


def test_relay_status_expired_friendly_error(
    setup_paths, fake_settings, kodi_ui, patch_requests,
):
    default_mod, progress = kodi_ui
    from lib import secrets, settings
    fake_settings["relay_url"] = "https://relay.example.workers.dev"
    settings.invalidate_cache()
    patch_requests.poll_sequence = [{"status": "expired"}]

    default_mod.setup_via_phone()

    assert secrets.get_secret("bot_token") in (None, "")
    oks = [m for (kind, h, m) in _DIALOG_LOG if kind == "ok"]
    assert any("expired" in m.lower() for m in oks)


def test_network_error_on_new_shows_redacted_dialog(
    setup_paths, fake_settings, kodi_ui, patch_requests,
):
    default_mod, progress = kodi_ui
    from lib import secrets, settings
    fake_settings["relay_url"] = "https://relay.example.workers.dev"
    settings.invalidate_cache()

    import requests as real_requests
    patch_requests.new_raises = real_requests.exceptions.ConnectionError("dns boom")

    default_mod.setup_via_phone()

    assert secrets.get_secret("bot_token") in (None, "")
    oks = [m for (kind, h, m) in _DIALOG_LOG if kind == "ok"]
    assert any("relay" in m.lower() or "reach" in m.lower() for m in oks)


def test_empty_relay_url_no_network_call(
    setup_paths, fake_settings, kodi_ui, patch_requests,
):
    default_mod, progress = kodi_ui
    from lib import settings
    fake_settings["relay_url"] = ""
    settings.invalidate_cache()

    default_mod.setup_via_phone()

    assert patch_requests.calls == []
    oks = [m for (kind, h, m) in _DIALOG_LOG if kind == "ok"]
    assert any("relay_url" in m.lower() for m in oks)


def test_garbage_relay_url_rejected(
    setup_paths, fake_settings, kodi_ui, patch_requests,
):
    """Non-https relay_url (e.g. http:// or junk) is rejected with no call."""
    default_mod, progress = kodi_ui
    from lib import settings
    fake_settings["relay_url"] = "http://insecure.example.com"
    settings.invalidate_cache()

    default_mod.setup_via_phone()

    assert patch_requests.calls == []
    oks = [m for (kind, h, m) in _DIALOG_LOG if kind == "ok"]
    assert any("relay_url" in m.lower() for m in oks)


def test_secret_mismatch_warns_but_uses_ours(
    setup_paths, fake_settings, kodi_ui, patch_requests, monkeypatch,
):
    """If the relay echoes a DIFFERENT setup_secret, we log a redacted warning
    and keep using OUR stored secret (BLOCKER 1)."""
    default_mod, progress = kodi_ui
    from lib import settings, secrets
    from lib.telegram import auth as tg_auth
    fake_settings["relay_url"] = "https://relay.example.workers.dev"
    settings.invalidate_cache()

    warnings: list[str] = []
    monkeypatch.setattr(default_mod.xbmc, "log",
                        lambda msg, lvl=0: warnings.append(msg))

    ready = dict(READY_PAYLOAD)
    ready["setup_secret"] = "totally-different-secret"
    patch_requests.poll_sequence = [ready]

    default_mod.setup_via_phone()

    # Stored secret is OURS (generated locally), not the relay's value.
    assert tg_auth.current_setup_secret() != "totally-different-secret"
    assert tg_auth.current_setup_secret() is not None
    assert any("does not match" in w for w in warnings)
    # Still stored the rest.
    assert secrets.get_secret("bot_token") == "123456:REALTOKEN"
