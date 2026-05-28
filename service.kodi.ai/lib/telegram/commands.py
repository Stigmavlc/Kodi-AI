"""V1 Telegram commands. PRAGMATIC: core informational + control commands.
Advanced commands (undo, panic, etc.) stubbed for V1.

These handlers read/write REAL state:
- secrets (configured yes/no — never the values),
- settings (mode + budget caps),
- the persisted BudgetGuard counters (today's / month's spend),
- the audit log tail (best-effort "last action").

They deliberately avoid importing service.py (which imports lib.telegram,
so the reverse import would be a cycle). State is read straight from the
underlying modules instead. The one cross-module concern — making a /mode
change take effect on a running service without a restart — is handled
inside service._get_router(), which rebuilds the cached router whenever the
persisted mode no longer matches; this handler just persists the new mode.

Spec §5.7.
"""
from __future__ import annotations
import math
from . import auth
from . import formatters as fmt
from .. import settings, secrets, redactor

# M3 — budget cap defaults. These same three numbers also live in
# service.py::_get_budget (named DEFAULT_*_CAP_USD there). They are intentionally
# duplicated rather than shared from a common module: commands.py deliberately
# avoids importing service.py (that would be an import cycle — service.py imports
# lib.telegram), and lib.settings is a low-level accessor that shouldn't carry
# budget policy. Naming them on both sides removes the bare-literal drift risk.
DEFAULT_PER_INCIDENT_CAP_USD = 0.50
DEFAULT_DAILY_CAP_USD = 5.0
DEFAULT_MONTHLY_CAP_USD = 30.0


def cmd_help(bot, chat_id, args_text):
    text = (
        "<b>Kodi-AI commands</b>\n"
        "/help — this message\n"
        "/status — current status, config, budget, last action\n"
        "/secret — show current setup_secret\n"
        "/budget — show budget caps + spend\n"
        "/mode auto|manual — set + persist agent mode\n"
        "/audit [count] — recent audit entries\n"
        "/undo — undo last fix (V1)\n"
        "/pause — pause agent (V1)\n"
        "/resume — resume agent (V1)\n"
        "/disable, /enable — disable/enable agent (V1)\n"
        "/panic — restore all snapshots (V1)\n"
    )
    bot.send_message(chat_id, text)


def _load_budget():
    """Build a BudgetGuard from the configured caps and load the persisted
    counters. Returns the guard, or None if it can't be read (caller treats
    that as 'no spend data')."""
    try:
        from ..llm.budget import BudgetGuard
        bg = BudgetGuard(
            per_incident_cap=settings.get_float("per_incident_cap_usd", DEFAULT_PER_INCIDENT_CAP_USD),
            daily_cap=settings.get_float("daily_cap_usd", DEFAULT_DAILY_CAP_USD),
            monthly_cap=settings.get_float("monthly_cap_usd", DEFAULT_MONTHLY_CAP_USD),
        )
        bg.load()  # no-op when budget_counters.json is absent
        return bg
    except Exception:
        return None


def _last_action_line():
    """Best-effort: most recent meaningful audit entry as a short string, or
    None. Reuses the tail-read pattern from cmd_audit. Never raises."""
    try:
        from .. import state_paths
        import os, json
        path = state_paths.profile_path("audit/audit.jsonl")
        if not os.path.exists(path):
            return None
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 8192))
            tail = f.read().decode("utf-8", errors="replace")
        for line in reversed(tail.splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            event = rec.get("event", "")
            # Skip pure noise; surface actionable events.
            if event in ("heartbeat",):
                continue
            ts = rec.get("ts", "")
            detail = ""
            d = rec.get("details") or {}
            if event == "tool_call":
                detail = f" {d.get('tool_name', '')}"
            return f"{event}{detail} @ {ts}"
        return None
    except Exception:
        return None


def cmd_status(bot, chat_id, args_text):
    """Report REAL state. Never leaks secret values — only configured yes/no."""
    try:
        has_token = bool(secrets.get_secret("bot_token"))
        has_key = bool(secrets.get_secret("openrouter_key"))
        mode = settings.get_string("mode", "auto") or "auto"
        try:
            paired = len(auth.chat_allowlist())
        except Exception:
            paired = 0
        username = settings.get_string("bot_username", "") or ""

        bg = _load_budget()
        if bg is not None:
            spent_today = bg.daily_cost_usd
            daily_cap = bg.daily_cap
        else:
            spent_today = 0.0
            daily_cap = settings.get_float("daily_cap_usd", DEFAULT_DAILY_CAP_USD)

        lines = ["<b>Kodi-AI status</b>"]
        lines.append(
            f"Configured: bot token: {'yes' if has_token else 'no'}, "
            f"OpenRouter key: {'yes' if has_key else 'no'}"
        )
        if username:
            lines.append(f"Bot: @{fmt.escape_html(username)}")
        lines.append(f"Paired users: {paired}")
        lines.append(f"Mode: {fmt.escape_html(mode)}")
        lines.append(f"Spent today: ${spent_today:.2f} / ${daily_cap:.2f}")
        last = _last_action_line()
        if last:
            lines.append(f"Last action: {fmt.escape_html(last)}")
        bot.send_message(chat_id, "\n".join(lines))
    except Exception as e:
        # H1 — Status must always answer, but the exception may carry a secret
        # (e.g. a path or response body echoing a token/key) AND is not HTML-
        # escaped (parse_mode=HTML). Log the full detail REDACTED to kodi.log
        # for the operator, and send the user a generic message — never the raw
        # exception. Matches the redaction invariant used across service.py.
        try:
            import xbmc
            xbmc.log(
                f"[service.kodi.ai] {redactor.redact(f'cmd_status error: {e!r}')}",
                xbmc.LOGWARNING,
            )
        except Exception:
            pass
        bot.send_message(
            chat_id,
            "<b>Kodi-AI status:</b> could not read status right now, try again.",
        )


def cmd_budget(bot, chat_id, args_text):
    """Show REAL caps + spend. Optional: '/budget daily <n>' raises the daily
    cap (V1 convenience; per_incident/monthly stay UI-only)."""
    arg = (args_text or "").strip()

    # Optional: '/budget daily <n>' — set the daily cap.
    if arg:
        parts = arg.split()
        if len(parts) == 2 and parts[0].lower() == "daily":
            try:
                new_cap = float(parts[1])
            except ValueError:
                bot.send_message(chat_id, "Usage: /budget daily &lt;amount&gt;")
                return
            # H2 — float() accepts "inf"/"nan"/"-inf". `nan <= 0` is False, so a
            # bare positivity check lets NaN through and would write a garbage
            # cap that disables budget enforcement (nan comparisons in
            # pre_call_check are always False → never trips). Reject anything
            # non-finite OR non-positive before writing.
            if not math.isfinite(new_cap) or new_cap <= 0:
                bot.send_message(chat_id, "Daily cap must be a positive number.")
                return
            settings.set_float("daily_cap_usd", new_cap)
            settings.invalidate_cache()
            bot.send_message(
                chat_id,
                f"Daily cap set to ${new_cap:.2f}. "
                f"Takes effect on the next incident.",
            )
            return
        # Any other args → fall through to showing current budget.

    per_incident = settings.get_float("per_incident_cap_usd", DEFAULT_PER_INCIDENT_CAP_USD)
    daily = settings.get_float("daily_cap_usd", DEFAULT_DAILY_CAP_USD)
    monthly = settings.get_float("monthly_cap_usd", DEFAULT_MONTHLY_CAP_USD)

    bg = _load_budget()
    spent_today = bg.daily_cost_usd if bg is not None else 0.0
    spent_month = bg.monthly_cost_usd if bg is not None else 0.0

    text = (
        "<b>Budget</b>\n"
        f"Per incident cap: ${per_incident:.2f}\n"
        f"Today: ${spent_today:.2f} / ${daily:.2f}\n"
        f"This month: ${spent_month:.2f} / ${monthly:.2f}"
    )
    bot.send_message(chat_id, text)


def cmd_mode(bot, chat_id, args_text):
    """Persist the agent mode so it survives + applies to the next incident.

    service._get_router() re-reads `mode` and rebuilds its cached router when
    the value changes, so no Kodi restart is needed for the new mode to take
    effect on the next incident handled by the running service."""
    value = (args_text or "").strip().lower()
    if value in ("auto", "manual"):
        settings.set_string("mode", value)
        settings.invalidate_cache()
        bot.send_message(
            chat_id,
            f"Mode set to {value}. Takes effect on the next incident.",
        )
    else:
        current = settings.get_string("mode", "auto") or "auto"
        bot.send_message(
            chat_id,
            f"Usage: /mode auto|manual\nCurrent: {fmt.escape_html(current)}",
        )


def cmd_secret(bot, chat_id, args_text):
    s = auth.current_setup_secret()
    if s:
        bot.send_message(chat_id, f"<b>Current setup_secret:</b> <code>{s}</code>")
    else:
        bot.send_message(chat_id, "No active setup_secret. Use Kodi UI to regenerate.")


def cmd_audit(bot, chat_id, args_text):
    try:
        from .. import state_paths
        import os, json
        path = state_paths.profile_path("audit/audit.jsonl")
        if not os.path.exists(path):
            bot.send_message(chat_id, "No audit log.")
            return
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 8192))
            tail = f.read().decode("utf-8", errors="replace")
        lines = tail.splitlines()[-10:]
        bot.send_message(chat_id, f"<pre>{chr(10).join(lines)}</pre>")
    except Exception as e:
        # H1 — same class of leak as cmd_status: redact to log, generic to user.
        try:
            import xbmc
            xbmc.log(
                f"[service.kodi.ai] {redactor.redact(f'cmd_audit error: {e!r}')}",
                xbmc.LOGWARNING,
            )
        except Exception:
            pass
        bot.send_message(chat_id, "Audit read failed, try again.")


def cmd_stub(bot, chat_id, args_text, command_name):
    bot.send_message(chat_id, f"/{command_name}: not yet implemented in V1.")


COMMANDS = {
    "help": cmd_help, "status": cmd_status, "budget": cmd_budget,
    "mode": cmd_mode, "secret": cmd_secret, "audit": cmd_audit,
    "undo": lambda b, c, a: cmd_stub(b, c, a, "undo"),
    "pause": lambda b, c, a: cmd_stub(b, c, a, "pause"),
    "resume": lambda b, c, a: cmd_stub(b, c, a, "resume"),
    "disable": lambda b, c, a: cmd_stub(b, c, a, "disable"),
    "enable": lambda b, c, a: cmd_stub(b, c, a, "enable"),
    "panic": lambda b, c, a: cmd_stub(b, c, a, "panic"),
    "invite": lambda b, c, a: cmd_stub(b, c, a, "invite"),
    "retry-notify": lambda b, c, a: cmd_stub(b, c, a, "retry-notify"),
}


def dispatch(bot, chat_id, text):
    """Parse '/foo arg1 arg2' and route to command. Returns True if handled."""
    if not text.startswith("/"):
        return False
    parts = text[1:].split(None, 1)
    name = parts[0]
    args_text = parts[1] if len(parts) > 1 else ""
    handler = COMMANDS.get(name)
    if handler:
        handler(bot, chat_id, args_text)
        return True
    return False
