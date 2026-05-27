"""In-memory secret cache backed by secrets.json (POSIX, 0600 best-effort).

Secrets in V1: openrouter_key, bot_token, setup_secret, optional provider-direct
keys. Same trust model as Trakt/RD/AllDebrid keys live in their addons —
documented in spec §5.1.

Access pattern: T4 (worker, reasoner) + T3 (telegram bot_token) read.
T2 (log watcher) MUST NOT read secrets. Module-level guard enforces nothing,
but reviewer checks it.

Spec: §5.1.
"""
from __future__ import annotations
import json
import os
import stat
import threading
from . import state_paths

_LOCK = threading.Lock()
_cache: dict[str, str] | None = None


def _path() -> str:
    return state_paths.profile_path("secrets.json")


def _load() -> dict[str, str]:
    global _cache
    if _cache is not None:
        return _cache
    p = _path()
    if not os.path.exists(p):
        _cache = {}
        return _cache
    try:
        with open(p, "r", encoding="utf-8") as f:
            _cache = json.load(f) or {}
    except (json.JSONDecodeError, OSError):
        _cache = {}
    return _cache


def _persist(data: dict[str, str]) -> None:
    blob = json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    state_paths.atomic_write(_path(), blob)
    # Best-effort 0600. On Android scoped storage this may not actually take effect.
    try:
        os.chmod(_path(), stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass  # documented limitation


def get_secret(key: str) -> str | None:
    with _LOCK:
        return _load().get(key)


def set_secret(key: str, value: str) -> None:
    with _LOCK:
        data = dict(_load())
        data[key] = value
        _persist(data)
        global _cache
        _cache = data


def delete_secret(key: str) -> None:
    with _LOCK:
        data = dict(_load())
        if key in data:
            del data[key]
            _persist(data)
            global _cache
            _cache = data


def invalidate_cache() -> None:
    """Force re-read on next access. Used for tests + post-process-restart."""
    with _LOCK:
        global _cache
        _cache = None
