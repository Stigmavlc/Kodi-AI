# service.kodi.ai/lib/health.py
"""Heartbeat + crash detection + crash_free_since.

Schema: {last_alive_ts, crash_free_since, telegram_last_rt_ok_ts,
allowlist_populated_at, last_clean_shutdown_ts}.

Clean shutdown if last_clean_shutdown_ts - last_alive_ts <= 5min + 30s grace.

Spec: §7.4.
"""
from __future__ import annotations
import json
import os
import time
from . import state_paths


HEARTBEAT_INTERVAL_S = 300.0
CLEAN_SHUTDOWN_GRACE_S = 30.0


def _path():
    return state_paths.profile_path("health.json")


def _load():
    if not os.path.exists(_path()):
        return {}
    try:
        with open(_path()) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _persist(blob):
    state_paths.atomic_write(_path(), json.dumps(blob).encode("utf-8"))


def heartbeat():
    blob = _load()
    blob["last_alive_ts"] = time.time()
    if "crash_free_since" not in blob:
        blob["crash_free_since"] = blob["last_alive_ts"]
    _persist(blob)


def record_clean_shutdown():
    blob = _load()
    blob["last_clean_shutdown_ts"] = time.time()
    _persist(blob)


def record_telegram_rt_ok():
    blob = _load()
    blob["telegram_last_rt_ok_ts"] = time.time()
    _persist(blob)


def record_allowlist_populated():
    blob = _load()
    blob["allowlist_populated_at"] = time.time()
    _persist(blob)


def boot_detect_and_update_crash_free_since():
    blob = _load()
    last_alive = blob.get("last_alive_ts", 0.0)
    last_shutdown = blob.get("last_clean_shutdown_ts")
    now = time.time()
    if last_shutdown is None or (last_shutdown - last_alive) > (HEARTBEAT_INTERVAL_S + CLEAN_SHUTDOWN_GRACE_S):
        blob["crash_free_since"] = now
    blob["last_alive_ts"] = now
    _persist(blob)
    return blob


def get_state():
    return _load()
