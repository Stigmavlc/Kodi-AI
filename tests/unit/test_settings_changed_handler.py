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
    # H1 — defensive: invalidate setup_dm_state's module-level cache so
    # cross-test leakage from test_telegram_dm_setup.py doesn't affect
    # our status_display tests (which read setup_dm_state).
    try:
        from lib.telegram import setup_dm_state
        setup_dm_state.invalidate_cache()
    except Exception:
        pass
    yield tmp_path
    # Clean up on exit too — keep _cache empty between tests.
    try:
        from lib.telegram import setup_dm_state
        setup_dm_state.invalidate_cache()
    except Exception:
        pass


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


def test_status_display_paired_no_mode_via_dm_state(
    setup_paths, fake_xbmcaddon, monkeypatch,
):
    """H1 — The 'pick agent mode in Telegram' status MUST be reachable
    when an allowlisted chat is in AWAITING_MODE. The previous logic
    keyed off settings.mode which always defaults to 'auto' in
    settings.xml, making the branch dead code.
    """
    from lib import secrets, state_paths
    from lib.telegram import setup_dm_state
    secrets.set_secret("bot_token", "12345:abc")
    secrets.set_secret("openrouter_key", "sk-or-validkey1234567890")
    # Pair a chat.
    import json
    path = state_paths.profile_path("chat_allowlist.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump([5555], f)
    # Set the chat to AWAITING_MODE (key validated but mode not picked).
    setup_dm_state.set_state(5555, setup_dm_state.AWAITING_MODE)
    # Even though Kodi's settings.mode defaults to 'auto', we expect
    # the dm_state signal to win.
    fake_xbmcaddon["mode"] = "auto"
    import service
    status = service._compute_status_display()
    assert "pick" in status.lower() or "agent mode" in status.lower(), (
        f"H1 violation: expected 'pick agent mode' status, got: {status!r}"
    )


def test_settings_handler_redacts_token_on_ssl_error(
    setup_paths, fake_xbmcaddon, stub_xbmcgui, stub_bot_holder, monkeypatch,
):
    """B1 — When requests.get raises a RequestException whose repr()
    embeds the Telegram bot URL (e.g. SSLError, HTTPError), the
    logged message AND any audit entry must have the token REDACTED.

    The redactor's URL-aware pattern (introduced in v0.2.1) catches
    `bot<TOKEN>:<rest>` glued to a path segment. Without redactor.redact()
    on the exception path, the token would leak to kodi.log + audit.
    """
    leaky_token = "1234567890:ABCdefGHIjklMNOpqrSTUvwxYZabcdefgHIjkl"
    fake_xbmcaddon["bot_token"] = leaky_token
    holder, started = stub_bot_holder
    state = {"last_known_bot_token": ""}

    import requests
    # Construct a real RequestException with a repr() that embeds the
    # full URL — this is what happens with HTTPError / SSLError.
    leaky_url = f"https://api.telegram.org/bot{leaky_token}/getMe"

    class FakeSSLError(requests.exceptions.RequestException):
        def __init__(self, msg):
            super().__init__(msg)
            self._msg = msg
        def __repr__(self):
            return f"FakeSSLError({self._msg!r})"
        def __str__(self):
            return self._msg

    def fake_get(url, timeout=None):
        raise FakeSSLError(f"HTTPSConnectionPool(host='api.telegram.org'): bad cert for {leaky_url}")
    monkeypatch.setattr(requests, "get", fake_get)

    # Capture xbmc.log calls so we can assert no token leaks.
    import xbmc
    log_calls: list[tuple[str, int]] = []
    monkeypatch.setattr(xbmc, "log", lambda msg, lvl=0: log_calls.append((msg, lvl)))

    import service
    service._handle_settings_changed(holder, state)

    # Verify SOME log line was emitted about getMe.
    relevant = [msg for msg, _ in log_calls if "getMe" in msg or "network" in msg]
    assert relevant, "expected at least one log entry about getMe failure"
    # CRITICAL — none of the log lines should contain the raw token.
    for msg, _ in log_calls:
        assert leaky_token not in msg, (
            f"TOKEN LEAK in log line: {msg!r}"
        )


def test_handler_skips_revalidation_for_unchanged_token(
    setup_paths, fake_xbmcaddon, stub_xbmcgui, stub_bot_holder, monkeypatch,
):
    """H3 — The debounce mechanism (last_known_bot_token) MUST short-
    circuit when the handler is called twice with the same token.
    """
    import requests
    get_call_urls: list[str] = []

    def fake_get(url, timeout=None):
        get_call_urls.append(url)
        resp = mock.MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "ok": True, "result": {"id": 1, "username": "kodibot"},
        }
        return resp
    monkeypatch.setattr(requests, "get", fake_get)

    fake_xbmcaddon["bot_token"] = "12345:goodtoken"
    holder, started = stub_bot_holder
    state = {"last_known_bot_token": ""}

    import service
    service._handle_settings_changed(holder, state)
    # Handler cleared the Kodi-setting copy. To simulate the user
    # re-opening Configure (no token change) we must put it back so
    # the handler sees the SAME token to compare against state.
    fake_xbmcaddon["bot_token"] = "12345:goodtoken"

    n_before = len(get_call_urls)
    service._handle_settings_changed(holder, state)
    # Second call should NOT have triggered another getMe — the
    # state.last_known_bot_token equals the current Kodi setting.
    assert len(get_call_urls) == n_before, (
        "expected debounce: second call must NOT re-validate same token"
    )


def test_migration_does_not_overwrite_existing_secret(
    setup_paths, fake_xbmcaddon, monkeypatch,
):
    """B3 — If a v0.2.x user has BOTH a working bot_token in secrets.json
    AND a stale residual in Kodi settings, migration MUST preserve the
    secret (source of truth) and merely clear the plaintext residual.
    Never overwrite a non-empty secret with a Kodi-side value.
    """
    from lib import secrets
    # Pre-seed a known-good secret.
    secrets.set_secret("bot_token", "999:CURRENT_GOOD_SECRET")
    # And place a DIFFERENT (stale) residual in Kodi settings.
    fake_xbmcaddon["bot_token"] = "111:STALE_KODI_RESIDUAL"

    import service
    service._migrate_v0_2_x_bot_token()

    # Secret must be UNCHANGED.
    assert secrets.get_secret("bot_token") == "999:CURRENT_GOOD_SECRET", (
        "B3 violation: migration overwrote the existing secret"
    )
    # Kodi setting must be CLEARED (defense in depth).
    assert fake_xbmcaddon.get("bot_token", "") == ""


def test_migration_clears_openrouter_key_kodi_residual(
    setup_paths, fake_xbmcaddon, monkeypatch,
):
    """R3 — Defense-in-depth: openrouter_key residual in Kodi settings
    must be cleared during migration regardless of bot_token state.
    """
    fake_xbmcaddon["openrouter_key"] = "sk-or-stale-key-12345"
    # No bot_token at all → migration's bot_token branch is a no-op.
    import service
    service._migrate_v0_2_x_bot_token()
    assert fake_xbmcaddon.get("openrouter_key", "") == ""


def test_handler_writes_dont_trigger_recursive_settings_change(
    setup_paths, fake_xbmcaddon, stub_xbmcgui, stub_bot_holder, stub_requests_ok,
):
    """B4 — The handler writes derived display fields (status_display,
    bot_username, pairing_command) via setSetting. Each setSetting on a
    real Kodi instance triggers onSettingsChanged on the GUI thread,
    which calls KodiAiMonitor.onSettingsChanged → put_nowait on the
    work queue. Without the suppress guard, this creates a cascade.

    Test: while the handler is running, the suppress flag must be SET
    so any concurrent onSettingsChanged callback short-circuits.
    """
    fake_xbmcaddon["bot_token"] = "12345:goodtoken"
    holder, started = stub_bot_holder
    state = {"last_known_bot_token": ""}

    # Drain the work queue first.
    from lib import concurrency
    while not concurrency.work_queue.empty():
        concurrency.work_queue.get_nowait()

    # Spy on the suppress flag — we wrap settings.set_string to assert
    # the suppress event is SET at the time setSetting is called.
    from lib import settings as settings_mod
    from lib import setup_monitor
    original_set_string = settings_mod.set_string
    suppress_seen: list[bool] = []

    def spy_set_string(key, value):
        suppress_seen.append(setup_monitor._suppress_event.is_set())
        return original_set_string(key, value)
    import service
    monkeypatch_target = service
    # We use a direct attribute patch on the imports lookup — service.py
    # called `from lib import settings` then `settings.set_string`.
    original = service.settings.set_string
    service.settings.set_string = spy_set_string
    try:
        service._handle_settings_changed(holder, state)
    finally:
        service.settings.set_string = original

    # At least one settings.set_string was called inside the handler
    # (status_display update is unconditional).
    assert suppress_seen, "expected handler to write derived fields"
    # ALL such writes must have seen the suppress event SET.
    assert all(suppress_seen), (
        "B4 violation: settings writes did not run under suppress_event"
    )
    # After the handler exits, the event must be CLEARED.
    assert not setup_monitor._suppress_event.is_set(), (
        "B4 violation: suppress_event leaked past handler return"
    )
    # And the KodiAiMonitor.onSettingsChanged would also short-circuit
    # while suppress is set — verify the gate directly.
    setup_monitor._suppress_event.set()
    try:
        # Drain queue then trigger onSettingsChanged.
        while not concurrency.work_queue.empty():
            concurrency.work_queue.get_nowait()
        m = setup_monitor.KodiAiMonitor()
        m.onSettingsChanged()
        assert concurrency.work_queue.empty(), (
            "B4 violation: suppress_event did not block enqueue"
        )
    finally:
        setup_monitor._suppress_event.clear()


def test_set_token_and_start_twice_shows_restart_notice(
    setup_paths, fake_xbmcaddon, stub_xbmcgui, monkeypatch,
):
    """B2 — When set_token_and_start is called a second time with a
    DIFFERENT token, the holder must surface a "restart Kodi" notice
    AND replace the in-memory bot reference (so handlers using get()
    see the new bot for outgoing sends).
    """
    from lib import bot_holder as bot_holder_mod
    # Patch threading.Thread so we don't actually spin up T3.
    started_threads: list = []

    class FakeThread:
        def __init__(self, target=None, name=None, daemon=False):
            self._target = target
            self.name = name
            self.daemon = daemon
            self._alive = False
        def start(self):
            self._alive = True
            started_threads.append(self)
        def is_alive(self):
            return self._alive
        def join(self, timeout=None):
            pass
    monkeypatch.setattr(bot_holder_mod.threading, "Thread", FakeThread)

    # Patch xbmcgui notification to record toasts.
    notifications: list[str] = []
    fake_xbmcgui_module = mock.MagicMock()

    class FakeDialog:
        def notification(self, title, message, **kw):
            notifications.append(message)
    fake_xbmcgui_module.Dialog.return_value = FakeDialog()
    monkeypatch.setitem(sys.modules, "xbmcgui", fake_xbmcgui_module)

    holder = bot_holder_mod.BotHolder()
    holder.set_token_and_start("token-A")
    assert holder.get() is not None
    # T3 was started exactly once.
    assert len(started_threads) == 1

    # Second call with DIFFERENT token: should NOT start another thread,
    # should replace the bot reference, AND should toast.
    holder.set_token_and_start("token-B")
    # No new thread (the old T3 keeps running per B2 Option A).
    assert len(started_threads) == 1
    # Bot reference updated for outgoing sends.
    new_bot = holder.get()
    assert new_bot is not None
    assert new_bot.token == "token-B"
    # Notification surfaced.
    assert any("restart" in n.lower() for n in notifications), (
        f"expected 'restart Kodi' notification, got {notifications!r}"
    )


def test_pairing_nudge_starts_t3_from_secrets(
    setup_paths, fake_xbmcaddon, stub_xbmcgui, stub_bot_holder, monkeypatch,
):
    """v0.4.0 — The script process (default.py) writes bot_token + key into
    secrets.json then bumps the internal _pairing_nudge setting. The service's
    settings-changed handler must react by re-reading secrets and calling
    bot_holder.set_token_and_start so T3 starts in THIS process.
    """
    from lib import secrets
    secrets.set_secret("bot_token", "12345:nudge_token")
    # Simulate the script-process nudge.
    fake_xbmcaddon["_pairing_nudge"] = "1234567890.5"
    holder, started = stub_bot_holder
    state = {"last_known_bot_token": "", "last_pairing_nudge": ""}

    # No requests.get should be called — the nudge path bypasses getMe.
    import requests
    called = []
    monkeypatch.setattr(requests, "get", lambda *a, **kw: (
        called.append(True), mock.MagicMock(status_code=200, json=lambda: {})
    )[1])

    import service
    service._handle_settings_changed(holder, state)

    assert started == ["12345:nudge_token"], (
        "expected nudge path to start T3 with the secrets bot_token"
    )
    assert called == [], "nudge path must NOT call Telegram getMe"
    # Debounce token recorded.
    assert state["last_pairing_nudge"] == "1234567890.5"


def test_pairing_nudge_reads_token_written_cross_process(
    setup_paths, fake_xbmcaddon, stub_xbmcgui, stub_bot_holder, monkeypatch,
):
    """B1 — REGRESSION (cross-process). The SCRIPT process (default.py)
    writes bot_token to secrets.json DIRECTLY ON DISK, then bumps the
    _pairing_nudge setting. The SERVICE process cached an EMPTY secrets
    dict at boot ({} is `not None`, so secrets._load() never re-reads
    disk). Without invalidate_cache() in the nudge branch, get_secret()
    returns None -> token == "" -> T3 (the bot) never starts on a fresh
    install via "Set up via phone".

    This test MUST exercise the real cross-process boundary: it writes
    secrets.json on disk WITHOUT calling secrets.set_secret() in-process
    (set_secret repopulates the service cache and would mask the bug),
    and primes the service-side cache to {} as it is at boot.

    Fails without the lib_secrets.invalidate_cache() fix; passes with it.
    """
    import json as _json
    from lib import secrets, state_paths

    # 1. Prime the SERVICE-side cache to an EMPTY dict, exactly as it is
    #    after boot (no secrets existed when the service started). `{}` is
    #    `not None`, so _load() will short-circuit and never re-read disk.
    secrets.invalidate_cache()
    assert secrets.get_secret("bot_token") is None  # cache now == {}

    # 2. The SCRIPT process writes secrets.json straight to disk. We do NOT
    #    use secrets.set_secret() — that would repopulate the in-process
    #    cache and hide the staleness bug we are testing for.
    secrets_path = state_paths.profile_path("secrets.json")
    os.makedirs(os.path.dirname(secrets_path), exist_ok=True)
    with open(secrets_path, "w", encoding="utf-8") as f:
        _json.dump({"bot_token": "12345:cross_process_token"}, f)

    # Sanity: the stale cache still returns None despite the disk write.
    assert secrets.get_secret("bot_token") is None, (
        "precondition: service cache must be stale before the handler runs"
    )

    # 3. The script process bumps the nudge setting.
    fake_xbmcaddon["_pairing_nudge"] = "9999999999.9"
    holder, started = stub_bot_holder
    state = {"last_known_bot_token": "", "last_pairing_nudge": ""}

    # The nudge path must NOT call Telegram getMe.
    import requests
    called = []
    monkeypatch.setattr(requests, "get", lambda *a, **kw: (
        called.append(True), mock.MagicMock(status_code=200, json=lambda: {})
    )[1])

    import service
    service._handle_settings_changed(holder, state)

    # 4. T3 must have started with the token written cross-process.
    assert started == ["12345:cross_process_token"], (
        "B1 regression: nudge handler must invalidate the secrets cache so "
        "it sees the cross-process disk write and starts T3"
    )
    assert called == [], "nudge path must NOT call Telegram getMe"
    assert state["last_pairing_nudge"] == "9999999999.9"


def test_pairing_nudge_debounced_on_repeat(
    setup_paths, fake_xbmcaddon, stub_xbmcgui, stub_bot_holder, monkeypatch,
):
    """A second handler call with the SAME nudge value must not re-start T3."""
    from lib import secrets
    secrets.set_secret("bot_token", "12345:nudge_token")
    fake_xbmcaddon["_pairing_nudge"] = "777.0"
    holder, started = stub_bot_holder
    state = {"last_known_bot_token": "", "last_pairing_nudge": ""}

    import service
    service._handle_settings_changed(holder, state)
    assert started == ["12345:nudge_token"]

    started.clear()
    # Same nudge value, handler called again (e.g. user edited another setting).
    service._handle_settings_changed(holder, state)
    assert started == [], "expected nudge debounce on identical value"


def test_pairing_nudge_without_token_does_not_start(
    setup_paths, fake_xbmcaddon, stub_xbmcgui, stub_bot_holder, monkeypatch,
):
    """If the nudge fires but secrets has no bot_token yet (race / partial
    write), do NOT attempt to start T3."""
    fake_xbmcaddon["_pairing_nudge"] = "555.0"
    holder, started = stub_bot_holder
    state = {"last_known_bot_token": "", "last_pairing_nudge": ""}

    import service
    service._handle_settings_changed(holder, state)

    assert started == []
    # Nudge still recorded so we don't re-fire on the same value.
    assert state["last_pairing_nudge"] == "555.0"


def test_set_token_and_start_same_token_idempotent(
    setup_paths, fake_xbmcaddon, monkeypatch,
):
    """B2 — Calling set_token_and_start twice with the SAME token must
    be idempotent (no extra threads, no warning toast)."""
    from lib import bot_holder as bot_holder_mod

    started_threads: list = []

    class FakeThread:
        def __init__(self, target=None, name=None, daemon=False):
            self._target = target
            self.name = name
            self.daemon = daemon
            self._alive = False
        def start(self):
            self._alive = True
            started_threads.append(self)
        def is_alive(self):
            return self._alive
        def join(self, timeout=None):
            pass
    monkeypatch.setattr(bot_holder_mod.threading, "Thread", FakeThread)

    notifications: list[str] = []
    fake_xbmcgui_module = mock.MagicMock()

    class FakeDialog:
        def notification(self, title, message, **kw):
            notifications.append(message)
    fake_xbmcgui_module.Dialog.return_value = FakeDialog()
    monkeypatch.setitem(sys.modules, "xbmcgui", fake_xbmcgui_module)

    holder = bot_holder_mod.BotHolder()
    holder.set_token_and_start("token-A")
    holder.set_token_and_start("token-A")
    # Only one T3 started.
    assert len(started_threads) == 1
    # No "restart" notification.
    assert not any("restart" in n.lower() for n in notifications)


# ---- /mode live-effect: _get_router rebuilds when cached mode is stale ----


def test_router_rebuilds_on_mode_change(setup_paths, fake_xbmcaddon, monkeypatch):
    """_get_router() must rebuild the cached router when the persisted `mode`
    setting no longer matches the cached router's mode. This is what makes a
    Telegram /mode change take effect on the NEXT incident without a Kodi
    restart (the bot persists mode via settings; service re-reads it here)."""
    import service
    # Isolate from any prior test that built a router singleton.
    monkeypatch.setattr(service, "_router_instance", None)

    from lib import settings
    fake_xbmcaddon["mode"] = "auto"
    settings.invalidate_cache()

    r1 = service._get_router()
    assert r1.mode == "auto"
    # Same mode → same cached instance (no needless rebuild).
    assert service._get_router() is r1

    # Simulate a /mode manual command persisting the new mode.
    fake_xbmcaddon["mode"] = "manual"
    settings.invalidate_cache()

    r2 = service._get_router()
    assert r2.mode == "manual"
    assert r2 is not r1  # rebuilt


# ---- /budget live-effect: _get_budget applies cap changes in place (H2) ----


def test_get_budget_applies_cap_change_in_place_preserving_spend(
    setup_paths, fake_xbmcaddon, monkeypatch
):
    """H2 — a /budget daily <n> cap change must reach the running service's
    cached BudgetGuard WITHOUT rebuilding it (which would zero the live spend
    counters). _get_budget() re-reads caps each call and mutates them in place;
    the same guard instance is returned and its accumulated spend survives."""
    import service
    # Isolate from any prior test that built a budget singleton.
    monkeypatch.setattr(service, "_budget_instance", None)

    from lib import settings
    fake_xbmcaddon["daily_cap_usd"] = "5.00"
    fake_xbmcaddon["per_incident_cap_usd"] = "0.50"
    fake_xbmcaddon["monthly_cap_usd"] = "30.00"
    settings.invalidate_cache()

    bg1 = service._get_budget()
    assert bg1.daily_cap == 5.00
    # Simulate real spend accumulating on the live guard.
    bg1.record_actual(1.23)
    assert bg1.daily_cost_usd == 1.23

    # Same caps → same instance, untouched.
    assert service._get_budget() is bg1

    # Simulate /budget daily 12 persisting a new cap.
    fake_xbmcaddon["daily_cap_usd"] = "12.00"
    settings.invalidate_cache()

    bg2 = service._get_budget()
    assert bg2 is bg1, "must NOT rebuild — same instance preserves spend"
    assert bg2.daily_cap == 12.00, "new cap applied in place"
    assert bg2.daily_cost_usd == 1.23, "live spend counter preserved across cap change"


def test_get_budget_defaults_when_caps_unset(setup_paths, fake_xbmcaddon, monkeypatch):
    """With no cap settings, _get_budget falls back to the named module
    defaults (M3) rather than bare literals."""
    import service
    monkeypatch.setattr(service, "_budget_instance", None)
    from lib import settings
    settings.invalidate_cache()

    bg = service._get_budget()
    assert bg.per_incident_cap == service.DEFAULT_PER_INCIDENT_CAP_USD
    assert bg.daily_cap == service.DEFAULT_DAILY_CAP_USD
    assert bg.monthly_cap == service.DEFAULT_MONTHLY_CAP_USD
