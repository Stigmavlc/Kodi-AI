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
  3. Safe replacement of the bot when a different token is typed (rare in
     practice but harmless — we just create a new bot; the running T3
     thread will pick up the new bot reference via get() in the next
     getUpdates iteration; the old token's outstanding long-poll request
     will quietly fail or return stale updates that we discard).

Spec: v0.3.0 settings-inline setup pivot, §D.
"""
from __future__ import annotations
import threading
from typing import TYPE_CHECKING

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
        """
        # Defer the import to avoid an import cycle at module load
        # (telegram.bot imports concurrency which doesn't import this,
        # but keeping it lazy is the cleanest pattern).
        from .telegram import bot as telegram_bot_mod
        with self._lock:
            self._bot = telegram_bot_mod.TelegramBot(token)
            if self._t3 is None or not self._t3.is_alive():
                self._t3 = threading.Thread(
                    target=self._bot.run,
                    name="T3_TGPoll",
                    daemon=False,
                )
                self._t3.start()

    def t3_thread(self) -> threading.Thread | None:
        """Expose the T3 thread for shutdown joining."""
        with self._lock:
            return self._t3

    def clear(self) -> None:
        """Drop bot reference (used at shutdown for GC; thread itself
        observes abort_event)."""
        with self._lock:
            self._bot = None
