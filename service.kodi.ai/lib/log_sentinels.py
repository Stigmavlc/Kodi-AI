"""Audit-only sentinel markers written via xbmc.log at LOGINFO.

NOT used for cross-thread synchronization (xbmc.log is buffered/async; the
in-memory ActiveCalls is the synchronization primitive — see lib/concurrency.py
and spec §1.3).

Sentinels appear in kodi.log for forensic debugging only. parse_sentinel()
is used by lib/log_watcher.py's boot post-mortem to detect dangling
sessions in kodi.old.log.

Spec: §1.3, §5.6.
"""
from __future__ import annotations
import re
import xbmc

_RE = re.compile(r"^\[service\.kodi\.ai\] reason-(start|end) ([a-z0-9]+)$")


def reason_start(session_id: str) -> None:
    xbmc.log(f"[service.kodi.ai] reason-start {session_id}", xbmc.LOGINFO)


def reason_end(session_id: str) -> None:
    xbmc.log(f"[service.kodi.ai] reason-end {session_id}", xbmc.LOGINFO)


def parse_sentinel(line: str) -> tuple[str, str] | None:
    """Returns ('start' | 'end', session_id) or None if not a sentinel."""
    m = _RE.match(line.rstrip())
    if not m:
        return None
    return (m.group(1), m.group(2))
