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
    """5-screen guided setup: key → bot → pair → mode → done."""
    d = xbmcgui.Dialog()
    TITLE = f"{ADDON_NAME}  ·  Setup Wizard"

    # Welcome / overview
    if not d.yesno(
        TITLE,
        f"{_h1('Welcome to ' + ADDON_NAME)}\n"
        f"{_dim('AI-assisted Kodi diagnostics + auto-fix via Telegram')}\n"
        f"{_HR}\n\n"
        f"{_h2('What this wizard sets up:')}\n"
        f"   {_BULLET} OpenRouter API key   {_dim('(LLM access)')}\n"
        f"   {_BULLET} Telegram bot         {_dim('(notifications + chat)')}\n"
        f"   {_BULLET} Pair your device     {_dim('(via QR or /start)')}\n"
        f"   {_BULLET} Agent mode           {_dim('(auto / manual)')}\n"
        f"\n{_dim('Takes ~2 minutes. Continue?')}",
        yeslabel="Begin Setup",
        nolabel="Cancel",
    ):
        return

    # ──────────────────────────────────────────────────────────────────
    # STEP 1 — OpenRouter (multi-screen for clarity)
    # ──────────────────────────────────────────────────────────────────

    # 1.0 — What's OpenRouter and why we need it
    d.ok(
        TITLE,
        f"{_step(1, 5, 'OpenRouter API Key')}\n\n"
        f"{_h2('What is OpenRouter?')}\n"
        f"It's a [B]single gateway[/B] to all major AI models — GPT, Claude,\n"
        f"Gemini, etc. One API key, one bill, you pick the model.\n\n"
        f"{_h2('Why do we use it?')}\n"
        f"   {_BULLET} Kodi-AI uses cheap models for triage ([B]~$0.0001[/B] per check)\n"
        f"   {_BULLET} And a better model when actually fixing things\n"
        f"   {_BULLET} You only pay for what you use — no subscription\n"
        f"   {_BULLET} Typical month: [B]$1–5[/B] depending on how often Kodi breaks\n\n"
        f"{_dim('Press OK to see how to get a key.')}",
    )

    # 1.1 — How to sign up + get the key + add credit
    d.ok(
        TITLE,
        f"{_h1('Get your OpenRouter key')}\n{_HR}\n\n"
        f"{_h2('On your phone or computer:')}\n\n"
        f"  [B][COLOR {COLOR_ACCENT}]1.[/COLOR][/B]  Open [B]openrouter.ai[/B] in a browser\n\n"
        f"  [B][COLOR {COLOR_ACCENT}]2.[/COLOR][/B]  Click [B]Sign in[/B] (top-right)\n"
        f"      Use Google / GitHub / email — whatever's easiest\n\n"
        f"  [B][COLOR {COLOR_ACCENT}]3.[/COLOR][/B]  Click your profile (top-right) → [B]Credits[/B]\n"
        f"      Add [B]$5[/B] (covers months of use; Stripe / card)\n\n"
        f"  [B][COLOR {COLOR_ACCENT}]4.[/COLOR][/B]  Click your profile → [B]Keys[/B]\n"
        f"      Press [B]Create Key[/B], give it any name (e.g. \"Kodi\")\n"
        f"      [B]Copy the key[/B] — looks like [COLOR {COLOR_ACCENT}]sk-or-v1-abc123...[/COLOR]\n\n"
        f"  [B][COLOR {COLOR_OK}]5.[/COLOR][/B]  Press OK below and paste the key on the next screen.\n",
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
    # STEP 2 — Telegram bot (multi-screen, first-timer-friendly)
    # ──────────────────────────────────────────────────────────────────

    # 2.0 — Intro + branching for Telegram newcomers
    d.ok(
        TITLE,
        f"{_step(2, 5, 'Telegram Bot')}\n\n"
        f"Kodi-AI talks to you through [B]your own[/B] Telegram bot.\n"
        f"You'll create the bot now — it takes about 1 minute.\n\n"
        f"{_h2('Why a bot, not just a regular Telegram chat?')}\n"
        f"   {_BULLET} Bots can be controlled by code (Kodi-AI talks AS the bot)\n"
        f"   {_BULLET} The bot is [B]100% yours[/B] — only you have its token\n"
        f"   {_BULLET} No central server, no shared accounts, no spam\n",
    )

    knows_telegram = d.yesno(
        TITLE,
        f"{_h2('Quick check:')}\n\n"
        f"Have you used Telegram before, and is it installed on your phone?",
        yeslabel="Yes, ready",
        nolabel="No, help me",
    )

    # 2.1 — Install Telegram (only shown to first-timers)
    if not knows_telegram:
        d.ok(
            TITLE,
            f"{_h1('Install Telegram first')}\n{_HR}\n\n"
            f"Telegram is a free messaging app (like WhatsApp). You need it\n"
            f"to talk to your Kodi-AI bot.\n\n"
            f"{_h2('Install on your phone:')}\n"
            f"   {_BULLET} [B]iPhone:[/B] App Store → search [B]Telegram[/B] → install\n"
            f"   {_BULLET} [B]Android:[/B] Play Store → search [B]Telegram[/B] → install\n"
            f"   {_BULLET} [B]Desktop:[/B] [B]telegram.org[/B] (works too, but phone easier)\n\n"
            f"{_h2('Once installed:')}\n"
            f"   {_BULLET} Open Telegram\n"
            f"   {_BULLET} Sign up with your phone number\n"
            f"   {_BULLET} Press OK below when you're logged in",
        )

    # 2.2 — Find @BotFather
    d.ok(
        TITLE,
        f"{_h1('Find @BotFather')}\n{_HR}\n\n"
        f"[B]@BotFather[/B] is Telegram's official bot-maker. It's a special bot\n"
        f"run by Telegram itself that lets anyone create their own bot.\n\n"
        f"{_h2('Open @BotFather:')}\n"
        f"   {_BULLET} In Telegram, tap the [B]search icon[/B] (top-right magnifier)\n"
        f"   {_BULLET} Type [B]@BotFather[/B] (with the @ symbol)\n"
        f"   {_BULLET} Tap the result with the [B]blue checkmark[/B] (official)\n"
        f"   {_BULLET} Tap [B]Start[/B] (or send [B]/start[/B] if you've used it before)\n\n"
        f"{_dim('You should see a welcome message from BotFather.')}",
    )

    # 2.3 — Create the bot (step-by-step with what BotFather will ask)
    d.ok(
        TITLE,
        f"{_h1('Create your bot')}\n{_HR}\n\n"
        f"{_h2('Send these to BotFather, one at a time:')}\n\n"
        f"  [B][COLOR {COLOR_ACCENT}]1.[/COLOR][/B]  Send [B]/newbot[/B]\n"
        f"      BotFather: [I]\"Alright, a new bot. How are we going to call it?\"[/I]\n\n"
        f"  [B][COLOR {COLOR_ACCENT}]2.[/COLOR][/B]  Type a [B]display name[/B], anything you want:\n"
        f"      e.g. [I]\"My Kodi Helper\"[/I] or [I]\"Shield Watcher\"[/I]\n"
        f"      BotFather: [I]\"Good. Now let's choose a username...\"[/I]\n\n"
        f"  [B][COLOR {COLOR_ACCENT}]3.[/COLOR][/B]  Type a [B]username[/B] — must be unique and end in [B]bot[/B]:\n"
        f"      e.g. [I]\"ivan_kodi_helper_bot\"[/I] or [I]\"shieldwatcher_bot\"[/I]\n"
        f"      If taken, BotFather will tell you — just try another name.\n\n"
        f"  [B][COLOR {COLOR_ACCENT}]4.[/COLOR][/B]  BotFather replies with a long [B]TOKEN[/B] in the format:\n"
        f"      [COLOR {COLOR_ACCENT}]<10-digit ID>[/COLOR][B]:[/B][COLOR {COLOR_ACCENT}]<35 random letters/digits/_-+>[/COLOR]\n\n"
        f"  [B][COLOR {COLOR_OK}]5.[/COLOR][/B]  [B]Copy that whole token[/B] — you'll paste it on the next screen.\n",
    )

    # 2.4 — Privacy setting (critical for the bot to read your messages)
    d.ok(
        TITLE,
        f"{_h1('Disable privacy mode (REQUIRED)')}\n{_HR}\n\n"
        f"By default Telegram bots [B]can't read messages[/B] sent to them — a\n"
        f"safety feature. We need to turn that off for [I]your[/I] bot so Kodi-AI\n"
        f"can actually receive what you type.\n\n"
        f"{_h2('In your @BotFather chat:')}\n"
        f"   {_BULLET} Send [B]/setprivacy[/B]\n"
        f"   {_BULLET} BotFather: [I]\"Choose a bot...\"[/I] → tap [B]your bot[/B]\n"
        f"   {_BULLET} BotFather shows two options: tap [B]Disable[/B]\n"
        f"   {_BULLET} Confirmation: [I]\"Success! ... will receive all messages.\"[/I]\n\n"
        f"{_dim('Without this step, Kodi-AI cannot see your replies.')}",
    )

    # 2.5 — Input the token
    d.ok(
        TITLE,
        f"{_h1('Paste the bot token')}\n{_HR}\n\n"
        f"On the next screen, paste the long [B]token[/B] BotFather gave you.\n\n"
        f"{_dim('Format reminder:')}\n"
        f"   [COLOR {COLOR_ACCENT}]<10-digit ID>[/COLOR][B]:[/B][COLOR {COLOR_ACCENT}]<35-char secret>[/COLOR]\n\n"
        f"{_dim('(digits, colon, then a 35-character letters+digits+_-+ string)')}",
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
    setup_secret = tg_auth.generate_setup_secret()
    d.ok(
        TITLE,
        f"{_step(3, 5, 'Pair your phone')}\n\n"
        f"On the next screen you'll see a [B]QR code[/B] and a [B]setup secret[/B].\n\n"
        f"{_h2('To pair:')}\n"
        f"   {_BULLET} Scan the QR with your phone's camera, OR\n"
        f"   {_BULLET} Open your bot in Telegram and send:\n"
        f"     [B][COLOR {COLOR_ACCENT}]/start {setup_secret}[/COLOR][/B]\n\n"
        f"{_dim('After pairing, only your account can talk to the bot.')}",
    )
    show_secret()
    if d.yesno(
        TITLE,
        f"{_h2('Waiting for pairing...')}\n\n"
        f"Have you sent [B]/start {setup_secret}[/B] to your bot?\n\n"
        f"{_dim('Click Yes to wait up to 60s for confirmation, or Skip to do this later.')}",
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
    # STEP 4 — Mode
    # ──────────────────────────────────────────────────────────────────
    d.ok(
        TITLE,
        f"{_step(4, 5, 'Agent Mode')}\n\n"
        f"How should the agent handle fixes?\n\n"
        f"{_h2('Auto')} {_dim('(recommended)')}\n"
        f"   Safe fixes apply automatically, you get a Telegram\n"
        f"   summary. Risky ones still ask first.\n\n"
        f"{_h2('Manual')}\n"
        f"   Every fix requires Yes/No confirmation in Telegram\n"
        f"   before applying.\n",
    )
    mode_choice = d.select(
        f"{ADDON_NAME}  ·  Choose mode",
        [
            "Auto      —  apply safe fixes automatically (recommended)",
            "Manual    —  confirm every fix in Telegram",
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
        f"{_step(5, 5, 'All set')}\n\n"
        f"[COLOR {COLOR_OK}][B]✓ Setup complete![/B][/COLOR]\n\n"
        f"{_h2('Summary:')}\n"
        f"   {_BULLET} OpenRouter:   [COLOR {COLOR_OK}]configured[/COLOR]\n"
        f"   {_BULLET} Telegram:     [B]@{settings.get_string('bot_username') or '?'}[/B]   {pair_status}\n"
        f"   {_BULLET} Mode:         [B]{settings.get_string('mode') or 'auto'}[/B]\n\n"
        f"{_HR}\n"
        f"{_dim('Kodi-AI will now monitor your Kodi logs. Restart Kodi to')}\n"
        f"{_dim('start the service immediately, or it will start on next launch.')}",
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
