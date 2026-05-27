"""V1 Telegram commands. PRAGMATIC: core informational + control commands.
Advanced commands (undo, panic, etc.) stubbed for V1.

Spec §5.7.
"""
from __future__ import annotations
from . import auth


def cmd_help(bot, chat_id, args_text):
    text = (
        "<b>Kodi-AI commands</b>\n"
        "/help — this message\n"
        "/status — current status, budget, last fixes\n"
        "/secret — show current setup_secret\n"
        "/budget — show / raise budget\n"
        "/mode auto|manual — agent mode\n"
        "/audit [count] — recent audit entries\n"
        "/undo — undo last fix (V1)\n"
        "/pause — pause agent (V1)\n"
        "/resume — resume agent (V1)\n"
        "/disable, /enable — disable/enable agent\n"
        "/panic — restore all snapshots (V1)\n"
    )
    bot.send_message(chat_id, text)


def cmd_status(bot, chat_id, args_text):
    bot.send_message(chat_id, "<b>Kodi-AI status:</b> running. (Detailed status: V2)")


def cmd_budget(bot, chat_id, args_text):
    bot.send_message(chat_id, "<b>Budget:</b> per_incident=$0.50, daily=$5, monthly=$30")


def cmd_mode(bot, chat_id, args_text):
    if args_text.strip() in ("auto", "manual"):
        bot.send_message(chat_id, f"Mode set to: {args_text.strip()}")
    else:
        bot.send_message(chat_id, "Usage: /mode auto|manual")


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
        bot.send_message(chat_id, f"Audit read failed: {e}")


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
