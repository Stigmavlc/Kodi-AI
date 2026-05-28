"""Kodi-AI UI entry point. Invoked via RunScript(default.py [, action]).

v0.4.0 device-code setup pivot:
  Setup moves OFF the TV keyboard. default.py exposes these actions
  (wired from settings.xml or the addon's Program-add-ons launch):

    (none)          -> status panel with action menu
    setup_via_phone -> OAuth-device-code flow via the user's Cloudflare
                      Worker relay (show code on TV, fill form on phone)
    setup_manual    -> no-phone fallback: type the bot token on the TV,
                      validate, store, finish pairing in Telegram
    reset_bot       -> confirm + clear allowlist + generate new setup_secret

Cross-process note: default.py runs in the SCRIPT process, which CANNOT
touch BotHolder (it lives in the service process). After storing secrets
we bump the internal `_pairing_nudge` setting; the service's
onSettingsChanged handler reacts by starting T3.

Spec: sec 1.14, sec 5.2, sec 7.3 + v0.4.0 device-code setup pivot.
"""
from __future__ import annotations
import os
import sys
import time

_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs  # noqa: F401 (used transitively via lib.state_paths)

import requests

from lib import state_paths, settings, secrets, redactor
from lib.telegram import auth as tg_auth


ADDON_ID = "service.kodi.ai"


ADDON_NAME = "Kodi-AI"
COLOR_ACCENT = "00D4FF"   # cyan — matches icon glow
COLOR_DIM = "7FB3D5"      # muted cyan for labels
COLOR_OK = "00E676"       # bright green
COLOR_WARN = "FFB300"     # amber
COLOR_ERROR = "FF5252"    # bright red
COLOR_BODY = "F0F8FF"     # off-white body text

_HR = "[COLOR " + COLOR_DIM + "]" + ("─" * 48) + "[/COLOR]"
_BULLET = "[COLOR " + COLOR_ACCENT + "]▸[/COLOR]"


def _h1(text: str) -> str:
    return f"[B][COLOR {COLOR_ACCENT}]{text}[/COLOR][/B]"


def _h2(text: str) -> str:
    return f"[B][COLOR {COLOR_BODY}]{text}[/COLOR][/B]"


def _dim(text: str) -> str:
    return f"[COLOR {COLOR_DIM}]{text}[/COLOR]"


def _safe_health_state() -> dict:
    """lib.health may not exist yet (Phase 11 task). Return empty dict if so."""
    try:
        from lib import health  # type: ignore
        return health.get_state() if hasattr(health, "get_state") else {}
    except Exception:
        return {}


def show_status_panel() -> None:
    """Default action: display status summary + action menu."""
    bot_token = secrets.get_secret("bot_token") or ""
    allowlist = tg_auth.chat_allowlist()
    setup_secret = tg_auth.current_setup_secret()
    health_state = _safe_health_state()
    last_alive = health_state.get("last_alive_ts", 0)
    crash_free_since = health_state.get("crash_free_since", 0)

    lines = [
        _h1(f"{ADDON_NAME}  ·  Status"),
        _dim("AI-assisted Kodi diagnostics + auto-fix via Telegram"),
        _HR,
        "",
        _h2("CONNECTION"),
    ]
    if not bot_token:
        lines.append(
            f"  {_BULLET} [COLOR {COLOR_WARN}]Not configured[/COLOR]   "
            f"{_dim('— open Configure to set up')}"
        )
    elif not allowlist:
        lines.append(
            f"  {_BULLET} [COLOR {COLOR_WARN}]Bot online, no users paired[/COLOR]"
        )
        if setup_secret:
            lines.append(
                f"      {_dim('Setup secret:')} "
                f"[B][COLOR {COLOR_ACCENT}]{setup_secret}[/COLOR][/B]"
            )
    else:
        lines.append(
            f"  {_BULLET} [COLOR {COLOR_OK}]●  Active[/COLOR]    "
            f"{_dim('Paired users:')} [B]{len(allowlist)}[/B]"
        )
    username = settings.get_string("bot_username") or ""
    if username and not username.startswith("("):
        lines.append(
            f"  {_BULLET} {_dim('Bot:')} [B]@{username}[/B]"
        )
    lines.append("")

    lines.append(_h2("AGENT"))
    mode = settings.get_string("mode") or "auto"
    mode_color = COLOR_OK if mode == "auto" else COLOR_DIM
    lines.append(
        f"  {_BULLET} {_dim('Mode:')} [B][COLOR {mode_color}]{mode}[/COLOR][/B]"
    )
    cap_pi = settings.get_float("per_incident_cap_usd", 0.50)
    cap_d = settings.get_float("daily_cap_usd", 5.0)
    cap_m = settings.get_float("monthly_cap_usd", 30.0)
    lines.append(
        f"  {_BULLET} {_dim('Budget caps:')} "
        f"${cap_pi:.2f} {_dim('per incident')}  ·  "
        f"${cap_d:.2f} {_dim('per day')}  ·  "
        f"${cap_m:.2f} {_dim('per month')}"
    )
    lines.append("")

    lines.append(_h2("HEALTH"))
    if last_alive:
        ago = int(time.time() - last_alive)
        ago_str = f"{ago}s" if ago < 60 else f"{ago // 60}m {ago % 60}s"
        beat_color = COLOR_OK if ago < 600 else COLOR_WARN
        lines.append(
            f"  {_BULLET} {_dim('Last heartbeat:')} "
            f"[COLOR {beat_color}]{ago_str} ago[/COLOR]"
        )
    else:
        lines.append(
            f"  {_BULLET} {_dim('Last heartbeat:')} "
            f"[COLOR {COLOR_DIM}]none yet — service may be starting[/COLOR]"
        )
    if crash_free_since:
        days = max(0, int((time.time() - crash_free_since) / 86400))
        lines.append(
            f"  {_BULLET} {_dim('Crash-free:')} [B]{days}d[/B]"
        )
    lines.append("")
    lines.append(_HR)
    lines.append(
        _dim("All setup lives in Configure → Telegram. Reset Bot Owner is "
             "available there for re-pairing.")
    )

    msg = "\n".join(lines)
    xbmcgui.Dialog().textviewer(f"{ADDON_NAME}  ·  Status", msg)

    actions = [
        "Open Configure (Settings)",
        "Reset Bot Owner",
        "View Audit Log",
        "Close",
    ]
    choice = xbmcgui.Dialog().select(f"{ADDON_NAME}  ·  Actions", actions)
    if choice == 0:
        # Open the addon settings dialog. This is the v0.3.0 setup entry point.
        try:
            xbmcaddon.Addon(ADDON_ID).openSettings()
        except Exception:
            xbmcgui.Dialog().ok(
                ADDON_NAME,
                "Open Add-ons → Kodi-AI → Configure to set up.",
            )
    elif choice == 1:
        if xbmcgui.Dialog().yesno(
            "Reset Bot Owner",
            "Clear all authorized users and generate a new setup secret?\n\n"
            "This cannot be undone.",
        ):
            new_secret = tg_auth.reset_bot_owner()
            xbmcgui.Dialog().ok(
                "Bot Owner Reset",
                f"New setup_secret:\n\n"
                f"[COLOR {COLOR_ACCENT}][B]{new_secret}[/B][/COLOR]\n\n"
                f"Open Configure to see the pairing command.",
            )
    elif choice == 2:
        view_audit()
    # choice == 3 (Close) or -1 (cancelled): no-op


def view_audit() -> None:
    """Tail the last ~30 lines of audit.jsonl into a textviewer."""
    p = state_paths.profile_path("audit/audit.jsonl")
    if not os.path.exists(p):
        xbmcgui.Dialog().ok("Audit Log", "No audit entries yet.")
        return
    try:
        with open(p, "rb") as f:
            f.seek(0, 2)
            sz = f.tell()
            f.seek(max(0, sz - 16384))
            tail = f.read().decode("utf-8", errors="replace")
        recent = "\n".join(tail.splitlines()[-30:]) or "(empty)"
        xbmcgui.Dialog().textviewer("Audit Log (recent)", recent)
    except Exception as e:
        xbmcgui.Dialog().ok("Audit Log Error", str(e))


# ---- v0.4.0 device-code + manual setup -------------------------------------

POLL_INTERVAL_S = 3.0
SESSION_TTL_S = 300.0
_HTTP_TIMEOUT = (5, 15)


def _nudge_service() -> None:
    """Cross-process T3 nudge. default.py runs in the SCRIPT process, which
    cannot reach BotHolder (it lives in the service process). Bump an internal
    settings key so the service's onSettingsChanged handler re-reads secrets
    and starts T3. Best-effort - a failure here just delays bot start until
    the next Kodi restart (boot pass starts T3 if a token exists)."""
    try:
        settings.set_string("_pairing_nudge", str(time.time()))
    except Exception:
        pass


def _refresh_pairing_labels(username: str) -> None:
    """Update the read-only bot_username + pairing_command labels (ASCII only).
    The setup_secret is already stored; re-read it to build the command."""
    try:
        secret = tg_auth.current_setup_secret() or ""
        if username:
            settings.set_string("bot_username", username)
        if username and secret:
            settings.set_string(
                "pairing_command", f"/start {secret} to @{username}",
            )
        elif secret:
            settings.set_string("pairing_command", f"/start {secret}")
        settings.set_string(
            "status_display",
            (f"Bot verified - open @{username} in Telegram and tap Start"
             if username
             else "Bot verified - open Telegram to pair"),
        )
    except Exception:
        pass


def _redacted_err(prefix: str, exc: Exception) -> str:
    """Build a user-safe, redacted one-liner for a network/HTTP failure.
    Telegram/relay URLs and tokens can ride inside exception reprs, so we
    always run them through the redactor before showing or logging."""
    try:
        return redactor.redact(f"{prefix}: {exc!r}")
    except Exception:
        return prefix


def setup_via_phone() -> None:
    """OAuth-device-code setup through the user's Cloudflare Worker relay.

    Kodi OWNS the setup_secret (BLOCKER 1): we generate + store it BEFORE
    talking to the relay, send it UP in /api/device/new, and use our copy
    for pairing regardless of what comes back. The device_code travels in
    the Authorization header on every poll (BLOCKER 3). The received bot is
    human-confirmed (BLOCKER 2b) before any secret is stored.
    """
    # 1. Relay URL must be configured + look like an HTTPS URL.
    relay_url = (settings.get_string("relay_url", "") or "").strip().rstrip("/")
    if not relay_url or not relay_url.lower().startswith("https://"):
        xbmcgui.Dialog().ok(
            "Kodi-AI Setup",
            "Set relay_url in Settings - Advanced first. "
            "See cloudflare/DEPLOY.md.",
        )
        return

    # 2. Generate + store the setup_secret NOW (Kodi owns it).
    try:
        setup_secret = tg_auth.generate_setup_secret()
    except Exception as e:
        xbmcgui.Dialog().ok(
            "Kodi-AI Setup", _redacted_err("Could not start setup", e),
        )
        return

    # 3. Ask the relay to mint a device/user code pair.
    try:
        resp = requests.post(
            f"{relay_url}/api/device/new",
            json={"setup_secret": setup_secret},
            timeout=_HTTP_TIMEOUT,
        )
        data = resp.json()
    except Exception as e:
        xbmcgui.Dialog().ok(
            "Kodi-AI Setup",
            "Could not reach your relay.\n\n"
            + _redacted_err("Error", e)
            + "\n\nCheck the Relay URL in Settings - Advanced.",
        )
        return

    user_code = (data or {}).get("user_code") or ""
    device_code = (data or {}).get("device_code") or ""
    if not user_code or not device_code:
        xbmcgui.Dialog().ok(
            "Kodi-AI Setup",
            "Relay did not return a code. Re-check cloudflare/DEPLOY.md "
            "and that the Worker is deployed.",
        )
        return

    # 4. Show the code + URL in a DialogProgress.
    progress = xbmcgui.DialogProgress()
    progress.create("Kodi-AI Setup", "")
    code_line = (
        f"[B][COLOR {COLOR_ACCENT}]{user_code}[/COLOR][/B]"
    )
    body = (
        f"On your phone open:\n[B]{relay_url}[/B]\n\n"
        f"Enter code:\n{code_line}\n\n"
        f"Waiting for your phone..."
    )
    progress.update(0, body)

    # 5. Poll loop.
    abort = xbmc.Monitor()
    start = time.time()
    received = None
    while True:
        # Cancellation / shutdown checks - never write secrets if either.
        if progress.iscanceled() or abort.abortRequested():
            progress.close()
            return
        elapsed = time.time() - start
        if elapsed >= SESSION_TTL_S:
            progress.close()
            xbmcgui.Dialog().ok(
                "Kodi-AI Setup", "Code expired, try again.",
            )
            return
        pct = min(99, int((elapsed / SESSION_TTL_S) * 100))
        progress.update(pct, body)

        try:
            poll = requests.get(
                f"{relay_url}/api/device/poll",
                headers={"Authorization": f"Bearer {device_code}"},
                timeout=_HTTP_TIMEOUT,
            )
            pdata = poll.json()
        except Exception as e:
            # Transient network error - keep polling (don't abort the whole
            # flow on a single blip). Log redacted for diagnostics.
            xbmc.log(
                f"[service.kodi.ai] {_redacted_err('poll error', e)}",
                xbmc.LOGDEBUG,
            )
            pdata = {"status": "pending"}

        status = (pdata or {}).get("status")
        if status == "ready":
            received = pdata
            break
        if status == "expired":
            progress.close()
            xbmcgui.Dialog().ok(
                "Kodi-AI Setup", "Code expired, try again.",
            )
            return

        # Sleep in short slices so cancel/abort stay responsive.
        slept = 0.0
        while slept < POLL_INTERVAL_S:
            if progress.iscanceled() or abort.abortRequested():
                progress.close()
                return
            if abort.waitForAbort(0.5):
                progress.close()
                return
            slept += 0.5

    # 6. Extract payload. setup_secret should match ours; if not, trust ours.
    payload = (received or {}).get("data") or {}
    bot_token = payload.get("bot_token") or ""
    openrouter_key = payload.get("openrouter_key") or ""
    mode = payload.get("mode") or "auto"
    bot_username = payload.get("bot_username") or ""
    returned_secret = (received or {}).get("setup_secret") or ""
    if returned_secret and returned_secret != setup_secret:
        xbmc.log(
            "[service.kodi.ai] setup_via_phone: relay returned a setup_secret "
            "that does not match ours - using our stored secret",
            xbmc.LOGWARNING,
        )

    # Always close the progress dialog before any modal yes/no.
    progress.close()

    if not bot_token or not openrouter_key:
        xbmcgui.Dialog().ok(
            "Kodi-AI Setup",
            "Your phone did not send complete details. Please try again.",
        )
        return

    # 7. Human confirmation (BLOCKER 2b) - never store an attacker's bot.
    confirmed = xbmcgui.Dialog().yesno(
        "Confirm",
        (f"Received bot @{bot_username} and an OpenRouter key.\n\n"
         f"Is @{bot_username} YOUR bot?"),
        yeslabel="Yes, it's mine",
        nolabel="No, cancel",
    )
    if not confirmed:
        # Abort: store nothing. (setup_secret remains set for a retry.)
        return

    # 8. Store secrets + settings. setup_secret is already stored (step 2).
    try:
        secrets.set_secret("bot_token", bot_token)
        secrets.set_secret("openrouter_key", openrouter_key)
        settings.set_string("mode", mode if mode in ("auto", "manual") else "auto")
        if bot_username:
            settings.set_string("bot_username", bot_username)
    except Exception as e:
        xbmcgui.Dialog().ok(
            "Kodi-AI Setup", _redacted_err("Could not save settings", e),
        )
        return

    # 9. + 10. Cross-process nudge + refresh display labels.
    _refresh_pairing_labels(bot_username)
    _nudge_service()

    # 11. Final instruction.
    xbmcgui.Dialog().ok(
        "Almost done",
        (f"Open your bot @{bot_username} in Telegram and tap Start "
         f"(or send /start to it) to finish pairing."),
    )


def setup_manual() -> None:
    """No-phone / no-relay fallback: type the bot token on the TV, validate it
    via getMe, store it, generate the setup_secret, nudge the service to start
    T3, and tell the user to finish in Telegram. The OpenRouter key + mode are
    collected later by the bot's DM flow (after /start), same as before."""
    token = xbmcgui.Dialog().input(
        "Paste bot token (from @BotFather)",
    )
    token = (token or "").strip()
    if not token:
        return

    # Validate via getMe.
    try:
        resp = requests.get(
            f"https://api.telegram.org/bot{token}/getMe",
            timeout=_HTTP_TIMEOUT,
        )
        body = resp.json()
    except Exception as e:
        # Redact: the Telegram URL embeds the token in the exception repr.
        xbmc.log(
            f"[service.kodi.ai] {_redacted_err('manual getMe error', e)}",
            xbmc.LOGWARNING,
        )
        xbmcgui.Dialog().ok(
            "Kodi-AI Setup",
            "Could not reach Telegram. Check your connection and try again.",
        )
        return

    if not isinstance(body, dict) or not body.get("ok"):
        xbmcgui.Dialog().ok(
            "Kodi-AI Setup",
            "That bot token did not validate. Re-copy it from @BotFather.",
        )
        return

    username = (body.get("result") or {}).get("username") or ""

    # Store token + generate the pairing secret.
    try:
        secrets.set_secret("bot_token", token)
        tg_auth.generate_setup_secret()
        if username:
            settings.set_string("bot_username", username)
    except Exception as e:
        xbmcgui.Dialog().ok(
            "Kodi-AI Setup", _redacted_err("Could not save token", e),
        )
        return

    _refresh_pairing_labels(username)
    _nudge_service()

    secret = tg_auth.current_setup_secret() or ""
    if username:
        msg = (
            f"Bot @{username} verified.\n\n"
            f"In Telegram, open @{username} and send:\n"
            f"[B]/start {secret}[/B]\n\n"
            f"The bot will then ask for your OpenRouter key + mode."
        )
    else:
        msg = (
            f"Bot verified.\n\n"
            f"In Telegram, send to your bot:\n[B]/start {secret}[/B]\n\n"
            f"The bot will then ask for your OpenRouter key + mode."
        )
    xbmcgui.Dialog().ok("Almost done", msg)


def reset_bot() -> None:
    """Confirm + clear allowlist + generate a new setup secret. Wired from
    settings.xml (Configure -> Telegram -> Reset bot owner)."""
    if xbmcgui.Dialog().yesno(
        "Reset Bot Owner",
        "Clear allowlist + generate a new setup secret?\n\nThis cannot be undone.",
    ):
        new_secret = tg_auth.reset_bot_owner()
        # Also refresh the pairing_command label so the user sees the new
        # secret in Configure right away.
        try:
            username = settings.get_string("bot_username", "") or ""
            if username and not username.startswith("("):
                settings.set_string(
                    "pairing_command",
                    f"/start {new_secret} to @{username}",
                )
            else:
                settings.set_string("pairing_command", f"/start {new_secret}")
        except Exception:
            pass
        xbmcgui.Dialog().ok(
            "Reset",
            f"New secret: [COLOR {COLOR_ACCENT}][B]{new_secret}[/B][/COLOR]\n\n"
            f"Configure -> Telegram now shows the new pairing command.",
        )


def main() -> None:
    action = sys.argv[1] if len(sys.argv) > 1 else ""
    if action == "setup_via_phone":
        setup_via_phone()
    elif action == "setup_manual":
        setup_manual()
    elif action == "reset_bot":
        reset_bot()
    else:
        show_status_panel()


if __name__ == "__main__":
    main()
