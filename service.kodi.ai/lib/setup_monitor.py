"""KodiAiMonitor — extends xbmc.Monitor with onSettingsChanged() override.

When the user edits any setting in the Configure dialog (v0.3.0 inline-setup
flow uses this to detect the user typing a fresh bot_token), Kodi invokes
onSettingsChanged() on every registered xbmc.Monitor subclass.

We pivot off this single hook to:
  1. Invalidate the in-memory settings cache.
  2. Detect bot_token changes (validate via Telegram getMe, copy to secrets.json,
     clear plaintext from Kodi settings, start T3 on demand).
  3. Refresh derived display fields (status_display, pairing_command).

This module is intentionally tiny: the heavy work happens on T4 via the
SettingsChanged work-queue item. onSettingsChanged() runs on Kodi's GUI
thread and MUST return fast.

Spec: v0.3.0 settings-inline setup pivot.
"""
from __future__ import annotations
import itertools
import threading
import time

import xbmc

from .concurrency import SettingsChanged, work_queue


class KodiAiMonitor(xbmc.Monitor):
    """xbmc.Monitor subclass — relays onSettingsChanged() to T4 as a
    SettingsChanged work item.

    Constructed exactly once in service.py. Kodi will keep the reference
    and call onSettingsChanged() on any settings dialog OK/apply.
    """

    # Module-level counter, used as the PriorityQueue tie-break (lower wins).
    # Defined here because we don't share enqueue() — we bypass the
    # priority-table API to use put_nowait() so onSettingsChanged() can
    # return immediately if the queue is full (transient state, the next
    # settings edit will trigger another notification anyway).
    _seq = itertools.count()

    def __init__(self):
        super().__init__()
        self._lock = threading.Lock()

    def onSettingsChanged(self) -> None:  # noqa: N802 — Kodi API method name
        """Kodi calls this on GUI thread after settings dialog OK/apply."""
        # Best-effort enqueue. The queue is bounded (maxsize=500); if it's
        # full, dropping is safe because the user's next settings edit
        # will re-trigger this. We never block the GUI thread.
        try:
            work_queue.put_nowait(
                (30, next(self._seq), SettingsChanged())
            )
        except Exception:
            # queue.Full or import failure — both must not crash GUI thread.
            pass
