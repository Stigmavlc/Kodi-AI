"""Synchronous notifier — called inline by T4 (NOT a thread).

send_message_with_retry(chat_id, text, ...) — 3-retry exp backoff (1,2,4s)
with abort_event.wait between attempts. Shutdown short-path: if
abort_event.is_set() at start → single attempt with timeout=(2,3).
Returns success bool + retries count.

Kodi toast fallback via xbmcgui.Dialog().notification on persistent failure.

notify_user(bot, chat_ids, telegram_text, ...) — the locked-spec primitive
(Telegram + Kodi toast). The on-screen toast ALWAYS fires first and
unconditionally (local-only operation works with no Telegram pairing); the
Telegram leg then runs best-effort per recipient. Each leg is independent: a
Telegram failure never blocks the toast (already fired) and a toast failure
never blocks Telegram.

Detect-dedupe (v0.5.0): a single root cause can emit several distinct error
signatures → several CRITICAL incidents → a flood of identical "detected"
toasts. detect_dedupe_check_and_arm() suppresses a NEW detect notification if
one fired within DETECT_DEDUPE_WINDOW_S (60s) OR while a reasoner session is
currently active (session_started/session_ended bracket the run). Resolution
messages are NEVER deduped — only the detect spam.

Spec: §1.7, §3.4, §5.7.
"""
from __future__ import annotations
import os
import threading
import time
import requests
import xbmcgui
from .concurrency import abort_event

# Toast bodies are one-liners in Kodi's corner; keep them short so the GUI
# doesn't silently clip mid-word. Telegram bodies are not subject to this.
_TOAST_MAX_LEN = 120

# Detect-dedupe window: suppress a repeat "detected" notification fired within
# this many seconds of the previous one (documented in module docstring).
DETECT_DEDUPE_WINDOW_S = 60.0


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


def _addon_icon_path() -> str:
    """Resolve service.kodi.ai/icon.png if it exists, else "" (Kodi shows its
    default). Mirrors the existence guard used by service.py's boot toast."""
    try:
        # lib/notifier.py → parent dir is the add-on root (service.kodi.ai/).
        addon_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        icon = os.path.join(addon_root, "icon.png")
        return icon if os.path.exists(icon) else ""
    except Exception:
        return ""


def _toast_body(text: str) -> str:
    """Single-line, length-capped toast body. Collapses newlines (a Kodi toast
    is one line) and truncates so the GUI doesn't clip mid-word. ASCII-only
    ellipsis ('...') per the Kodi-toast ASCII constraint."""
    body = " ".join((text or "").split())
    if len(body) > _TOAST_MAX_LEN:
        body = body[: _TOAST_MAX_LEN - 3].rstrip() + "..."
    return body


def notify_user(
    bot,
    chat_ids,
    telegram_text: str,
    toast_text: str | None = None,
    urgency: str = "medium",
) -> None:
    """Show a Kodi on-screen toast AND (best-effort) message Telegram.

    The locked-spec user-notification primitive. Behavior:
      - Toast ALWAYS fires first, unconditionally — local-only operation works
        even with no Telegram pairing. Body is `toast_text` (or `telegram_text`
        when omitted), single-lined + length-capped. sound=True only for
        urgency=="high".
      - Then Telegram: only when `bot is not None` and `chat_ids` is non-empty.
        Each recipient is sent independently inside try/except so one failing
        recipient (or Telegram being down) never blocks the others — and the
        toast already fired regardless.

    No secret leakage: callers must pass already-safe text. This function never
    interpolates raw exceptions.
    """
    # --- Leg 1: Kodi toast (unconditional, fired first) ---
    try:
        xbmcgui.Dialog().notification(
            "Kodi-AI",
            _toast_body(toast_text if toast_text is not None else telegram_text),
            icon=_addon_icon_path(),
            time=5000,
            sound=(urgency == "high"),
        )
    except Exception:
        # Toast is best-effort; a GUI failure must not block the Telegram leg.
        pass

    # --- Leg 2: Telegram (best-effort, per-recipient isolation) ---
    if bot is None or not chat_ids:
        return
    for cid in chat_ids:
        try:
            send_message_with_retry(bot, cid, telegram_text)
        except Exception:
            # One bad recipient / Telegram-down must not stop the others.
            continue


# ---- Detect-dedupe (suppresses repeat "detected" toasts; see module docstring) ----

_detect_lock = threading.Lock()
_last_detect_monotonic: float = -1e18  # far past → first detect always allowed
_active_sessions: int = 0


def detect_dedupe_check_and_arm() -> bool:
    """Return True if a NEW "detected" notification may fire right now, arming
    the window when it does. Return False (suppress) if a detect fired within
    DETECT_DEDUPE_WINDOW_S OR a reasoner session is currently active.

    Resolution notifications must NOT call this — only detect spam is deduped.
    """
    global _last_detect_monotonic
    now = time.monotonic()
    with _detect_lock:
        if _active_sessions > 0:
            return False
        if now - _last_detect_monotonic < DETECT_DEDUPE_WINDOW_S:
            return False
        _last_detect_monotonic = now
        return True


def session_started() -> None:
    """Mark a reasoner session active (suppresses detect notifications until it
    ends). Bracket each incident reasoner run with started/ended."""
    global _active_sessions
    with _detect_lock:
        _active_sessions += 1


def session_ended() -> None:
    """Mark a reasoner session finished. Never drives the counter below 0 (a
    stray extra call must not wedge dedupe into permanent suppression)."""
    global _active_sessions
    with _detect_lock:
        if _active_sessions > 0:
            _active_sessions -= 1


def _reset_detect_state_for_tests() -> None:
    """Test hook: clear the module-level dedupe state between tests."""
    global _last_detect_monotonic, _active_sessions
    with _detect_lock:
        _last_detect_monotonic = -1e18
        _active_sessions = 0
