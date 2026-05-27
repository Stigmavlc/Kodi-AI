"""BotHolder — thread-safe TelegramBot reference + on-demand T3 startup.

In v0.2.x the TelegramBot was constructed at service boot only if bot_token
was already set, and T3 was started right then. With v0.3.0 the user
types the bot_token into Kodi settings AFTER service boot, so we need:

  1. A mutable reference T4 handlers (_handle_incident, _handle_user_msg,
     _handle_outcome, _handle_resume_work) read every time they need to
     send a Telegram message — so a token validated mid-runtime is seen
     by the next handler invocation.
  2. A way to start the T3 long-poll thread on demand (idempotent — if
     it's already running, do nothing).

Known limitation (B2, accepted for v0.3.1 — Option A):
  set_token_and_start does NOT hot-swap a running T3 thread. The
  T3 long-poll loop captures `self.token` from the original TelegramBot
  instance and will keep polling the OLD bot until the next Kodi restart.
  When called a second time with a different token after a bot has already
  been started, the holder:
    - logs a clear warning,
    - displays a toast asking the user to restart Kodi,
    - REPLACES the in-memory bot reference (so handlers that read it
      via .get() see the new bot for outgoing sends),
    - does NOT touch the running T3 thread (which still polls the old
      bot). Outgoing sends via .get() will go through the new bot; the
      old long-poll keeps running until shutdown but is harmless (it
      just receives messages destined for the old bot, which the user
      has presumably stopped using).

  This trade-off keeps the implementation simple and avoids the
  thread-restart complexity. The cost is a restart on token change,
  which is a rare event (only happens if the user regenerates the
  BotFather token, in which case they're probably already restarting
  Kodi as part of changing the secret).

  Option B (clean stop-and-restart of T3) is deferred to v0.3.2+ if
  user reports come in for the hot-swap path. Tracked in HANDOVER §7.

Spec: v0.3.0 settings-inline setup pivot, §D.
"""
from __future__ import annotations
import threading
from typing import TYPE_CHECKING

import xbmc

if TYPE_CHECKING:
    from .telegram.bot import TelegramBot


class BotHolder:
    """Holds the current TelegramBot + T3 thread reference.

    All access is mutex-protected. get() returns None if no bot is
    configured; callers must check.
    """

    def __init__(self):
        self._bot: "TelegramBot | None" = None
        self._t3: threading.Thread | None = None
        self._lock = threading.Lock()

    def get(self) -> "TelegramBot | None":
        """Return the current bot (or None if not yet configured)."""
        with self._lock:
            return self._bot

    def set_token_and_start(self, token: str) -> None:
        """Create / replace the TelegramBot for `token` and start T3 if it
        isn't already running.

        Called by T4 after onSettingsChanged() validates a new bot_token,
        and also at service boot if a token is already in secrets.json.

        Behavior matrix:
          - First call (no bot yet): create bot + start T3.
          - Subsequent call with same token: idempotent no-op.
          - Subsequent call with DIFFERENT token (token rotation):
            replace in-memory bot, surface "restart Kodi" notification,
            do NOT touch the running T3 thread (see module docstring B2).
        """
        # Defer the import to avoid an import cycle at module load
        # (telegram.bot imports concurrency which doesn't import this,
        # but keeping it lazy is the cleanest pattern).
        from .telegram import bot as telegram_bot_mod
        with self._lock:
            existing_bot = self._bot
            existing_t3 = self._t3
            existing_t3_alive = (
                existing_t3 is not None and existing_t3.is_alive()
            )
            same_token = (
                existing_bot is not None and existing_bot.token == token
            )

            if same_token and existing_t3_alive:
                # Idempotent: nothing to do.
                return

            new_bot = telegram_bot_mod.TelegramBot(token)
            self._bot = new_bot

            if not existing_t3_alive:
                # No live T3 yet (first call, or T3 has died): start a
                # fresh long-poll thread bound to the new bot.
                self._t3 = threading.Thread(
                    target=new_bot.run,
                    name="T3_TGPoll",
                    daemon=False,
                )
                self._t3.start()
                return

            # Token CHANGED and an old T3 is still running. We can't
            # safely kill that thread (long-poll request can sit for
            # ~10s on a slow network; abrupt thread kill is not a thing
            # in Python). The new bot reference is now in place for
            # outgoing sends; the user must restart Kodi to spin up a
            # T3 bound to the new token.
            xbmc.log(
                "[service.kodi.ai] BotHolder: bot token changed at "
                "runtime — long-poll thread keeps using OLD bot until "
                "Kodi restart. New bot is active for outgoing sends.",
                xbmc.LOGWARNING,
            )
            try:
                # Inline import — xbmcgui may not be importable in unit
                # tests that didn't stub it.
                import xbmcgui
                xbmcgui.Dialog().notification(
                    "Kodi-AI",
                    "Bot token updated — restart Kodi to activate",
                    time=8000,
                )
            except Exception:
                # Notification is best-effort; log is the source of truth.
                pass

    def t3_thread(self) -> threading.Thread | None:
        """Expose the T3 thread for shutdown joining."""
        with self._lock:
            return self._t3

    def clear(self) -> None:
        """Drop bot reference (used at shutdown for GC; thread itself
        observes abort_event)."""
        with self._lock:
            self._bot = None
