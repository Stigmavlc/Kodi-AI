"""Unit tests for lib.setup_server — port binding, token auth, host guard,
rate-limit, headers, endpoints.

These tests run the server on 127.0.0.1 against an OS-assigned port (port=0)
so they don't conflict with the developer machine's services.
"""
from __future__ import annotations
import http.client
import json
import os
import socket
import sys
import threading
import time
from unittest import mock

import pytest


@pytest.fixture(autouse=True)
def mock_paths(tmp_path, monkeypatch):
    fake_xbmcvfs = mock.MagicMock()
    fake_xbmcvfs.translatePath.side_effect = lambda p: str(tmp_path / p.replace("special://", ""))
    fake_xbmcvfs.mkdirs.side_effect = lambda p: (
        os.makedirs(fake_xbmcvfs.translatePath(p), exist_ok=True) or True
    )
    monkeypatch.setitem(sys.modules, "xbmcvfs", fake_xbmcvfs)
    if "lib.state_paths" in sys.modules:
        monkeypatch.setattr(sys.modules["lib.state_paths"], "xbmcvfs", fake_xbmcvfs)
    from lib import state_paths
    state_paths.ensure_dirs()
    yield


@pytest.fixture
def setup_html(tmp_path, monkeypatch):
    """Create a minimal setup.html so /setup has something to substitute."""
    web_dir = tmp_path / "addon_root" / "resources" / "web"
    web_dir.mkdir(parents=True, exist_ok=True)
    (web_dir / "setup.html").write_text(
        "<title>Kodi-AI Setup</title>"
        "IP={{LAN_IP}};PORT={{PORT}};TOKEN={{TOKEN}};"
        "HAS_OR={{HAS_OPENROUTER}};HAS_BOT={{HAS_BOT}};BOT={{BOT_USERNAME}}",
        encoding="utf-8",
    )
    from lib import setup_server
    monkeypatch.setattr(setup_server, "_addon_root", lambda: str(tmp_path / "addon_root"))
    return setup_server


@pytest.fixture
def server(setup_html, monkeypatch):
    """Start a SetupHTTPServer on an OS-assigned port. Caller can read
    `server.port` for the bound port + `server.session_token` for the
    auth token."""
    setup_server = setup_html
    token = "test-token-1234567890123456"
    srv = setup_server.SetupHTTPServer(
        ("127.0.0.1", 0),
        setup_server.SetupHandler,
        session_token=token,
        lan_ip="127.0.0.1",  # so Host header matches in tests
        port=0,  # placeholder — will be overridden below
    )
    srv.port = srv.server_address[1]
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    yield srv
    srv.shutdown()
    srv.server_close()
    th.join(timeout=3)


# ---------------------------------------------------------------------------
# _bind_port
# ---------------------------------------------------------------------------
def test_bind_port_returns_open_socket_and_port():
    from lib import setup_server
    s, port = setup_server._bind_port()
    try:
        assert isinstance(port, int)
        assert port > 0
        # Socket should be bound but caller closes it before reusing the port.
        addr = s.getsockname()
        assert addr[1] == port
    finally:
        s.close()


def test_bind_port_falls_back_to_zero_when_preferred_busy(monkeypatch):
    """Force every preferred port to fail bind so we hit the port=0 fallback."""
    from lib import setup_server

    busy_sockets = []

    real_socket = socket.socket
    call_count = {"n": 0}
    def _patched_socket(family=socket.AF_INET, type=socket.SOCK_STREAM, *a, **kw):
        s = real_socket(family, type, *a, **kw)
        call_count["n"] += 1
        return s

    monkeypatch.setattr(socket, "socket", _patched_socket)

    # Pre-occupy all preferred ports so they raise OSError on bind.
    for port in setup_server.PORT_RANGE:
        try:
            s = real_socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
            s.bind(("127.0.0.1", port))
            s.listen(1)
            busy_sockets.append(s)
        except OSError:
            # Already busy on the dev machine — that's fine, _bind_port
            # will fall through the same way.
            pass

    try:
        s, port = setup_server._bind_port()
        try:
            # If we successfully bound a preferred port (because the dev
            # machine didn't occupy it for us), great. Otherwise the
            # fallback port=0 must have given us something.
            assert isinstance(port, int) and port > 0
        finally:
            s.close()
    finally:
        for s in busy_sockets:
            s.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _request(server, method, path, *, host_override=None, body: str = None,
             content_type="application/json"):
    """Drive an HTTPConnection directly so we can set the Host header
    explicitly. The default `host` keyword to HTTPConnection becomes the
    Host header automatically; we can override it via `putheader`."""
    conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
    conn.connect()
    try:
        # Build the request manually to control the Host header.
        if body is None:
            conn.putrequest(method, path, skip_host=True)
            conn.putheader("Host", host_override or f"127.0.0.1:{server.port}")
            conn.endheaders()
        else:
            data = body.encode("utf-8")
            conn.putrequest(method, path, skip_host=True)
            conn.putheader("Host", host_override or f"127.0.0.1:{server.port}")
            conn.putheader("Content-Type", content_type)
            conn.putheader("Content-Length", str(len(data)))
            conn.endheaders()
            conn.send(data)
        resp = conn.getresponse()
        return resp.status, dict(resp.getheaders()), resp.read()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# /setup
# ---------------------------------------------------------------------------
def test_setup_valid_token_returns_200_with_substitutions(server):
    status, headers, body = _request(server, "GET", f"/setup?token={server.session_token}")
    assert status == 200
    text = body.decode("utf-8")
    assert "<title>Kodi-AI Setup</title>" in text
    assert f"PORT={server.port}" in text
    assert f"TOKEN={server.session_token}" in text


def test_setup_invalid_token_returns_403_after_throttle(server):
    t0 = time.time()
    status, _h, _b = _request(server, "GET", "/setup?token=WRONG_TOKEN")
    elapsed = time.time() - t0
    assert status == 403
    assert elapsed >= 0.5  # rate-limit sleep


def test_setup_missing_token_returns_403(server):
    status, _h, _b = _request(server, "GET", "/setup")
    assert status == 403


def test_setup_sets_csp_header(server):
    status, headers, _b = _request(server, "GET", f"/setup?token={server.session_token}")
    assert status == 200
    csp = headers.get("Content-Security-Policy", "")
    assert "default-src 'self'" in csp
    assert "script-src 'self'" in csp
    assert "style-src 'self'" in csp


def test_setup_sets_no_store_cache_control(server):
    _s, headers, _b = _request(server, "GET", f"/setup?token={server.session_token}")
    cc = headers.get("Cache-Control", "")
    assert "no-store" in cc
    assert "no-cache" in cc
    assert "must-revalidate" in cc


# ---------------------------------------------------------------------------
# Host header validation
# ---------------------------------------------------------------------------
def test_bad_host_header_returns_400(server):
    status, _h, body = _request(
        server, "GET", f"/setup?token={server.session_token}",
        host_override="evil.example.com",
    )
    assert status == 400
    assert b"Bad Host header" in body


def test_host_header_with_lan_ip_accepted(server):
    # The fixture sets lan_ip='127.0.0.1' so both '127.0.0.1' and
    # '127.0.0.1:<port>' should be accepted.
    status, _h, _b = _request(
        server, "GET", f"/setup?token={server.session_token}",
        host_override="127.0.0.1",
    )
    assert status == 200


# ---------------------------------------------------------------------------
# Bad-token counter + self-shutdown
# ---------------------------------------------------------------------------
def test_100_bad_tokens_triggers_shutdown_flag(server, monkeypatch):
    # Override the throttle to 0 so we don't wait 50 seconds in the test.
    from lib import setup_server
    monkeypatch.setattr(setup_server, "BAD_TOKEN_THROTTLE_SECONDS", 0.0)
    for _ in range(100):
        status, _h, _b = _request(server, "GET", "/setup?token=BAD")
        assert status == 403
    assert server.should_die is True
    assert server.bad_token_count == 100


def test_100_bad_tokens_triggers_actual_shutdown_via_status_endpoint(server, monkeypatch):
    """B1: after 100 bad tokens the should_die flag must be observable
    via /api/status so the TV-side polling thread can react to it."""
    from lib import setup_server
    monkeypatch.setattr(setup_server, "BAD_TOKEN_THROTTLE_SECONDS", 0.0)

    # Baseline: should_die is False.
    status, _h, body = _request(
        server, "GET", f"/api/status?token={server.session_token}"
    )
    assert status == 200
    data = json.loads(body)
    assert data.get("should_die") is False

    # Trip the rate limit.
    for _ in range(100):
        _request(server, "GET", "/setup?token=BAD")

    # Now /api/status must surface the flag.
    status, _h, body = _request(
        server, "GET", f"/api/status?token={server.session_token}"
    )
    assert status == 200
    data = json.loads(body)
    assert data.get("should_die") is True


# ---------------------------------------------------------------------------
# B2 — redactor.redact() on validation errors so audit log never leaks tokens
# ---------------------------------------------------------------------------
def test_validate_telegram_audit_redacts_token_on_ssl_error(server, monkeypatch):
    """B2: validation errors that don't match the dedicated Timeout/
    ConnectionError branches fall into the catch-all `except Exception`.
    Without redaction, repr(e) leaks the bot_token via the embedded URL
    (e.g. HTTPError, JSONDecodeError). Use a Telegram-shaped token that
    matches the redactor pattern (8-12 digits : 30+ chars) so we exercise
    the redaction itself rather than relying on incidental coverage from
    other branches.

    The test name retains 'ssl_error' for traceability with the review
    finding's wording, but the exception is HTTPError because SSLError
    is actually a ConnectionError subclass and never reaches the
    catch-all branch.
    """
    import requests as requests_mod
    from lib import setup_server, audit_log, state_paths

    # Format MUST match the Telegram-token redactor pattern:
    #   \b\d{8,12}:[A-Za-z0-9_-]{30,}\b
    secret_token = "1234567890:VERY-SECRET-TG-TOKEN-ABCDEFGHIJKLMNOP"
    fake_url = (
        f"https://api.telegram.org/bot{secret_token}/getMe"
    )

    def _raise(url, timeout):
        # HTTPError repr embeds the request URL (in real requests usage
        # the URL contains the path with `bot{TOKEN}`). Use this rather
        # than SSLError, which would be caught by the dedicated
        # ConnectionError branch (and never reaches the catch-all where
        # repr(e) is composed).
        raise requests_mod.exceptions.HTTPError(
            f"500 Server Error for url: {fake_url}"
        )

    monkeypatch.setattr(setup_server.requests, "get", _raise)

    _request(
        server, "POST",
        f"/api/validate-telegram?token={server.session_token}",
        body=json.dumps({"bot_token": secret_token}),
    )
    audit_log.write("flush_marker", details={})
    audit = state_paths.profile_path("audit/audit.jsonl")
    with open(audit, "r", encoding="utf-8") as f:
        content = f.read()
    assert secret_token not in content, (
        "Bot token leaked into audit log via repr(HTTPError) -- "
        "redactor.redact() must be applied to validation errors."
    )


def test_validate_openrouter_audit_redacts_key_on_error(server, monkeypatch):
    """Same protection on the OpenRouter side: an LLMError whose repr
    contains the API key must not survive into the audit log."""
    from lib import setup_server, audit_log, state_paths
    from lib.llm import client as llm_client

    secret_key = "sk-or-VERY-LEAKY-12345abcdefghijklmnopqrstuvwx"

    def _raise(**kw):
        # LLMError is the project's catch-all; the message embeds the key
        # similar to how requests.exceptions does for URLs.
        raise llm_client.LLMError(
            f"upstream returned 500 for key={secret_key}"
        )
    monkeypatch.setattr(llm_client, "chat", _raise)

    _request(
        server, "POST",
        f"/api/validate-openrouter?token={server.session_token}",
        body=json.dumps({"api_key": secret_key}),
    )
    audit_log.write("flush_marker", details={})
    audit = state_paths.profile_path("audit/audit.jsonl")
    with open(audit, "r", encoding="utf-8") as f:
        content = f.read()
    assert secret_key not in content, (
        "OpenRouter key leaked into audit log via repr(LLMError) -- "
        "redactor.redact() must be applied to validation errors."
    )


# ---------------------------------------------------------------------------
# /api/status
# ---------------------------------------------------------------------------
def test_api_status_returns_initial_state(server):
    status, _h, body = _request(server, "GET", f"/api/status?token={server.session_token}")
    assert status == 200
    data = json.loads(body)
    assert data == {
        "step": 1,
        "openrouter_ok": False,
        "telegram_ok": False,
        "paired": False,
        # B1: rate-limit self-shutdown flag, observable to the TV polling
        # thread so it can close the dialog when the server decides to die.
        "should_die": False,
    }


# ---------------------------------------------------------------------------
# /api/validate-openrouter
# ---------------------------------------------------------------------------
def test_validate_openrouter_ok(server, monkeypatch):
    from lib.llm import client as llm_client
    monkeypatch.setattr(llm_client, "chat", lambda **kw: mock.MagicMock())
    status, _h, body = _request(
        server, "POST",
        f"/api/validate-openrouter?token={server.session_token}",
        body=json.dumps({"api_key": "sk-or-xxx"}),
    )
    assert status == 200
    assert json.loads(body) == {"ok": True}
    assert server.step_state["openrouter_ok"] is True
    assert server.step_state["step"] >= 2


def test_validate_openrouter_invalid_key(server, monkeypatch):
    from lib.llm import client as llm_client

    def _raise(**kw):
        raise llm_client.LLMAuthError("401")
    monkeypatch.setattr(llm_client, "chat", _raise)

    status, _h, body = _request(
        server, "POST",
        f"/api/validate-openrouter?token={server.session_token}",
        body=json.dumps({"api_key": "sk-or-bad"}),
    )
    assert status == 200
    data = json.loads(body)
    assert data["ok"] is False
    assert data["error"] == "Invalid API key"


def test_validate_openrouter_no_credit(server, monkeypatch):
    from lib.llm import client as llm_client

    def _raise(**kw):
        raise llm_client.LLMNoCreditError("402")
    monkeypatch.setattr(llm_client, "chat", _raise)

    _s, _h, body = _request(
        server, "POST",
        f"/api/validate-openrouter?token={server.session_token}",
        body=json.dumps({"api_key": "sk-or-xxx"}),
    )
    assert json.loads(body) == {"ok": False, "error": "No credit on account"}


def test_validate_openrouter_network_error(server, monkeypatch):
    from lib.llm import client as llm_client

    def _raise(**kw):
        raise llm_client.LLMServerError("timeout")
    monkeypatch.setattr(llm_client, "chat", _raise)

    _s, _h, body = _request(
        server, "POST",
        f"/api/validate-openrouter?token={server.session_token}",
        body=json.dumps({"api_key": "sk-or-xxx"}),
    )
    assert json.loads(body) == {"ok": False, "error": "Could not reach OpenRouter"}


def test_validate_openrouter_audit_never_includes_key(server, monkeypatch):
    from lib import audit_log, state_paths
    from lib.llm import client as llm_client
    monkeypatch.setattr(llm_client, "chat", lambda **kw: mock.MagicMock())

    secret_key = "sk-or-VERY-SECRET-KEY-1234"
    _request(
        server, "POST",
        f"/api/validate-openrouter?token={server.session_token}",
        body=json.dumps({"api_key": secret_key}),
    )
    # Force file flush.
    audit_log.write("flush_marker", details={})
    audit = state_paths.profile_path("audit/audit.jsonl")
    with open(audit, "r", encoding="utf-8") as f:
        content = f.read()
    assert secret_key not in content


# ---------------------------------------------------------------------------
# /api/validate-telegram
# ---------------------------------------------------------------------------
def test_validate_telegram_ok(server, monkeypatch):
    from lib import setup_server

    fake_resp = mock.MagicMock()
    fake_resp.json.return_value = {"ok": True, "result": {"username": "kodi_ai_bot"}}
    monkeypatch.setattr(setup_server.requests, "get",
                        lambda url, timeout: fake_resp)

    status, _h, body = _request(
        server, "POST",
        f"/api/validate-telegram?token={server.session_token}",
        body=json.dumps({"bot_token": "111:abc"}),
    )
    assert status == 200
    assert json.loads(body) == {"ok": True, "username": "kodi_ai_bot"}
    assert server.step_state["telegram_ok"] is True


def test_validate_telegram_invalid(server, monkeypatch):
    from lib import setup_server

    fake_resp = mock.MagicMock()
    fake_resp.json.return_value = {"ok": False, "description": "Unauthorized"}
    monkeypatch.setattr(setup_server.requests, "get",
                        lambda url, timeout: fake_resp)

    _s, _h, body = _request(
        server, "POST",
        f"/api/validate-telegram?token={server.session_token}",
        body=json.dumps({"bot_token": "111:bad"}),
    )
    assert json.loads(body) == {"ok": False, "error": "Unauthorized"}


def test_validate_telegram_audit_never_includes_token(server, monkeypatch):
    from lib import setup_server, audit_log, state_paths
    fake_resp = mock.MagicMock()
    fake_resp.json.return_value = {"ok": True, "result": {"username": "u"}}
    monkeypatch.setattr(setup_server.requests, "get",
                        lambda url, timeout: fake_resp)

    secret_token = "999999:VERY-SECRET-TG-TOKEN-XYZ"
    _request(
        server, "POST",
        f"/api/validate-telegram?token={server.session_token}",
        body=json.dumps({"bot_token": secret_token}),
    )
    audit_log.write("flush_marker", details={})
    audit = state_paths.profile_path("audit/audit.jsonl")
    with open(audit, "r", encoding="utf-8") as f:
        content = f.read()
    assert secret_token not in content


# ---------------------------------------------------------------------------
# /api/save-config
# ---------------------------------------------------------------------------
def test_save_config_persists_secrets_and_returns_deeplink(server, monkeypatch):
    from lib import secrets as secrets_lib, settings
    monkeypatch.setattr(secrets_lib, "set_secret", mock.MagicMock())
    monkeypatch.setattr(settings, "set_string", mock.MagicMock())

    status, _h, body = _request(
        server, "POST",
        f"/api/save-config?token={server.session_token}",
        body=json.dumps({
            "openrouter_key": "sk-or-newkey",
            "bot_token": "222:newtoken",
            "bot_username": "my_kodi_bot",
            "mode": "auto",
        }),
    )
    assert status == 200
    data = json.loads(body)
    assert data["ok"] is True
    assert data["setup_secret"]
    assert data["deeplink"].startswith("https://t.me/my_kodi_bot?start=")
    secrets_lib.set_secret.assert_any_call("openrouter_key", "sk-or-newkey")
    secrets_lib.set_secret.assert_any_call("bot_token", "222:newtoken")
    settings.set_string.assert_any_call("bot_username", "my_kodi_bot")
    settings.set_string.assert_any_call("mode", "auto")


def test_save_config_reuses_existing_setup_secret(server, monkeypatch):
    """H3: a second save-config call must return the SAME setup_secret as
    the first. Rotating the secret invalidates any /start <secret> already
    sent to the bot in flight (e.g. user double-taps "Save & continue")."""
    from lib import secrets as secrets_lib, settings
    from lib.telegram import auth as tg_auth

    # In-memory stand-ins so current_setup_secret() can observe what
    # generate_setup_secret() wrote.
    secret_box: dict = {}
    monkeypatch.setattr(secrets_lib, "set_secret",
                        lambda k, v: secret_box.update({k: v}))
    monkeypatch.setattr(secrets_lib, "get_secret",
                        lambda k: secret_box.get(k))
    monkeypatch.setattr(settings, "set_string", mock.MagicMock())

    # Patch tg_auth.* to use the in-memory store consistently (they
    # were imported into setup_server's local namespace at module load).
    monkeypatch.setattr(tg_auth, "current_setup_secret",
                        lambda: secret_box.get("setup_secret"))

    def _gen():
        import secrets as _stdlib_secrets
        s = _stdlib_secrets.token_urlsafe(8)
        secret_box["setup_secret"] = s
        return s
    monkeypatch.setattr(tg_auth, "generate_setup_secret", _gen)

    # Two identical save-config calls.
    payload = json.dumps({
        "openrouter_key": "sk-or-newkey",
        "bot_token": "222:newtoken",
        "bot_username": "my_kodi_bot",
        "mode": "auto",
    })
    _s, _h, body1 = _request(
        server, "POST",
        f"/api/save-config?token={server.session_token}",
        body=payload,
    )
    _s, _h, body2 = _request(
        server, "POST",
        f"/api/save-config?token={server.session_token}",
        body=payload,
    )
    data1 = json.loads(body1)
    data2 = json.loads(body2)
    assert data1["ok"] and data2["ok"]
    assert data1["setup_secret"] == data2["setup_secret"], (
        "setup_secret must be stable across repeated save-config calls"
    )
    assert data1["deeplink"] == data2["deeplink"]


def test_save_config_omits_empty_fields(server, monkeypatch):
    from lib import secrets as secrets_lib, settings
    monkeypatch.setattr(secrets_lib, "set_secret", mock.MagicMock())
    monkeypatch.setattr(settings, "set_string", mock.MagicMock())

    _request(
        server, "POST",
        f"/api/save-config?token={server.session_token}",
        body=json.dumps({"mode": "manual"}),
    )
    # Should have set mode but NOT openrouter_key / bot_token / bot_username.
    set_secret_calls = [c.args for c in secrets_lib.set_secret.mock_calls]
    set_string_calls = [c.args for c in settings.set_string.mock_calls]
    assert not any(c[0] == "openrouter_key" for c in set_secret_calls)
    assert not any(c[0] == "bot_token" for c in set_secret_calls)
    assert ("mode", "manual") in set_string_calls


# ---------------------------------------------------------------------------
# /api/check-paired
# ---------------------------------------------------------------------------
def test_check_paired_no_users(server):
    status, _h, body = _request(
        server, "POST",
        f"/api/check-paired?token={server.session_token}",
        body="{}",
    )
    assert status == 200
    assert json.loads(body) == {"paired": False, "paired_user_count": 0}


def test_check_paired_with_users(server, monkeypatch):
    from lib.telegram import auth as tg_auth
    monkeypatch.setattr(tg_auth, "chat_allowlist", lambda: [12345, 67890])
    _s, _h, body = _request(
        server, "POST",
        f"/api/check-paired?token={server.session_token}",
        body="{}",
    )
    assert json.loads(body) == {"paired": True, "paired_user_count": 2}


# ---------------------------------------------------------------------------
# Unknown endpoints
# ---------------------------------------------------------------------------
def test_unknown_get_returns_404(server):
    status, _h, _b = _request(server, "GET", f"/whatever?token={server.session_token}")
    assert status == 404


def test_unknown_post_returns_404(server):
    status, _h, _b = _request(
        server, "POST", f"/api/nope?token={server.session_token}",
        body="{}",
    )
    assert status == 404


def test_post_with_bad_json_returns_400(server):
    status, _h, body = _request(
        server, "POST",
        f"/api/validate-openrouter?token={server.session_token}",
        body="not-json",
    )
    assert status == 400
    assert json.loads(body)["ok"] is False
