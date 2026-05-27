"""Kodi-AI UI entry point. Invoked via RunScript(default.py [, action]).

Actions:
  (none)        → status panel with action menu
  setup_wizard  → 5-screen setup flow
  show_secret   → QR PNG + setup_secret display
  reset_bot     → confirm + clear allowlist + generate new secret

Spec: §1.14, §5.2, §7.3. Kodi-native UI only (Dialog().textviewer/select/
input/yesno/ok/notification). Estuary-skin-friendly [COLOR]/[B]/[I] tokens.
"""
from __future__ import annotations
import os
import sys
import time

_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

import xbmc
import xbmcgui
import xbmcvfs  # noqa: F401 (used transitively via lib.state_paths)

from lib import state_paths, settings, secrets, qr
from lib.telegram import auth as tg_auth
from lib.llm import client as llm_client


ADDON_NAME = "Kodi-AI"
COLOR_ACCENT = "00A2DB"
COLOR_OK = "00C853"
COLOR_WARN = "FF8800"
COLOR_ERROR = "E53935"


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

    lines = [f"[B][COLOR {COLOR_ACCENT}]{ADDON_NAME} — Status[/COLOR][/B]", ""]
    if not bot_token:
        lines.append(f"[COLOR {COLOR_WARN}]Not configured.[/COLOR] Run Setup Wizard.")
    elif not allowlist:
        lines.append(f"[COLOR {COLOR_WARN}]Bot configured but no users paired.[/COLOR]")
        if setup_secret:
            lines.append(f"Setup secret: [COLOR {COLOR_ACCENT}]{setup_secret}[/COLOR]")
    else:
        lines.append(f"[COLOR {COLOR_OK}]Active[/COLOR]  |  Users: {len(allowlist)}")
    if last_alive:
        ago = int(time.time() - last_alive)
        lines.append(f"Last heartbeat: {ago}s ago")
    if crash_free_since:
        days = max(0, int((time.time() - crash_free_since) / 86400))
        lines.append(f"Crash-free: {days}d")
    mode = settings.get_string("mode") or "auto"
    lines.append(f"Mode: [B]{mode}[/B]")
    cap_pi = settings.get_float("per_incident_cap_usd", 0.50)
    cap_d = settings.get_float("daily_cap_usd", 5.0)
    cap_m = settings.get_float("monthly_cap_usd", 30.0)
    lines.append(
        f"Budget: ${cap_pi:.2f}/incident, ${cap_d:.2f}/day, ${cap_m:.2f}/month"
    )

    msg = "\n".join(lines)
    xbmcgui.Dialog().textviewer(ADDON_NAME, msg)

    actions = [
        "Setup Wizard" if not bot_token else "Re-run Setup Wizard",
        "Show Setup QR / Secret",
        "Reset Bot Owner",
        "View Audit Log",
        "Close",
    ]
    choice = xbmcgui.Dialog().select(ADDON_NAME, actions)
    if choice == 0:
        setup_wizard()
    elif choice == 1:
        show_secret()
    elif choice == 2:
        if xbmcgui.Dialog().yesno(
            "Reset Bot Owner",
            "Clear all authorized users and generate a new setup secret?\n\n"
            "This cannot be undone.",
        ):
            new_secret = tg_auth.reset_bot_owner()
            xbmcgui.Dialog().ok(
                "Bot Owner Reset",
                f"New setup_secret:\n\n[COLOR {COLOR_ACCENT}][B]{new_secret}[/B][/COLOR]",
            )
    elif choice == 3:
        view_audit()
    # choice == 4 (Close) or -1 (cancelled): no-op


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


def show_secret() -> None:
    """Generate / display QR image + setup_secret + deeplink."""
    bot_token = secrets.get_secret("bot_token") or ""
    if not bot_token:
        xbmcgui.Dialog().ok(ADDON_NAME, "No bot configured. Run Setup Wizard first.")
        return
    setup_secret = tg_auth.current_setup_secret() or tg_auth.generate_setup_secret()
    bot_username = settings.get_string("bot_username") or ""
    if bot_username:
        deeplink = f"https://t.me/{bot_username}?start={setup_secret}"
    else:
        deeplink = f"(bot username unknown — DM your bot: /start {setup_secret})"

    qr_dir = state_paths.profile_path(".qr")
    try:
        os.makedirs(qr_dir, exist_ok=True)
    except OSError:
        pass
    qr_path = os.path.join(qr_dir, "setup.png")
    qr_written = False
    try:
        png = qr.qr_png(deeplink, module_pixel_size=10, ecc_level="H")
        with open(qr_path, "wb") as f:
            f.write(png)
        qr_written = True
    except Exception as e:
        xbmcgui.Dialog().ok(
            ADDON_NAME,
            f"QR generation failed: {e}\n\n"
            f"Setup link:\n[COLOR {COLOR_ACCENT}]{deeplink}[/COLOR]\n\n"
            f"Setup secret: [B]{setup_secret}[/B]",
        )
        return
    msg = (
        f"[B]Pair your Telegram bot[/B]\n\n"
        f"Open in Telegram or scan the QR:\n"
        f"[COLOR {COLOR_ACCENT}]{deeplink}[/COLOR]\n\n"
        f"Or manually send to your bot:\n[B]/start {setup_secret}[/B]\n\n"
        f"QR image saved at: {qr_path}"
    )
    xbmcgui.Dialog().ok(f"{ADDON_NAME} — Pair", msg)
    if qr_written:
        try:
            os.remove(qr_path)
        except OSError:
            pass


def setup_wizard() -> None:
    """5-screen guided setup: key → bot → pair → mode → done."""
    d = xbmcgui.Dialog()
    if not d.yesno(
        f"{ADDON_NAME} Setup",
        f"Welcome to [B]{ADDON_NAME}[/B]!\n\n"
        "This wizard will set up:\n"
        "  - OpenRouter API key\n"
        "  - Telegram bot\n"
        "  - Agent mode\n"
        "  - Test connection\n\nContinue?",
    ):
        return

    # 1. OpenRouter API key
    current_key = secrets.get_secret("openrouter_key") or ""
    new_key = d.input(
        "OpenRouter API Key (sk-or-...)",
        defaultt=current_key,
        type=xbmcgui.INPUT_ALPHANUM,
    )
    if not new_key:
        d.ok(ADDON_NAME, "Setup cancelled (no API key entered).")
        return
    secrets.set_secret("openrouter_key", new_key)
    d.notification(ADDON_NAME, "Testing OpenRouter key...", time=2000)
    try:
        llm_client.chat(
            api_key=new_key,
            model="google/gemini-2.0-flash-001",
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=5,
        )
        d.notification(
            ADDON_NAME, f"[COLOR {COLOR_OK}]OpenRouter valid[/COLOR]", time=2000
        )
    except llm_client.LLMAuthError:
        d.ok(
            ADDON_NAME,
            f"[COLOR {COLOR_ERROR}]Invalid API key.[/COLOR]\n\n"
            "Get one at openrouter.ai/keys then re-run the wizard.",
        )
        return
    except llm_client.LLMNoCreditError:
        d.ok(
            ADDON_NAME,
            f"[COLOR {COLOR_WARN}]No credit on OpenRouter account.[/COLOR]\n\n"
            "Add credit at openrouter.ai/credits then re-run the wizard.",
        )
        return
    except Exception as e:
        if not d.yesno(
            ADDON_NAME,
            f"[COLOR {COLOR_WARN}]Preflight error: {e}[/COLOR]\n\nContinue anyway?",
        ):
            return

    # 2. Telegram bot
    d.ok(
        ADDON_NAME,
        "Now create a Telegram bot:\n\n"
        "  1. Open Telegram, message [B]@BotFather[/B]\n"
        "  2. Send [B]/newbot[/B], follow the prompts\n"
        "  3. Copy the [B]bot_token[/B] (like 12345:ABC...)\n"
        "  4. IMPORTANT: send [B]/setprivacy[/B] then [B]Disable[/B] to BotFather\n"
        "     (so the bot can read DMs sent to it)",
    )
    bot_token = d.input(
        "Telegram bot_token",
        defaultt=secrets.get_secret("bot_token") or "",
        type=xbmcgui.INPUT_ALPHANUM,
    )
    if not bot_token:
        d.ok(ADDON_NAME, "Setup cancelled (no bot token entered).")
        return
    secrets.set_secret("bot_token", bot_token)
    d.notification(ADDON_NAME, "Validating bot...", time=2000)
    try:
        from lib.telegram.bot import TelegramBot
        bot = TelegramBot(bot_token)
        me = bot.get_me()
        if not me.get("ok"):
            d.ok(
                ADDON_NAME,
                f"[COLOR {COLOR_ERROR}]Bot token invalid:[/COLOR]\n{me}",
            )
            return
        username = me.get("result", {}).get("username", "")
        settings.set_string("bot_username", username)
        d.notification(
            ADDON_NAME, f"[COLOR {COLOR_OK}]Bot: @{username}[/COLOR]", time=2500
        )
    except Exception as e:
        d.ok(ADDON_NAME, f"[COLOR {COLOR_ERROR}]Bot validation failed: {e}[/COLOR]")
        return

    # 3. QR / pair
    setup_secret = tg_auth.generate_setup_secret()
    show_secret()
    if d.yesno(
        ADDON_NAME,
        f"Pairing displayed.\n\nIn Telegram, send to your bot:\n"
        f"[B]/start {setup_secret}[/B]\n\n"
        "Click [B]Yes[/B] once sent (we'll wait up to 60s), or [B]No[/B] to skip.",
    ):
        d.notification(ADDON_NAME, "Waiting for pairing...", time=2000)
        paired = False
        for _ in range(60):
            if tg_auth.chat_allowlist():
                paired = True
                break
            time.sleep(1)
        if paired:
            d.notification(
                ADDON_NAME, f"[COLOR {COLOR_OK}]Paired![/COLOR]", time=2500
            )
        else:
            d.ok(
                ADDON_NAME,
                f"[COLOR {COLOR_WARN}]Pair timeout.[/COLOR]\n\n"
                "Use 'Show Setup QR / Secret' from the menu later.",
            )

    # 4. Mode
    mode_choice = d.select(
        "Choose Agent Mode",
        [
            "Auto (recommended) - apply safe fixes automatically",
            "Manual - confirm each fix before applying",
        ],
    )
    if mode_choice == 0:
        settings.set_string("mode", "auto")
    elif mode_choice == 1:
        settings.set_string("mode", "manual")

    # 5. Done
    d.ok(
        ADDON_NAME,
        f"[COLOR {COLOR_OK}][B]Setup complete![/B][/COLOR]\n\n"
        f"  - OpenRouter: configured\n"
        f"  - Telegram: @{settings.get_string('bot_username') or '?'} "
        f"{'(paired)' if tg_auth.chat_allowlist() else '(not paired)'}\n"
        f"  - Mode: {settings.get_string('mode') or 'auto'}\n\n"
        f"Kodi-AI now monitors logs. Restart Kodi to start the service "
        f"(or it will start on next Kodi launch).",
    )


def main() -> None:
    action = sys.argv[1] if len(sys.argv) > 1 else ""
    if action == "setup_wizard":
        setup_wizard()
    elif action == "show_secret":
        show_secret()
    elif action == "reset_bot":
        if xbmcgui.Dialog().yesno(
            "Reset Bot Owner",
            "Clear allowlist + generate a new setup secret?\n\nThis cannot be undone.",
        ):
            new_secret = tg_auth.reset_bot_owner()
            xbmcgui.Dialog().ok(
                "Reset",
                f"New secret: [COLOR {COLOR_ACCENT}][B]{new_secret}[/B][/COLOR]",
            )
    else:
        show_status_panel()


if __name__ == "__main__":
    main()
