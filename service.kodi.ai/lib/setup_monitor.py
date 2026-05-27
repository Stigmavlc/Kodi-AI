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

B4 — Re-entrancy guard (`_suppress_event`):
  The T4 handler responds to SettingsChanged by writing derived display
  fields back into Kodi settings via setSetting (status_display,
  bot_username, pairing_command). Each setSetting triggers a fresh
  onSettingsChanged callback on the GUI thread, which would re-enqueue
  another SettingsChanged work item, which T4 would then process — a
  self-amplifying flood that pegs the work queue with redundant
  validation passes and (in pathological cases) loops.

  The cleanest fix is a module-level threading.Event that the handler
  SETS while it's actively writing back derived fields and CLEARS when
  done. onSettingsChanged checks the flag and short-circuits if set,
  preserving the user's actual edits (which happen outside the handler's
  active window) but suppressing the cascade.

  threading.Event is thread-safe (GIL + atomic set/clear/is_set), so a
  global flag works correctly across the GUI thread (which checks) and
  T4 (which sets/clears).

Spec: v0.3.0 settings-inline setup pivot.
"""
from __future__ import annotations
import itertools
import threading
import time

import xbmc

from .concurrency import SettingsChanged, work_queue


# B4 — Module-level re-entrancy flag. The T4 settings-changed handler
# SETS this while it's writing derived display fields back into Kodi
# settings via setSetting, and CLEARS it when done. KodiAiMonitor
# checks it on every onSettingsChanged callback and short-circuits if
# set, breaking the self-triggered onSettingsChanged cascade.
_suppress_event = threading.Event()


def suppress_settings_changed() -> "_SuppressContext":
    """Context manager: SETs _suppress_event for the duration of the
    `with` block, then CLEARs it. Used by the T4 handler when writing
    derived display fields so the resulting onSettingsChanged callbacks
    don't recursively enqueue more SettingsChanged work items.

    Nesting is safe (no-op semantics: nested entries don't re-set, and
    only the outermost exit clears) — but the only call site is the
    settings-changed handler which never nests, so we keep the
    implementation flat.
    """
    return _SuppressContext()


class _SuppressContext:
    """Context manager for suppress_settings_changed()."""

    def __enter__(self):
        _suppress_event.set()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        _suppress_event.clear()
        return False  # don't swallow exceptions


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
        # B4 — Skip self-triggered events. T4 holds _suppress_event while
        # it writes derived display fields; those writes generate
        # onSettingsChanged callbacks that would otherwise re-enqueue
        # more SettingsChanged items and cause a self-amplifying flood.
        if _suppress_event.is_set():
            return
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
