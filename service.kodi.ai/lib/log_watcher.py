"""T2 LogPoll body — tail special://logpath/kodi.log and enqueue
LogIncident objects to work_queue.

Initial implementation: poll + read + parse + quiescence (basic, 3s fixed
window). Adaptive cadence, 3-signal rotation, burst-mode, trace-continuation,
per-tool-boundary buffer evaluation, boot post-mortem added in Tasks 4.5–4.7.

Spec: §1.4, §3.1.
"""
from __future__ import annotations
import os
import re
import time
from datetime import datetime, timezone

import xbmcvfs

from .concurrency import (
    abort_event, work_queue, enqueue, LogIncident,
    coalesce_lock, active_cluster_ids, active_calls,
)
from . import prefilter, state_paths


# Kodi log format (typical): "<ts> <level> <[addon]> <message>"
# Pragmatic regex — Kodi's exact format varies by version; capture what we need.
_LINE_RE = re.compile(
    r"^(?:\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d+\s+)?"
    r"(?P<level>DEBUG|INFO|NOTICE|WARNING|ERROR|FATAL|SEVERE)\s*"
    r"(?:<general>|<[A-Z]+>)?\s*"
    r"(?:(?:\[(?P<addon>[a-zA-Z0-9._-]+)\])\s*)?"
    r"(?P<body>.*)$"
)


PER_TICK_CAP = 1_048_576  # 1 MB
IDLE_TICKS_THRESHOLD = 40  # ~30s @ 750ms


class LogWatcher:
    def __init__(self, *, poll_active_ms: int = 750, poll_idle_ms: int = 2500,
                 quiescence_window_s: float = 3.0):
        self.poll_active_ms = poll_active_ms
        self.poll_idle_ms = poll_idle_ms
        self.quiescence_window_s = quiescence_window_s
        self._last_offset = 0
        self._last_inode: int | None = None
        self._first_line_ts_cache: str | None = None
        self._open_clusters: dict[str, dict] = {}  # cluster_id → {lines, first_seen, last_seen, addon}
        self._ticks_since_growth = 0

    def _peek_first_line(self, path: str) -> str | None:
        try:
            with open(path, "rb") as f:
                return f.readline().decode("utf-8", errors="replace")
        except OSError:
            return None

    def _detect_rotation(self, path: str, size: int) -> bool:
        """3 signals: size shrink, inode change, first-line timestamp regression."""
        # Signal 1: size shrunk
        if size < self._last_offset:
            return True
        # Signal 2: inode changed (if available on this FS)
        try:
            st = os.stat(path)
            ino = getattr(st, "st_ino", None)
            if ino is not None and self._last_inode is not None and ino != self._last_inode:
                self._last_inode = ino
                return True
            if ino is not None:
                self._last_inode = ino
        except OSError:
            pass
        # Signal 3: first-line timestamp regression (only when we've read before)
        if self._last_offset > 0:
            first = self._peek_first_line(path)
            if first and self._first_line_ts_cache and first != self._first_line_ts_cache:
                # Heuristic: if file's first line changed, rotation likely
                self._first_line_ts_cache = first
                return True
            if first and self._first_line_ts_cache is None:
                self._first_line_ts_cache = first
        return False

    def _reopen(self, path: str) -> None:
        self._last_offset = 0
        try:
            self._last_inode = getattr(os.stat(path), "st_ino", None)
        except OSError:
            self._last_inode = None
        self._first_line_ts_cache = self._peek_first_line(path)

    def _read_new_bytes(self) -> str:
        path = state_paths.log_path()
        if not os.path.exists(path):
            self._ticks_since_growth += 1
            return ""
        size = os.path.getsize(path)
        if self._detect_rotation(path, size):
            self._reopen(path)
            size = os.path.getsize(path)  # may be 0
        if size == self._last_offset:
            self._ticks_since_growth += 1
            return ""
        # Per-tick 1MB cap; rest read next tick (catch-up)
        end = min(size, self._last_offset + PER_TICK_CAP)
        with open(path, "rb") as f:
            f.seek(self._last_offset)
            data = f.read(end - self._last_offset)
        self._last_offset = end
        if self._first_line_ts_cache is None:
            self._first_line_ts_cache = self._peek_first_line(path)
        self._ticks_since_growth = 0
        return data.decode("utf-8", errors="replace")

    def _current_cadence_ms(self) -> int:
        return self.poll_active_ms if self._ticks_since_growth < IDLE_TICKS_THRESHOLD else self.poll_idle_ms

    def _parse_line(self, line: str) -> tuple[str, str | None, str] | None:
        """Returns (level, addon, body) or None if unparseable."""
        m = _LINE_RE.match(line)
        if not m:
            return None
        return (m.group("level"), m.group("addon"), m.group("body") or "")

    def _ingest_chunk(self, text: str) -> None:
        for line in text.splitlines():
            if not line.strip():
                continue
            # Suppress our own addon-prefixed lines (belt-and-braces)
            if "[service.kodi.ai]" in line:
                continue
            parsed = self._parse_line(line)
            if not parsed:
                continue
            level, addon, body = parsed
            if level not in ("ERROR", "FATAL", "SEVERE", "WARNING"):
                continue
            if prefilter.is_benign(body):
                continue
            # Reasoner-loop guard: drop lines during active windows whose
            # addon matches our active target_addons (refined in Task 4.7).
            if active_calls.is_active():
                targets = active_calls.get_active_target_addons()
                if targets == "ALL" or (addon and addon in targets):
                    continue  # likely our own side-effect
            cid = prefilter.cluster_id_for(body)
            now = datetime.now(timezone.utc)
            cluster = self._open_clusters.setdefault(cid, {
                "lines": [], "first_seen": now, "last_seen": now,
                "addon": addon, "level": level, "occurrences": 0,
            })
            cluster["lines"].append(line)
            cluster["last_seen"] = now
            cluster["occurrences"] += 1

    def _close_expired_clusters(self) -> None:
        now = datetime.now(timezone.utc)
        expired: list[str] = []
        for cid, c in list(self._open_clusters.items()):
            age = (now - c["last_seen"]).total_seconds()
            if age >= self.quiescence_window_s:
                expired.append(cid)
        for cid in expired:
            c = self._open_clusters.pop(cid)
            with coalesce_lock:
                if cid in active_cluster_ids:
                    continue  # already enqueued; coalesce
                active_cluster_ids.add(cid)
            try:
                enqueue(LogIncident(
                    cluster_id=cid,
                    first_seen=c["first_seen"], last_seen=c["last_seen"],
                    occurrences=c["occurrences"], raw_lines=c["lines"],
                    severity_hint=c["level"], likely_addon=c["addon"],
                    likely_action=None, backdated=False,
                    from_previous_session=False, triage_deferred=True,
                ))
            except Exception:
                # work_queue.Full or similar — drop counter handled in Task 4.7
                pass

    def run(self) -> None:
        # Wait for service to finish startup before tailing
        from .concurrency import startup_complete_event
        startup_complete_event.wait()
        while not abort_event.is_set():
            chunk = self._read_new_bytes()
            if chunk:
                self._ingest_chunk(chunk)
            self._close_expired_clusters()
            cadence_ms = self._current_cadence_ms()
            if abort_event.wait(cadence_ms / 1000.0):
                return
