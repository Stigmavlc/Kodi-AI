"""Synchronous notifier — called inline by T4 (NOT a thread).

send_message_with_retry(chat_id, text, ...) — 3-retry exp backoff (1,2,4s)
with abort_event.wait between attempts. Shutdown short-path: if
abort_event.is_set() at start → single attempt with timeout=(2,3).
Returns success bool + retries count.

Kodi toast fallback via xbmcgui.Dialog().notification on persistent failure.

Spec: §1.7, §3.4, §5.7.
"""
from __future__ import annotations
import requests
import xbmcgui
from .concurrency import abort_event


def send_message_with_retry(bot, chat_id: int, text: str, **kwargs) -> tuple[bool, int]:
    """Returns (ok, retries_made)."""
    shutdown = abort_event.is_set()
    backoffs = [1.0, 2.0, 4.0] if not shutdown else [0.0]
    timeout = (2, 3) if shutdown else (3, 10)
    retries = 0
    for delay in backoffs:
        if delay > 0 and abort_event.wait(delay):
            return False, retries
        retries += 1
        try:
            res = bot.send_message(chat_id, text, **kwargs)
            if res.get("ok"):
                return True, retries
        except Exception:
            pass
        if shutdown:
            break
    return False, retries


def kodi_toast(title: str, message: str) -> None:
    try:
        xbmcgui.Dialog().notification(title, message, time=5000)
    except Exception:
        pass


def notify_or_toast(bot, chat_id: int, text: str, *, toast_title: str = "Kodi-AI",
                    **kwargs) -> bool:
    ok, _ = send_message_with_retry(bot, chat_id, text, **kwargs)
    if not ok:
        # Strip HTML for toast (Kodi toast doesn't parse HTML)
        plain = text.replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", "")
        kodi_toast(toast_title, plain[:200])
    return ok
