"""Local HTTP server for the phone-driven setup flow.

Threading model:
- `SetupHTTPServer` extends `ThreadingHTTPServer` with `daemon_threads=True`
  so threads exit when the main process does.
- The server runs in a single background thread started by `default.py`;
  ThreadingHTTPServer spawns one handler thread per request.
- Server shutdown is ALWAYS driven from the outer `setup_via_phone()` —
  never from inside a handler (would deadlock).

Security:
- Every request requires a `token` query param matching the session token
  (compared via `secrets.compare_digest`).
- Bad-token requests are throttled with `time.sleep(0.5)` and counted; after
  100 cumulative bad tokens, an internal `should_die` flag is set. The flag
  is exposed via `GET /api/status` so the TV-side polling thread can detect
  it and close the dialog (which drives outer-loop server shutdown).
- `Host:` header is validated against `<lan_ip>:<port>`, `127.0.0.1:<port>`,
  `localhost:<port>`, or the bare-IP forms without port.
- `/setup` HTML response sets a strict Content-Security-Policy. All
  responses set `Cache-Control: no-store, no-cache, must-revalidate`.
- All validation/network error strings written to the audit log are passed
  through `redactor.redact()` because `repr(exception)` can include
  authentication URLs (e.g. SSLError URL contains the Telegram bot_token).

Endpoints (all token-gated):
- GET  /setup                     → mobile setup HTML
- GET  /api/status                → step state + should_die flag
- POST /api/validate-openrouter   → preflight OpenRouter API key
- POST /api/validate-telegram     → validate Telegram bot_token via getMe
- POST /api/save-config           → persist secrets + settings, return deeplink
- POST /api/check-paired          → poll pairing status

Spec: spec §1.14 (revised), §5.2.
"""
from __future__ import annotations
import json
import os
import secrets as _secrets
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional, Tuple
from urllib.parse import urlparse, parse_qs

import requests

from . import redactor

ADDON_ID = "service.kodi.ai"

# Port preference: try this range in order, then fall back to OS-assigned.
PORT_RANGE = list(range(8088, 8100))  # 8088..8099 inclusive

# Server-wide hard limit on bad-token requests.
BAD_TOKEN_HARD_LIMIT = 100
BAD_TOKEN_THROTTLE_SECONDS = 0.5

# Telegram getMe timeout (longer than bot.get_me() default because slow LANs).
TELEGRAM_VALIDATE_TIMEOUT_SECONDS = 10


def _bind_port() -> Tuple[socket.socket, int]:
    """Try ports 8088..8099 in order, fall back to OS-assigned port=0.

    Returns the OPEN socket + port. The caller MUST pass this socket to
    `SetupHTTPServer(..., bound_socket=s)` rather than closing it and
    re-binding — closing + re-binding leaves a race window where another
    LAN process using SO_REUSEADDR could grab the same port between our
    close() and the HTTP server's bind().
    """
    for p in PORT_RANGE:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("0.0.0.0", p))
            return s, p
        except OSError:
            s.close()
            continue

    # Fall back: let the OS assign any free port.
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("0.0.0.0", 0))
    return s, s.getsockname()[1]


class SetupHTTPServer(ThreadingHTTPServer):
    """ThreadingHTTPServer with daemon threads + session state.

    All session state lives on the server instance so handlers can read /
    mutate it via `self.server.<attr>`. Use the `_state_lock` for cross-
    thread coordination (the polling thread reads `step_state`).

    If `bound_socket` is provided, we adopt the already-bound socket
    instead of binding a new one — avoids the close-then-rebind race
    where another LAN process could grab the port in between (see H5).
    """

    daemon_threads = True
    # Allow re-binding the port if a previous instance left a TIME_WAIT.
    allow_reuse_address = True

    def __init__(
        self,
        server_address,
        RequestHandlerClass,
        *,
        session_token: str,
        lan_ip: str,
        port: int,
        bound_socket: Optional[socket.socket] = None,
    ):
        if bound_socket is not None:
            # Adopt the externally-bound socket. Skip super().server_bind()
            # by passing bind_and_activate=False, then plug our socket in
            # and call server_activate() to put it in listening state.
            super().__init__(
                server_address, RequestHandlerClass, bind_and_activate=False,
            )
            # Close the placeholder socket the base class may have created
            # via socketserver.__init__ (it doesn't bind, but we still want
            # to replace the fd).
            try:
                self.socket.close()
            except Exception:
                pass
            self.socket = bound_socket
            # Refresh server_address from the actually-bound socket so
            # the bound port is reflected.
            try:
                self.server_address = self.socket.getsockname()
            except Exception:
                pass
            self.server_activate()
        else:
            super().__init__(server_address, RequestHandlerClass)
        self.session_token = session_token
        self.lan_ip = lan_ip
        self.port = port
        self._state_lock = threading.Lock()
        self.bad_token_count = 0
        self.should_die = False
        # 4-step state for the TV polling thread.
        self.step_state = {
            "step": 1,
            "openrouter_ok": False,
            "telegram_ok": False,
            "paired": False,
        }


class SetupHandler(BaseHTTPRequestHandler):
    """HTTP handler for the setup server. One per request thread."""

    # Suppress default request logging to Kodi.log noise.
    def log_message(self, fmt, *args):  # noqa: A003
        return

    # ---- low-level response helpers ------------------------------------
    def _send_headers(self, status: int, content_type: str, body_len: int,
                      extra: Optional[dict] = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(body_len))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        if extra:
            for k, v in extra.items():
                self.send_header(k, v)
        self.end_headers()

    def _send_text(self, status: int, body: str, *, content_type: str = "text/plain; charset=utf-8") -> None:
        data = body.encode("utf-8")
        self._send_headers(status, content_type, len(data))
        self.wfile.write(data)

    def _send_json(self, status: int, payload: dict) -> None:
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self._send_headers(status, "application/json; charset=utf-8", len(data))
        self.wfile.write(data)

    def _send_html(self, status: int, html: str) -> None:
        data = html.encode("utf-8")
        csp = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'"
        )
        self._send_headers(
            status,
            "text/html; charset=utf-8",
            len(data),
            extra={"Content-Security-Policy": csp},
        )
        self.wfile.write(data)

    # ---- validation ----------------------------------------------------
    def _accepted_hosts(self) -> set:
        """Hosts allowed in the Host: header — exact match against this set
        is required (case-insensitive on the bare host part)."""
        port = self.server.port
        lan = self.server.lan_ip
        return {
            f"{lan}:{port}".lower(),
            f"127.0.0.1:{port}",
            f"localhost:{port}",
            lan.lower(),       # some mobile browsers strip the port for default-ish ports
            "127.0.0.1",
            "localhost",
        }

    def _check_host(self) -> bool:
        host = (self.headers.get("Host") or "").strip().lower()
        return host in self._accepted_hosts()

    def _bad_host(self) -> None:
        expected = f"{self.server.lan_ip}:{self.server.port}"
        self._send_text(400, f"Bad Host header. Expected: {expected}")

    def _extract_token(self) -> Optional[str]:
        qs = parse_qs(urlparse(self.path).query)
        vals = qs.get("token", [])
        return vals[0] if vals else None

    def _check_token(self) -> bool:
        token = self._extract_token() or ""
        server_token = self.server.session_token
        try:
            return _secrets.compare_digest(token, server_token)
        except (TypeError, ValueError):
            return False

    def _reject_bad_token(self) -> None:
        with self.server._state_lock:
            self.server.bad_token_count += 1
            count = self.server.bad_token_count
            if count >= BAD_TOKEN_HARD_LIMIT:
                self.server.should_die = True
        # Throttle. This sleeps in the handler thread — fine because
        # ThreadingHTTPServer dispatches each request to its own thread.
        time.sleep(BAD_TOKEN_THROTTLE_SECONDS)
        self._send_text(403, "Forbidden")

    # ---- dispatch ------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        if not self._check_host():
            self._bad_host()
            return
        if not self._check_token():
            self._reject_bad_token()
            return
        path = urlparse(self.path).path
        if path == "/setup":
            self._handle_setup_html()
        elif path == "/api/status":
            self._handle_get_status()
        else:
            self._send_text(404, "Not Found")

    def do_POST(self) -> None:  # noqa: N802
        if not self._check_host():
            self._bad_host()
            return
        if not self._check_token():
            self._reject_bad_token()
            return
        path = urlparse(self.path).path
        try:
            body = self._read_json_body()
        except ValueError as e:
            self._send_json(400, {"ok": False, "error": f"Bad JSON: {e}"})
            return
        if path == "/api/validate-openrouter":
            self._handle_validate_openrouter(body)
        elif path == "/api/validate-telegram":
            self._handle_validate_telegram(body)
        elif path == "/api/save-config":
            self._handle_save_config(body)
        elif path == "/api/check-paired":
            self._handle_check_paired(body)
        else:
            self._send_text(404, "Not Found")

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        if length > 64 * 1024:
            raise ValueError("body too large")
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise ValueError(str(e))
        if not isinstance(data, dict):
            raise ValueError("expected JSON object")
        return data

    # ---- handlers ------------------------------------------------------
    def _handle_setup_html(self) -> None:
        from . import secrets as secrets_lib, settings  # lazy — avoids import cycles
        addon_path = _addon_root()
        html_path = os.path.join(addon_path, "resources", "web", "setup.html")
        try:
            with open(html_path, "r", encoding="utf-8") as f:
                tpl = f.read()
        except OSError as e:
            self._send_text(500, f"setup.html missing: {e}")
            return
        has_openrouter = bool(secrets_lib.get_secret("openrouter_key"))
        has_bot = bool(secrets_lib.get_secret("bot_token"))
        bot_username = settings.get_string("bot_username") or ""
        # JSON-encode bot_username so the JS literal is well-formed even
        # for unexpected/hostile usernames (defence in depth; Telegram
        # validates the format but we never want template injection here).
        bot_username_js = json.dumps(bot_username)
        out = (tpl
               .replace("{{LAN_IP}}", self.server.lan_ip)
               .replace("{{PORT}}", str(self.server.port))
               .replace("{{TOKEN}}", self.server.session_token)
               .replace("{{HAS_OPENROUTER}}", "true" if has_openrouter else "false")
               .replace("{{HAS_BOT}}", "true" if has_bot else "false")
               .replace("{{BOT_USERNAME_JS}}", bot_username_js)
               .replace("{{BOT_USERNAME}}", bot_username))
        self._send_html(200, out)

    def _handle_get_status(self) -> None:
        with self.server._state_lock:
            payload = dict(self.server.step_state)
            # Surface the rate-limit self-shutdown flag so the TV polling
            # thread can close the dialog (which drives server.shutdown()
            # via setup_via_phone's finally block). Spec §5.2 rate-limit
            # defense (B1).
            payload["should_die"] = bool(self.server.should_die)
        self._send_json(200, payload)

    def _handle_validate_openrouter(self, body: dict) -> None:
        from .llm import client as llm_client
        from . import audit_log
        api_key = str(body.get("api_key") or "").strip()
        if not api_key:
            audit_log.write("setup_validate_openrouter",
                            details={"ok": False, "error": "empty"})
            self._send_json(400, {"ok": False, "error": "Empty API key"})
            return
        ok = False
        err: Optional[str] = None
        try:
            llm_client.chat(
                api_key=api_key,
                model="google/gemini-2.0-flash-001",
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=5,
            )
            ok = True
        except llm_client.LLMAuthError:
            err = "Invalid API key"
        except llm_client.LLMNoCreditError:
            err = "No credit on account"
        except llm_client.LLMServerError:
            err = "Could not reach OpenRouter"
        except llm_client.LLMError as e:
            # repr(e) can leak the bot_token / API key via the URL embedded
            # in network errors (e.g. SSLError("... url: .../{api_key} ...")).
            # audit_log.write does NOT auto-redact (only write_tool_call
            # does), so we redact here before composing the message (B2).
            err = redactor.redact(f"Validation failed: {e!r}")
        except Exception as e:  # network / unexpected
            err = redactor.redact(f"Validation failed: {e!r}")
        audit_log.write("setup_validate_openrouter",
                        details={"ok": ok, "error": err})
        if ok:
            with self.server._state_lock:
                self.server.step_state["openrouter_ok"] = True
                self.server.step_state["step"] = max(
                    self.server.step_state["step"], 2
                )
            self._send_json(200, {"ok": True})
        else:
            self._send_json(200, {"ok": False, "error": err})

    def _handle_validate_telegram(self, body: dict) -> None:
        from . import audit_log
        bot_token = str(body.get("bot_token") or "").strip()
        if not bot_token:
            audit_log.write("setup_validate_telegram",
                            details={"ok": False, "username": "", "error": "empty"})
            self._send_json(400, {"ok": False, "error": "Empty bot token"})
            return
        ok = False
        username = ""
        err: Optional[str] = None
        try:
            r = requests.get(
                f"https://api.telegram.org/bot{bot_token}/getMe",
                timeout=TELEGRAM_VALIDATE_TIMEOUT_SECONDS,
            )
            data = r.json()
            if data.get("ok"):
                ok = True
                username = data.get("result", {}).get("username", "") or ""
            else:
                err = data.get("description") or "Invalid bot token"
        except requests.exceptions.Timeout:
            err = "Could not reach Telegram"
        except requests.exceptions.ConnectionError:
            err = "Could not reach Telegram"
        except Exception as e:
            # repr(e) on SSLError / HTTPError / JSONDecodeError can include
            # the request URL, which contains `bot{TOKEN}` for Telegram.
            # audit_log.write does NOT auto-redact (only write_tool_call
            # does), so we redact here before composing the message (B2).
            err = redactor.redact(f"Validation failed: {e!r}")
        audit_log.write("setup_validate_telegram",
                        details={"ok": ok, "username": username, "error": err})
        if ok:
            with self.server._state_lock:
                self.server.step_state["telegram_ok"] = True
                self.server.step_state["step"] = max(
                    self.server.step_state["step"], 3
                )
            self._send_json(200, {"ok": True, "username": username})
        else:
            self._send_json(200, {"ok": False, "error": err})

    def _handle_save_config(self, body: dict) -> None:
        from . import secrets as secrets_lib, settings, audit_log
        from .telegram import auth as tg_auth
        openrouter_key = str(body.get("openrouter_key") or "").strip()
        bot_token = str(body.get("bot_token") or "").strip()
        bot_username = str(body.get("bot_username") or "").strip()
        mode = str(body.get("mode") or "").strip().lower()
        if openrouter_key:
            secrets_lib.set_secret("openrouter_key", openrouter_key)
        if bot_token:
            secrets_lib.set_secret("bot_token", bot_token)
        if bot_username:
            settings.set_string("bot_username", bot_username)
        if mode in ("auto", "manual"):
            settings.set_string("mode", mode)
        # Reuse an existing secret if one is in flight (e.g. double-tap on
        # "Save & continue" or a browser refresh). Rotating it on every
        # save invalidates any /start <secret> already sent to the bot (H3).
        setup_secret = (
            tg_auth.current_setup_secret()
            or tg_auth.generate_setup_secret()
        )
        effective_username = bot_username or settings.get_string("bot_username") or ""
        deeplink = (
            f"https://t.me/{effective_username}?start={setup_secret}"
            if effective_username else f"(send /start {setup_secret} to your bot)"
        )
        audit_log.write(
            "setup_complete",
            details={
                "has_openrouter_key": bool(openrouter_key) or bool(secrets_lib.get_secret("openrouter_key")),
                "has_bot_token": bool(bot_token) or bool(secrets_lib.get_secret("bot_token")),
                "mode": mode or settings.get_string("mode") or "",
            },
        )
        with self.server._state_lock:
            self.server.step_state["step"] = max(
                self.server.step_state["step"], 4
            )
        self._send_json(200, {
            "ok": True,
            "setup_secret": setup_secret,
            "deeplink": deeplink,
        })

    def _handle_check_paired(self, body: dict) -> None:  # body unused
        from .telegram import auth as tg_auth
        allowlist = tg_auth.chat_allowlist()
        paired = bool(allowlist)
        with self.server._state_lock:
            self.server.step_state["paired"] = paired
            if paired:
                self.server.step_state["step"] = 4
        self._send_json(200, {"paired": paired, "paired_user_count": len(allowlist)})


def _addon_root() -> str:
    """Resolve the on-disk addon root.

    In Kodi the addon is installed via xbmcaddon.Addon().getAddonInfo("path");
    we fall back to walking up from this file's location for tests.
    """
    try:
        import xbmcaddon  # type: ignore
        return xbmcaddon.Addon(ADDON_ID).getAddonInfo("path")
    except Exception:
        # service.kodi.ai/lib/setup_server.py -> service.kodi.ai/
        here = os.path.dirname(os.path.abspath(__file__))
        return os.path.dirname(here)
