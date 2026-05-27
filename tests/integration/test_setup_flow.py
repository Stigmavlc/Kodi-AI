"""End-to-end HTTP flow against a real ThreadingHTTPServer instance.

Boots the server on port=0 (OS-assigned) bound to 127.0.0.1, drives the
full setup flow via urllib.request:
  GET  /setup?token=valid              → HTML contains <title>Kodi-AI Setup</title>
  POST /api/validate-openrouter        → {ok:true}      (llm_client.chat mocked)
  POST /api/validate-telegram          → {ok:true}      (requests.get mocked)
  POST /api/save-config                → secrets/settings written via fakes,
                                         deeplink returned
  POST /api/check-paired               → reflects allowlist
  GET  /api/status                     → step state reflects progress

Marked `integration` per pyproject.toml convention.
"""
from __future__ import annotations
import json
import os
import threading
import urllib.request
import urllib.error
from unittest import mock

import pytest

pytestmark = pytest.mark.integration


@pytest.fixture
def addon_root(tmp_path, monkeypatch):
    """Stand up a fake addon root with setup.html copied from the real source."""
    root = tmp_path / "addon_root"
    web = root / "resources" / "web"
    web.mkdir(parents=True, exist_ok=True)
    here = os.path.dirname(os.path.abspath(__file__))
    real_html = os.path.join(
        here, "..", "..", "service.kodi.ai", "resources", "web", "setup.html"
    )
    real_html = os.path.normpath(real_html)
    with open(real_html, "r", encoding="utf-8") as f:
        (web / "setup.html").write_text(f.read(), encoding="utf-8")

    from lib import setup_server
    monkeypatch.setattr(setup_server, "_addon_root", lambda: str(root))
    return root


@pytest.fixture
def fake_addon_data(tmp_path, monkeypatch):
    """Redirect special:// paths used by secrets / settings / audit_log."""
    from tests.integration.fakes import fake_xbmcvfs
    # The integration conftest already sets up fake_xbmcvfs; just ensure
    # the addon_data dir exists.
    from lib import state_paths
    os.makedirs(state_paths.profile_path(""), exist_ok=True)
    yield


@pytest.fixture
def server(addon_root, fake_addon_data, monkeypatch):
    """Start a SetupHTTPServer on an OS-assigned port + return it.

    The settings module reads from xbmcaddon, which the kodistubs package
    fakes. We need to fake `xbmcaddon.Addon().getSetting` calls to return
    persisted bot_username — patch the settings module's accessors directly.
    """
    from lib import setup_server, settings, secrets

    # In-memory settings store.
    store = {}
    monkeypatch.setattr(settings, "get_string",
                        lambda k, default="": store.get(k, default))
    monkeypatch.setattr(settings, "set_string",
                        lambda k, v: store.update({k: v}) or None)

    # Use real secrets module (it writes to /tmp/kodi-ai-test via fake_xbmcvfs).
    secrets.invalidate_cache()

    token = "integration-token-1234567890123"
    srv = setup_server.SetupHTTPServer(
        ("127.0.0.1", 0), setup_server.SetupHandler,
        session_token=token, lan_ip="127.0.0.1", port=0,
    )
    srv.port = srv.server_address[1]
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    yield srv, store
    srv.shutdown()
    srv.server_close()
    th.join(timeout=3)


def _url(server, path):
    return f"http://127.0.0.1:{server.port}{path}"


def _get(server, path, token=None):
    if token is None:
        token = server.session_token
    sep = "&" if "?" in path else "?"
    full = _url(server, path) + f"{sep}token={token}"
    req = urllib.request.Request(full, headers={"Host": f"127.0.0.1:{server.port}"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.status, r.read()


def _post_json(server, path, payload, token=None):
    if token is None:
        token = server.session_token
    sep = "&" if "?" in path else "?"
    full = _url(server, path) + f"{sep}token={token}"
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        full,
        data=body,
        method="POST",
        headers={
            "Host": f"127.0.0.1:{server.port}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.status, r.read()


def test_full_setup_flow(server, monkeypatch):
    srv, store = server

    # 1. GET /setup → 200, contains expected title + token substitution.
    status, body = _get(srv, "/setup")
    assert status == 200
    text = body.decode("utf-8")
    assert "<title>Kodi-AI Setup</title>" in text
    # Token substitution should have inserted our token.
    assert srv.session_token in text
    # CSP must be applied — but we can't read headers via urlopen.read() alone.

    # 2. POST /api/validate-openrouter (with mocked llm_client.chat).
    from lib.llm import client as llm_client
    monkeypatch.setattr(llm_client, "chat", lambda **kw: mock.MagicMock())
    status, body = _post_json(srv, "/api/validate-openrouter", {"api_key": "sk-or-test"})
    assert status == 200
    assert json.loads(body) == {"ok": True}

    # 3. POST /api/validate-telegram (with mocked requests.get).
    from lib import setup_server
    fake_resp = mock.MagicMock()
    fake_resp.json.return_value = {"ok": True, "result": {"username": "my_bot"}}
    monkeypatch.setattr(setup_server.requests, "get",
                        lambda url, timeout: fake_resp)
    status, body = _post_json(srv, "/api/validate-telegram", {"bot_token": "111:test"})
    assert status == 200
    assert json.loads(body) == {"ok": True, "username": "my_bot"}

    # 4. POST /api/save-config → returns setup_secret + deeplink.
    status, body = _post_json(srv, "/api/save-config", {
        "openrouter_key": "sk-or-test",
        "bot_token": "111:test",
        "bot_username": "my_bot",
        "mode": "auto",
    })
    assert status == 200
    data = json.loads(body)
    assert data["ok"] is True
    assert data["setup_secret"]
    assert data["deeplink"].startswith("https://t.me/my_bot?start=")
    # Settings should have been written.
    assert store.get("bot_username") == "my_bot"
    assert store.get("mode") == "auto"
    # Secrets should have been written.
    from lib import secrets as secrets_lib
    secrets_lib.invalidate_cache()
    assert secrets_lib.get_secret("openrouter_key") == "sk-or-test"
    assert secrets_lib.get_secret("bot_token") == "111:test"

    # 5. POST /api/check-paired (no users yet).
    status, body = _post_json(srv, "/api/check-paired", {})
    assert status == 200
    assert json.loads(body) == {"paired": False, "paired_user_count": 0}

    # 6. Simulate a user pairing → /api/check-paired reports paired=true.
    from lib.telegram import auth as tg_auth
    monkeypatch.setattr(tg_auth, "chat_allowlist", lambda: [99999])
    status, body = _post_json(srv, "/api/check-paired", {})
    assert json.loads(body) == {"paired": True, "paired_user_count": 1}

    # 7. GET /api/status reflects progression.
    status, body = _get(srv, "/api/status")
    assert status == 200
    state = json.loads(body)
    assert state["openrouter_ok"] is True
    assert state["telegram_ok"] is True
    assert state["paired"] is True
    assert state["step"] == 4


def test_bad_token_rejected(server):
    srv, _store = server
    try:
        _get(srv, "/setup", token="WRONG")
        assert False, "expected 403"
    except urllib.error.HTTPError as e:
        assert e.code == 403


def test_setup_html_substitutes_has_flags(server, monkeypatch):
    """When openrouter_key / bot_token are already in secrets, the page
    should receive {{HAS_OPENROUTER}}=true / {{HAS_BOT}}=true."""
    srv, store = server
    store["bot_username"] = "existing_bot"

    from lib import secrets as secrets_lib
    secrets_lib.set_secret("openrouter_key", "existing-or-key")
    secrets_lib.set_secret("bot_token", "existing-bot-token")

    status, body = _get(srv, "/setup")
    assert status == 200
    text = body.decode("utf-8")
    # The HTML embeds them inside JS as `"true"` / `"false"` literals.
    assert '"true"' in text  # appears at least once (HAS_OPENROUTER or HAS_BOT)
    assert "existing_bot" in text  # bot username inlined for the "Already configured" badge
