"""Kodi-AI UI entry point. Invoked via RunScript(default.py [, action]).

Actions:
  (none)            → status panel with action menu
  setup_via_phone   → phone-driven setup (QR + local HTTP server)  ← preferred
  setup_wizard      → fallback 4-step TV-keyboard setup
  show_secret       → QR PNG + setup_secret display
  reset_bot         → confirm + clear allowlist + generate new secret

Spec: §1.14, §5.2, §7.3. Kodi-native UI only (Dialog().textviewer/select/
input/yesno/ok/notification). Estuary-skin-friendly [COLOR]/[B]/[I] tokens.
"""
from __future__ import annotations
import os
import secrets as secrets_lib
import sys
import threading
import time

_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs  # noqa: F401 (used transitively via lib.state_paths)

from lib import state_paths, settings, secrets, qr
from lib.telegram import auth as tg_auth
from lib.llm import client as llm_client


ADDON_ID = "service.kodi.ai"
_addon_path = xbmcaddon.Addon(ADDON_ID).getAddonInfo("path")


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


def _step(n: int, total: int, title: str) -> str:
    return (
        f"[COLOR {COLOR_DIM}]STEP {n} of {total}[/COLOR]"
        f"   {_h1(title)}\n{_HR}"
    )


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
            f"{_dim('— run Setup Wizard to begin')}"
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
    if username:
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
        _dim("Use the action menu below to configure or inspect this add-on.")
    )

    msg = "\n".join(lines)
    xbmcgui.Dialog().textviewer(f"{ADDON_NAME}  ·  Status", msg)

    actions = [
        "Setup Wizard" if not bot_token else "Re-run Setup Wizard",
        "Show Setup QR / Secret",
        "Reset Bot Owner",
        "View Audit Log",
        "Close",
    ]
    choice = xbmcgui.Dialog().select(f"{ADDON_NAME}  ·  Actions", actions)
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
        f"{_h1('Pair your phone')}\n"
        f"{_dim('Scan the QR with your phone, or send /start to your bot')}\n"
        f"{_HR}\n\n"
        f"{_h2('Deeplink:')}\n"
        f"[COLOR {COLOR_ACCENT}]{deeplink}[/COLOR]\n\n"
        f"{_h2('Or manually in your bot chat:')}\n"
        f"[B][COLOR {COLOR_ACCENT}]/start {setup_secret}[/COLOR][/B]\n\n"
        f"{_dim('QR image saved to:')}\n{qr_path}"
    )
    xbmcgui.Dialog().ok(f"{ADDON_NAME}  ·  Pair", msg)
    if qr_written:
        try:
            os.remove(qr_path)
        except OSError:
            pass


def setup_wizard() -> None:
    """4-step guided setup: OpenRouter key → Telegram bot → pair → mode."""
    d = xbmcgui.Dialog()
    TITLE = f"{ADDON_NAME}  ·  Setup"

    # Welcome — one brief screen, then straight into Step 1.
    if not d.yesno(
        TITLE,
        f"{_h1('Set up Kodi-AI')}\n"
        f"{_dim('4 quick steps. ~2 minutes.')}\n{_HR}\n\n"
        f"   {_BULLET} OpenRouter API key  {_dim('(AI access)')}\n"
        f"   {_BULLET} Telegram bot        {_dim('(notifications)')}\n"
        f"   {_BULLET} Pair your phone\n"
        f"   {_BULLET} Pick agent mode\n",
        yeslabel="Begin",
        nolabel="Cancel",
    ):
        return

    # ──────────────────────────────────────────────────────────────────
    # STEP 1 — OpenRouter (single screen, then input)
    # ──────────────────────────────────────────────────────────────────
    d.ok(
        TITLE,
        f"{_step(1, 4, 'OpenRouter API Key')}\n\n"
        f"OpenRouter is a single gateway to GPT / Claude / Gemini.\n"
        f"Typical cost: [B]$1–5/month[/B] for normal use.\n\n"
        f"{_h2('On your phone:')}\n"
        f"   {_BULLET} Open [B]openrouter.ai[/B] → Sign in\n"
        f"   {_BULLET} Profile → [B]Credits[/B] → add [B]$5[/B]\n"
        f"   {_BULLET} Profile → [B]Keys[/B] → [B]Create Key[/B] → copy it\n\n"
        f"{_dim('Press OK to paste it.')}",
    )
    current_key = secrets.get_secret("openrouter_key") or ""
    new_key = d.input(
        "OpenRouter API Key  (sk-or-...)",
        defaultt=current_key,
        type=xbmcgui.INPUT_ALPHANUM,
    )
    if not new_key:
        d.ok(TITLE, f"{_dim('Setup cancelled — no API key entered.')}")
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
            ADDON_NAME, f"[COLOR {COLOR_OK}]✓ OpenRouter key valid[/COLOR]",
            time=2000,
        )
    except llm_client.LLMAuthError:
        d.ok(
            TITLE,
            f"[COLOR {COLOR_ERROR}][B]Invalid API key.[/B][/COLOR]\n\n"
            f"Get a new one at [B]openrouter.ai/keys[/B] and re-run the wizard.",
        )
        return
    except llm_client.LLMNoCreditError:
        d.ok(
            TITLE,
            f"[COLOR {COLOR_WARN}][B]No credit on your OpenRouter account.[/B][/COLOR]\n\n"
            f"Add credit at [B]openrouter.ai/credits[/B] and re-run the wizard.",
        )
        return
    except Exception as e:
        if not d.yesno(
            TITLE,
            f"[COLOR {COLOR_WARN}]Preflight error:[/COLOR] {e}\n\n"
            f"{_dim('Continue anyway? Setup can finish offline; the key will be retested at runtime.')}",
            yeslabel="Continue",
            nolabel="Cancel",
        ):
            return

    # ──────────────────────────────────────────────────────────────────
    # STEP 2 — Telegram bot (single screen, then input)
    # ──────────────────────────────────────────────────────────────────
    d.ok(
        TITLE,
        f"{_step(2, 4, 'Telegram Bot')}\n\n"
        f"You'll create [B]your own[/B] Telegram bot — Kodi-AI talks through it.\n\n"
        f"{_h2('In Telegram, message [B]@BotFather[/B]:')}\n"
        f"   {_BULLET} Send [B]/newbot[/B] → pick a name + username (must end in [B]bot[/B])\n"
        f"   {_BULLET} Copy the [B]token[/B] BotFather sends back ([I]digits:letters[/I])\n"
        f"   {_BULLET} Send [B]/setprivacy[/B] → pick your bot → [B]Disable[/B] {_dim('(REQUIRED)')}\n\n"
        f"{_dim('No Telegram? Install it free from your app store first.')}\n"
        f"{_dim('Press OK to paste the token.')}",
    )
    bot_token = d.input(
        "Telegram bot_token  (paste from BotFather)",
        defaultt=secrets.get_secret("bot_token") or "",
        type=xbmcgui.INPUT_ALPHANUM,
    )
    if not bot_token:
        d.ok(TITLE, f"{_dim('Setup cancelled — no bot token entered.')}")
        return
    secrets.set_secret("bot_token", bot_token)
    d.notification(ADDON_NAME, "Validating bot...", time=2000)
    try:
        from lib.telegram.bot import TelegramBot
        bot = TelegramBot(bot_token)
        me = bot.get_me()
        if not me.get("ok"):
            d.ok(
                TITLE,
                f"[COLOR {COLOR_ERROR}][B]Bot token invalid.[/B][/COLOR]\n\n"
                f"{_dim(str(me))}\n\n"
                f"Re-run the wizard with a fresh token from BotFather.",
            )
            return
        username = me.get("result", {}).get("username", "")
        settings.set_string("bot_username", username)
        d.notification(
            ADDON_NAME,
            f"[COLOR {COLOR_OK}]✓ @{username} verified[/COLOR]",
            time=2500,
        )
    except Exception as e:
        d.ok(
            TITLE,
            f"[COLOR {COLOR_ERROR}][B]Bot validation failed.[/B][/COLOR]\n\n{e}",
        )
        return

    # ──────────────────────────────────────────────────────────────────
    # STEP 3 — Pair
    # ──────────────────────────────────────────────────────────────────
    tg_auth.generate_setup_secret()  # ensure secret exists; show_secret() reads it
    show_secret()  # displays QR + deeplink + /start command in one screen
    setup_secret = tg_auth.current_setup_secret() or ""
    if d.yesno(
        TITLE,
        f"{_step(3, 4, 'Pair your phone')}\n\n"
        f"Have you sent [B]/start {setup_secret}[/B] to your bot?\n\n"
        f"{_dim('Yes → wait up to 60s for pairing.  Skip → pair later from the menu.')}",
        yeslabel="I have sent it",
        nolabel="Skip for now",
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
                ADDON_NAME,
                f"[COLOR {COLOR_OK}]✓ Paired successfully[/COLOR]",
                time=2500,
            )
        else:
            d.ok(
                TITLE,
                f"[COLOR {COLOR_WARN}][B]Pair timeout.[/B][/COLOR]\n\n"
                f"No incoming /start within 60s.\n\n"
                f"{_dim('You can pair later from the main menu: ')}"
                f"[B]Show Setup QR / Secret[/B]",
            )

    # ──────────────────────────────────────────────────────────────────
    # STEP 4 — Mode (single select, no intro screen)
    # ──────────────────────────────────────────────────────────────────
    mode_choice = d.select(
        f"Step 4 of 4  —  How should the agent apply fixes?",
        [
            "Auto      —  apply safe fixes automatically  (recommended)",
            "Manual    —  ask via Telegram before every fix",
        ],
    )
    if mode_choice == 0:
        settings.set_string("mode", "auto")
    elif mode_choice == 1:
        settings.set_string("mode", "manual")

    # ──────────────────────────────────────────────────────────────────
    # STEP 5 — Done
    # ──────────────────────────────────────────────────────────────────
    paired_ok = bool(tg_auth.chat_allowlist())
    pair_status = (
        f"[COLOR {COLOR_OK}]paired[/COLOR]"
        if paired_ok
        else f"[COLOR {COLOR_WARN}]not paired[/COLOR]"
    )
    d.ok(
        TITLE,
        f"[COLOR {COLOR_OK}][B]✓ Setup complete[/B][/COLOR]\n{_HR}\n\n"
        f"   {_BULLET} OpenRouter:  [COLOR {COLOR_OK}]configured[/COLOR]\n"
        f"   {_BULLET} Telegram:    [B]@{settings.get_string('bot_username') or '?'}[/B]   {pair_status}\n"
        f"   {_BULLET} Mode:        [B]{settings.get_string('mode') or 'auto'}[/B]\n\n"
        f"{_dim('Restart Kodi to start the service now, or it will start on next launch.')}",
    )


def setup_via_phone() -> None:
    """Phone-driven setup: TV shows QR + status, phone does all input.

    Architecture:
      1. Detect LAN IP (xbmc.getIPAddress → UDP-connect fallback).
      2. Reserve a port (8088..8099 preferred, else OS-assigned).
      3. Generate a 128-bit session token.
      4. Render the setup URL as a QR PNG → write to .qr/ in profile.
      5. Start the local HTTP server.
      6. Open the SetupWindow (modal); its polling thread mirrors progress.
      7. After dialog dismisses (auto-close on pair, or user Cancel),
         shut down the server + clean up the QR file.
    """
    from lib import setup_ip, setup_server, setup_window  # lazy import

    lan_ip = setup_ip._get_lan_ip()
    if not lan_ip:
        xbmcgui.Dialog().ok(
            "Kodi-AI Setup",
            "Could not detect your LAN IP.\n\n"
            "Make sure your Shield is on WiFi or Ethernet, then "
            "use [B]Manual setup (TV keyboard)[/B] from settings.",
        )
        return

    # Reserve port, then immediately close so the server can re-bind it.
    s, port = setup_server._bind_port()
    s.close()

    session_token = secrets_lib.token_urlsafe(16)
    url = f"http://{lan_ip}:{port}/setup?token={session_token}"

    # Render QR + write to profile/.qr/ — atomic + sweep stale (>1h old) files.
    qr_dir = state_paths.profile_path(".qr")
    try:
        os.makedirs(qr_dir, exist_ok=True)
    except OSError:
        pass
    now = time.time()
    try:
        for fn in os.listdir(qr_dir):
            if fn.startswith("kodi-ai-qr-") and fn.endswith(".png"):
                fp = os.path.join(qr_dir, fn)
                try:
                    if now - os.path.getmtime(fp) > 3600:
                        os.remove(fp)
                except OSError:
                    pass
    except OSError:
        pass
    qr_path = os.path.join(qr_dir, f"kodi-ai-qr-{session_token[:8]}.png")
    try:
        png = qr.qr_png(url, module_pixel_size=10, ecc_level="M")
        state_paths.atomic_write(qr_path, png)
    except Exception as e:
        xbmcgui.Dialog().ok(
            "Kodi-AI Setup",
            f"Could not generate QR code: {e}\n\n"
            "Use [B]Manual setup (TV keyboard)[/B] from settings.",
        )
        return

    server = setup_server.SetupHTTPServer(
        ("0.0.0.0", port),
        setup_server.SetupHandler,
        session_token=session_token,
        lan_ip=lan_ip,
        port=port,
    )
    server_thread = threading.Thread(
        target=server.serve_forever, daemon=True, name="kodi-ai-setup-http",
    )
    server_thread.start()
    try:
        window = setup_window.SetupWindow(
            "Setup.xml", _addon_path, "Default", "720p",
            qr_path=qr_path,
            url=url,
            session_token=session_token,
            lan_ip=lan_ip,
            port=port,
        )
        window.doModal()
        del window  # break the reference so Kodi releases the native window
    finally:
        try:
            server.shutdown()
        except Exception:
            pass
        server_thread.join(timeout=3)
        try:
            server.server_close()
        except Exception:
            pass
        try:
            os.remove(qr_path)
        except OSError:
            pass

    if secrets.get_secret("openrouter_key") and secrets.get_secret("bot_token"):
        xbmcgui.Dialog().notification(
            ADDON_NAME, "Setup complete", time=3000,
        )


def main() -> None:
    action = sys.argv[1] if len(sys.argv) > 1 else ""
    if action == "setup_via_phone":
        setup_via_phone()
    elif action == "setup_wizard":
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
