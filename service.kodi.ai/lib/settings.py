"""xbmcaddon settings wrapper with in-memory cache.

Kodi's settings API returns strings always; we provide typed accessors.
Cache invalidated explicitly (e.g. on onSettingsChanged or via /status command)."""
from __future__ import annotations
import threading
import xbmcaddon

ADDON_ID = "service.kodi.ai"

_cache: dict[str, str] = {}
_lock = threading.Lock()


def _addon():
    # xbmcaddon.Addon() must be called fresh each time when not cached
    return xbmcaddon.Addon(ADDON_ID)


def get_string(key: str, default: str = "") -> str:
    with _lock:
        if key not in _cache:
            try:
                _cache[key] = _addon().getSetting(key) or ""
            except Exception:
                _cache[key] = ""
        val = _cache[key]
    return val if val else default


def get_bool(key: str, default: bool = False) -> bool:
    raw = get_string(key, default="").lower()
    if raw in ("true", "1", "yes"):
        return True
    if raw in ("false", "0", "no"):
        return False
    return default


def get_int(key: str, default: int = 0) -> int:
    try:
        return int(get_string(key, default=str(default)))
    except (ValueError, TypeError):
        return default


def get_float(key: str, default: float = 0.0) -> float:
    try:
        return float(get_string(key, default=str(default)))
    except (ValueError, TypeError):
        return default


def set_string(key: str, value: str) -> None:
    with _lock:
        _addon().setSetting(key, value)
        _cache[key] = value


def set_float(key: str, value: float) -> None:
    """Persist a float setting. Kodi settings are strings, so store the str
    form and keep the cache consistent with what a subsequent get_float reads."""
    set_string(key, str(value))


def invalidate_cache() -> None:
    with _lock:
        _cache.clear()
