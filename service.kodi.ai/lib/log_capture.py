"""Captures stdlib logging + sys.stderr/sys.stdout writes from libraries
(requests, urllib3, anthropic SDK if used, etc.) and forwards to xbmc.log
with our [service.kodi.ai] prefix.

Thread-local recursion guard prevents handler->xbmc.log->handler loops.
1s dedup window collapses library retry-loop spam.

KNOWN LIMITATION (documented in spec §5.9): native C extensions writing
directly to fd 2 (lxml, cryptography errors) bypass sys.stderr wrapper.
Optional os.dup2 fd 2 -> pipe -> reader-thread fix deferred to V2.

Spec: §5.9.
"""
from __future__ import annotations
import logging
import sys
import threading
import time

import xbmc

_PREFIX = "[service.kodi.ai] "
_in_handler = threading.local()
_DEDUP_WINDOW_S = 1.0
_recent: dict[str, float] = {}
_recent_lock = threading.Lock()


def _should_emit(msg: str) -> bool:
    """Returns False if msg was emitted < 1s ago (dedup)."""
    now = time.monotonic()
    with _recent_lock:
        last = _recent.get(msg)
        if last is not None and (now - last) < _DEDUP_WINDOW_S:
            return False
        _recent[msg] = now
        # Garbage collect entries older than 5s
        if len(_recent) > 100:
            cutoff = now - 5.0
            for k in [k for k, t in _recent.items() if t < cutoff]:
                del _recent[k]
    return True


class _XbmcLogHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        if getattr(_in_handler, "value", False):
            return  # recursion guard
        _in_handler.value = True
        try:
            try:
                msg = self.format(record)
            except Exception:
                return
            level = self._map_level(record.levelno)
            for line in msg.splitlines():
                if not line.strip():
                    continue
                full = _PREFIX + line
                if _should_emit(full):
                    xbmc.log(full, level)
        finally:
            _in_handler.value = False

    @staticmethod
    def _map_level(levelno: int) -> int:
        if levelno >= logging.ERROR: return xbmc.LOGERROR
        if levelno >= logging.WARNING: return getattr(xbmc, "LOGWARNING", 2)
        if levelno >= logging.INFO: return xbmc.LOGINFO
        return getattr(xbmc, "LOGDEBUG", 0)


class _StreamRedirect:
    """Wraps sys.stderr / sys.stdout — buffers until newline, then emits one xbmc.log."""
    def __init__(self, level: int):
        self._buf = ""
        self._level = level
        self._lock = threading.Lock()
    def write(self, text: str) -> int:
        if not isinstance(text, str):
            text = text.decode("utf-8", errors="replace") if isinstance(text, (bytes, bytearray)) else str(text)
        with self._lock:
            self._buf += text
            while "\n" in self._buf:
                line, _, rest = self._buf.partition("\n")
                self._buf = rest
                if not line.strip():
                    continue
                full = _PREFIX + line
                if getattr(_in_handler, "value", False):
                    continue
                _in_handler.value = True
                try:
                    if _should_emit(full):
                        xbmc.log(full, self._level)
                finally:
                    _in_handler.value = False
        return len(text)
    def flush(self): pass
    def isatty(self): return False


_orig_stderr = None
_orig_stdout = None
_handler: _XbmcLogHandler | None = None


def install(verbose: bool = False) -> None:
    """Install handler + stream redirects. Idempotent."""
    global _handler, _orig_stderr, _orig_stdout
    if _handler is not None:
        return
    _handler = _XbmcLogHandler()
    _handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    _handler.setFormatter(logging.Formatter("%(name)s [%(levelname)s] %(message)s"))
    root = logging.getLogger()
    root.addHandler(_handler)
    if root.level > logging.INFO:
        root.setLevel(logging.INFO)
    _orig_stderr = sys.stderr
    _orig_stdout = sys.stdout
    sys.stderr = _StreamRedirect(xbmc.LOGERROR)
    sys.stdout = _StreamRedirect(xbmc.LOGINFO)


def uninstall() -> None:
    """Restore original stderr/stdout + remove handler. Used in tests."""
    global _handler, _orig_stderr, _orig_stdout
    if _handler is None:
        return
    logging.getLogger().removeHandler(_handler)
    _handler = None
    if _orig_stderr is not None:
        sys.stderr = _orig_stderr
    if _orig_stdout is not None:
        sys.stdout = _orig_stdout
    _orig_stderr = None
    _orig_stdout = None
    with _recent_lock:
        _recent.clear()
