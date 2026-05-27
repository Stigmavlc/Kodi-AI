"""special:// path resolution + atomic write helpers.

Wraps xbmcvfs for testability. All paths under POSIX-backed special://profile/
on Android — atomic rename verified at startup + every 50 writes (smoke probe
in .smoke/ subdir; see lib/health.py)."""
from __future__ import annotations
import os
import xbmcvfs

ADDON_ID = "service.kodi.ai"


def profile_path(relpath: str = "") -> str:
    """Returns absolute path under special://profile/addon_data/<addon>/."""
    base = xbmcvfs.translatePath(f"special://profile/addon_data/{ADDON_ID}/")
    return os.path.join(base, relpath) if relpath else base


def snapshots_path(relpath: str = "") -> str:
    """Snapshots live OUTSIDE addon_data so they survive addon reinstall."""
    base = xbmcvfs.translatePath("special://userdata/Kodi-AI-snapshots/")
    return os.path.join(base, relpath) if relpath else base


def temp_path(relpath: str = "") -> str:
    base = xbmcvfs.translatePath("special://temp/")
    return os.path.join(base, relpath) if relpath else base


def log_path() -> str:
    return xbmcvfs.translatePath("special://logpath/kodi.log")


def old_log_path() -> str:
    return xbmcvfs.translatePath("special://logpath/kodi.old.log")


def ensure_dirs() -> None:
    """Create all addon state dirs. Idempotent."""
    for sub in ("", "sessions", "audit", "recovery", ".smoke"):
        xbmcvfs.mkdirs(f"special://profile/addon_data/{ADDON_ID}/{sub}/")
    xbmcvfs.mkdirs("special://userdata/Kodi-AI-snapshots/")
    xbmcvfs.mkdirs("special://userdata/Kodi-AI-snapshots/.undone/")
    xbmcvfs.mkdirs("special://userdata/Kodi-AI-snapshots/.orphaned/")


def atomic_write(path: str, data: bytes) -> None:
    """Write bytes atomically: .tmp + fsync + rename. POSIX-backed on Android."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    tmp = path + ".tmp"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)  # atomic on POSIX


def smoke_probe_atomic_rename() -> bool:
    """Verify atomic rename works on the underlying FS. Used at startup
    and every 50 writes (see lib/health.py). Returns True if OK."""
    probe_dir = profile_path(".smoke")
    os.makedirs(probe_dir, exist_ok=True)
    probe = os.path.join(probe_dir, "probe")
    payload = os.urandom(16)
    try:
        atomic_write(probe, payload)
        with open(probe, "rb") as f:
            return f.read() == payload
    finally:
        try:
            os.remove(probe)
        except FileNotFoundError:
            pass
