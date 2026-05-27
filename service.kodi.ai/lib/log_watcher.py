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
    coalesce_lock, active_cluster_ids, active_calls, drop_counter,
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

BURST_QUEUE_THRESHOLD = int(0.8 * 500)  # 80% of work_queue maxsize
BURST_LAG_TICKS = 2
BOOT_SCAN_CHUNK = 256 * 1024  # 256 KB backward chunks
BOOT_SCAN_MAX_BYTES_LARGE_FILE = 2 * 1024 * 1024
LARGE_FILE_THRESHOLD = 50 * 1024 * 1024


class LogWatcher:
    def __init__(self, *, poll_active_ms: int = 750, poll_idle_ms: int = 2500,
                 quiescence_window_s: float = 3.0,
                 buffer_max_lines: int = 5000,
                 buffer_max_bytes: int = 5 * 1024 * 1024):
        self.poll_active_ms = poll_active_ms
        self.poll_idle_ms = poll_idle_ms
        self.quiescence_window_s = quiescence_window_s
        self._last_offset = 0
        self._last_inode: int | None = None
        self._first_line_ts_cache: str | None = None
        self._open_clusters: dict[str, dict] = {}  # cluster_id → {lines, first_seen, last_seen, addon}
        self._ticks_since_growth = 0
        # Per-tool-boundary buffer (Task 4.6-REVISED, spec §1.3)
        self.buffer_max_lines = buffer_max_lines
        self.buffer_max_bytes = buffer_max_bytes
        self._window_buffer: list[tuple[datetime, str, str | None, str, str]] = []
        # tuple: (ts, raw_line, addon, level, body)
        self._window_buffer_bytes = 0
        self._was_active_last_tick = False
        # Burst-mode tracking (Task 4.7-REVISED)
        self._lag_streak = 0
        self._last_error_cluster_id: str | None = None
        self._last_error_addon: str | None = None

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
            # Reasoner-loop guard (Task 4.6-REVISED, spec §1.3): during active
            # windows, BUFFER the line for per-tool-boundary post-window
            # evaluation (do NOT discard at ingest time — foreign-addon
            # errors must still surface as new incidents).
            if active_calls.is_active():
                self._buffer_line(raw_line=line, addon=addon, level=level, body=body)
                continue
            cid = prefilter.cluster_id_for(body)
            now = datetime.now(timezone.utc)
            cluster = self._open_clusters.setdefault(cid, {
                "lines": [], "first_seen": now, "last_seen": now,
                "addon": addon, "level": level, "occurrences": 0,
            })
            cluster["lines"].append(line)
            cluster["last_seen"] = now
            cluster["occurrences"] += 1

    def _buffer_line(self, raw_line: str, addon: str | None, level: str, body: str) -> None:
        """Buffer a line that arrived during an active reasoner window.
        Per spec §1.3, post-window evaluation decides surface vs. discard."""
        line_bytes = len(raw_line.encode("utf-8"))
        # Overflow handling: drop oldest until under cap; emit synthetic if dropped
        dropped_any = False
        while (len(self._window_buffer) >= self.buffer_max_lines
               or self._window_buffer_bytes + line_bytes > self.buffer_max_bytes):
            if not self._window_buffer:
                break
            _, old_raw, *_ = self._window_buffer.pop(0)
            self._window_buffer_bytes -= len(old_raw.encode("utf-8"))
            dropped_any = True
        if dropped_any:
            self._emit_overrun_synthetic()
        self._window_buffer.append(
            (datetime.now(timezone.utc), raw_line, addon, level, body)
        )
        self._window_buffer_bytes += line_bytes

    def _emit_overrun_synthetic(self) -> None:
        """Emit a synthetic 'buffer overrun' LogIncident so the operator can
        see we silently dropped post-window-eval candidates."""
        now = datetime.now(timezone.utc)
        try:
            enqueue(LogIncident(
                cluster_id=f"buf_overrun_{int(now.timestamp())}",
                first_seen=now, last_seen=now, occurrences=1,
                raw_lines=["post-window eval skipped: buffer overrun (5MB/5000-line cap)"],
                severity_hint="ERROR", likely_addon=None, likely_action=None,
                backdated=False, from_previous_session=False, triage_deferred=True,
            ))
        except Exception:
            drop_counter.inc()

    def _evaluate_buffer_post_window(self) -> None:
        """Evaluate buffered lines per spec §1.3 per-tool-boundary rule.
        Uses active_calls.last_window_targets() to identify which addons
        are "ours" (currently-active tools + lingers within last 5s):
          - target-addon line  → drop (our side-effect)
          - foreign-addon line → surface as new LogIncident

        Runs every tick (post-close). Foreign-addon errors surface
        promptly even while we're mid-fix on a different addon. Buffer
        is fully drained on each call (idempotent).
        """
        if not self._window_buffer:
            return
        recent_targets = active_calls.last_window_targets()
        clusters: dict[str, dict] = {}
        for ts, raw, addon, level, body in self._window_buffer:
            if recent_targets == "ALL" or (addon and addon in recent_targets):
                continue  # target-addon line → discard
            cid = prefilter.cluster_id_for(body)
            c = clusters.setdefault(cid, {
                "lines": [], "first": ts, "last": ts,
                "addon": addon, "level": level,
            })
            c["lines"].append(raw)
            c["last"] = ts
        for cid, c in clusters.items():
            try:
                enqueue(LogIncident(
                    cluster_id=cid, first_seen=c["first"], last_seen=c["last"],
                    occurrences=len(c["lines"]), raw_lines=c["lines"],
                    severity_hint=c["level"], likely_addon=c["addon"],
                    likely_action=None, backdated=False,
                    from_previous_session=False, triage_deferred=True,
                ))
            except Exception:
                drop_counter.inc()
        self._window_buffer.clear()
        self._window_buffer_bytes = 0

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
        # Per-tool-boundary buffer eval runs every tick (spec §1.3)
        self._evaluate_buffer_post_window()

    def _maybe_enter_burst_mode_and_read(self) -> bool:
        """If queue >=80% full AND lag growing 2 ticks -> skip-to-tail.
        Returns True if burst mode entered."""
        qsize = work_queue.qsize()
        if qsize >= BURST_QUEUE_THRESHOLD:
            self._lag_streak += 1
        else:
            self._lag_streak = 0
            return False
        if self._lag_streak < BURST_LAG_TICKS:
            return False
        # Burst mode: read last 1MB, count ERRORs by addon in skipped region
        path = state_paths.log_path()
        try:
            size = os.path.getsize(path)
        except OSError:
            return False
        skipped_start = self._last_offset
        skipped_end = max(self._last_offset, size - PER_TICK_CAP)
        # Count ERRORs across the full burst region (skipped + tail-to-read) so
        # the synthetic incident reflects the entire burst window, not just the
        # lost portion. The "X MB skipped" message still refers to the skipped
        # bytes only — counts span the whole burst for operator usefulness.
        counts: dict[str, int] = {}
        if size > skipped_start:
            with open(path, "rb") as f:
                f.seek(skipped_start)
                buf = b""
                remaining = size - skipped_start
                while remaining > 0:
                    chunk = f.read(min(64 * 1024, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    buf += chunk
                    while b"\n" in buf:
                        line_b, _, buf = buf.partition(b"\n")
                        line = line_b.decode("utf-8", errors="replace")
                        parsed = self._parse_line(line)
                        if parsed and parsed[0] in ("ERROR", "FATAL"):
                            addon = parsed[1] or "<unknown>"
                            counts[addon] = counts.get(addon, 0) + 1
        # Read tail 1MB and ingest normally
        self._last_offset = max(skipped_end, self._last_offset)
        skip_mb = (skipped_end - skipped_start) / (1024 * 1024)
        synth = (
            f"log burst, {skip_mb:.1f} MB skipped; counts: "
            + ", ".join(f"{k}: {v} ERR" for k, v in counts.items())
        )
        try:
            now = datetime.now(timezone.utc)
            enqueue(LogIncident(
                cluster_id=f"burst_{int(now.timestamp())}",
                first_seen=now, last_seen=now, occurrences=1,
                raw_lines=[synth], severity_hint="ERROR",
                likely_addon=None, likely_action=None, backdated=False,
                from_previous_session=False, triage_deferred=True,
            ))
        except Exception:
            drop_counter.inc()
        # Resume normal read
        chunk = self._read_new_bytes()
        if chunk:
            self._ingest_chunk(chunk)
        # Reset lag streak so burst-mode is a one-shot relief, not per-tick repeater.
        # Spec §1.4: "Resume normal polling next tick".
        self._lag_streak = 0
        return True

    def boot_post_mortem(self) -> None:
        """Scan kodi.old.log backward for sentinel boundaries + emit backdated
        incidents (per spec §1.4). Skip if file absent or fresh first boot.
        Uses per-session state machine (round-2 fix H7) for dangling-session
        suppression."""
        from . import log_sentinels
        path = state_paths.old_log_path()
        if not os.path.exists(path):
            # Spec §1.4: log INFO when kodi.old.log absent (fresh first boot).
            try:
                import xbmc
                xbmc.log("[service.kodi.ai] boot_post_mortem: kodi.old.log absent, skipping",
                         xbmc.LOGINFO)
            except Exception:
                pass  # xbmc not available in non-Kodi environments
            return
        size = os.path.getsize(path)
        cap = BOOT_SCAN_MAX_BYTES_LARGE_FILE if size >= LARGE_FILE_THRESHOLD else size
        # Read backward in chunks until first sentinel boundary found OR cap reached
        read_so_far = 0
        chunks: list[bytes] = []
        with open(path, "rb") as f:
            pos = size
            while read_so_far < cap and pos > 0:
                chunk_size = min(BOOT_SCAN_CHUNK, pos, cap - read_so_far)
                pos -= chunk_size
                f.seek(pos)
                chunks.append(f.read(chunk_size))
                read_so_far += chunk_size
                if b"[service.kodi.ai] reason-" in chunks[-1]:
                    break
        chunks.reverse()
        tail = b"".join(chunks).decode("utf-8", errors="replace")
        lines = tail.splitlines()
        # Build open_sessions set from tail (sessions started without end)
        open_sessions: set[str] = set()
        for line in lines:
            s = log_sentinels.parse_sentinel(line)
            if s is None:
                continue
            kind, sid = s
            if kind == "start":
                open_sessions.add(sid)
            elif kind == "end":
                open_sessions.discard(sid)
        # Per-session state machine (4.7-REVISED H7 fix)
        suppress_lines: set[int] = set()
        currently_open: set[str] = set()
        # Load tool_history signatures from sessions/*.json for tool-history-match
        tool_history_signatures: set[str] = set()
        try:
            from . import reasoner_state
            for sid in reasoner_state.list_all():
                st = reasoner_state.load(sid)
                if st is None:
                    continue
                for tool_entry in (getattr(st, "tool_history", None) or []):
                    sig = tool_entry.get("output_signature") if isinstance(tool_entry, dict) else None
                    if sig:
                        tool_history_signatures.add(sig)
        except Exception:
            pass  # reasoner_state not yet implemented (Task 5.2)
        for i, line in enumerate(lines):
            s = log_sentinels.parse_sentinel(line)
            if s:
                kind, sid = s
                if kind == "start" and sid in open_sessions:
                    currently_open.add(sid)
                elif kind == "end":
                    currently_open.discard(sid)
                continue
            # Suppress this line ONLY IF inside an open session AND
            # (addon-prefix is ours OR signature matches a recorded tool call)
            if currently_open:
                if "[service.kodi.ai]" in line:
                    suppress_lines.add(i)
                else:
                    sig = prefilter.cluster_id_for(line)
                    if sig in tool_history_signatures:
                        suppress_lines.add(i)
        # Emit non-suppressed ERROR/FATAL lines as backdated incidents
        for i, line in enumerate(lines):
            if i in suppress_lines:
                continue
            parsed = self._parse_line(line)
            if not parsed or parsed[0] not in ("ERROR", "FATAL", "SEVERE"):
                continue
            level, addon, body = parsed
            if prefilter.is_benign(body):
                continue
            cid = prefilter.cluster_id_for(body)
            now = datetime.now(timezone.utc)
            try:
                enqueue(LogIncident(
                    cluster_id=cid, first_seen=now, last_seen=now, occurrences=1,
                    raw_lines=[line], severity_hint=level, likely_addon=addon,
                    likely_action=None, backdated=True,
                    from_previous_session=True, triage_deferred=True,
                ))
            except Exception:
                drop_counter.inc()

    def run(self) -> None:
        # Wait for service to finish startup before tailing
        from .concurrency import startup_complete_event
        startup_complete_event.wait()
        while not abort_event.is_set():
            # Burst-mode check first (spec §1.4): if queue >=80% full and
            # lag-streak threshold reached, skip-to-tail + emit synthetic.
            # Burst path handles its own read+ingest internally.
            if not self._maybe_enter_burst_mode_and_read():
                chunk = self._read_new_bytes()
                if chunk:
                    self._ingest_chunk(chunk)
            self._close_expired_clusters()  # also runs buffer eval (spec §1.3)
            cadence_ms = self._current_cadence_ms()
            if abort_event.wait(cadence_ms / 1000.0):
                return
