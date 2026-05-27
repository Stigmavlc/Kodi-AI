"""Kodi-AI UI entry point. Invoked via RunScript(default.py [, action]).

v0.3.0 settings-inline setup pivot:
  All configuration lives inline in Kodi's standard Configure dialog
  (settings.xml). default.py is now used only for two actions invoked
  from settings.xml or the addon's Program-add-ons launch:

    (none)        → status panel with action menu
    reset_bot     → confirm + clear allowlist + generate new setup_secret

The old phone-driven setup wizard (setup_via_phone, setup_wizard) and the
QR-based show_secret screen are gone in v0.3.0 because the same content
is exposed inline in the Configure dialog (pairing_command label) and the
bot DM flow handles OpenRouter key + mode selection.

Spec: §1.14, §5.2, §7.3 + v0.3.0 settings-inline setup pivot.
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

from lib import state_paths, settings, secrets
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


def reset_bot() -> None:
    """Confirm + clear allowlist + generate a new setup secret. Wired from
    settings.xml (Configure → Telegram → Reset bot owner)."""
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
            f"Configure → Telegram now shows the new pairing command.",
        )


def main() -> None:
    action = sys.argv[1] if len(sys.argv) > 1 else ""
    if action == "reset_bot":
        reset_bot()
    else:
        show_status_panel()


if __name__ == "__main__":
    main()
