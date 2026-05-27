"""Unit tests for lib.health — heartbeat + clean shutdown + crash detection.

Spec §7.4. Uses xbmcvfs sys.modules patching with state_paths re-bind to
isolate tmp_path between tests.
"""
from __future__ import annotations
import os
import sys
import time
import pytest
from unittest import mock


@pytest.fixture(autouse=True)
def setup(tmp_path, monkeypatch):
    fake = mock.MagicMock()
    fake.translatePath.side_effect = lambda p: str(tmp_path / p.replace("special://", ""))
    fake.mkdirs.side_effect = lambda p: os.makedirs(fake.translatePath(p), exist_ok=True) or True
    monkeypatch.setitem(sys.modules, "xbmcvfs", fake)
    # Re-bind already-imported state_paths to this test's fake.
    if "lib.state_paths" in sys.modules:
        monkeypatch.setattr(sys.modules["lib.state_paths"], "xbmcvfs", fake)
    from lib import state_paths
    state_paths.ensure_dirs()
    yield


def test_heartbeat_updates_last_alive():
    from lib import health
    health.heartbeat()
    blob = health.get_state()
    assert "last_alive_ts" in blob
    assert "crash_free_since" in blob
    # crash_free_since seeded to last_alive_ts on first heartbeat
    assert blob["crash_free_since"] == blob["last_alive_ts"]
    prev_alive = blob["last_alive_ts"]
    time.sleep(0.01)
    health.heartbeat()
    blob2 = health.get_state()
    assert blob2["last_alive_ts"] >= prev_alive
    # crash_free_since unchanged on subsequent heartbeats
    assert blob2["crash_free_since"] == blob["crash_free_since"]


def test_record_clean_shutdown():
    from lib import health
    health.heartbeat()
    health.record_clean_shutdown()
    blob = health.get_state()
    assert "last_clean_shutdown_ts" in blob
    assert blob["last_clean_shutdown_ts"] > 0


def test_record_telegram_rt_ok():
    from lib import health
    health.record_telegram_rt_ok()
    blob = health.get_state()
    assert "telegram_last_rt_ok_ts" in blob
    assert blob["telegram_last_rt_ok_ts"] > 0


def test_record_allowlist_populated():
    from lib import health
    health.record_allowlist_populated()
    blob = health.get_state()
    assert "allowlist_populated_at" in blob


def test_boot_detect_clean_shutdown():
    """If last_clean_shutdown_ts - last_alive_ts is within heartbeat
    interval + grace, treat as clean shutdown — preserve crash_free_since.
    """
    from lib import health
    now = time.time()
    blob = {
        "last_alive_ts": now - 60,
        "last_clean_shutdown_ts": now - 30,  # delta 30s, well within 5min+30s grace
        "crash_free_since": now - 3600,
    }
    health._persist(blob)
    health.boot_detect_and_update_crash_free_since()
    out = health.get_state()
    # No crash inferred → crash_free_since preserved
    assert out["crash_free_since"] == now - 3600


def test_boot_detect_crash_inferred():
    """If delta exceeds heartbeat + grace, treat as crash — reset
    crash_free_since to now.
    """
    from lib import health
    now = time.time()
    # delta = 1 hour ago alive, never shut down clean → crash
    blob = {
        "last_alive_ts": now - 3600,
        "last_clean_shutdown_ts": None,
        "crash_free_since": now - 7200,
    }
    health._persist(blob)
    health.boot_detect_and_update_crash_free_since()
    out = health.get_state()
    # Crash inferred → crash_free_since reset to ~now
    assert out["crash_free_since"] >= now - 1
    assert out["crash_free_since"] <= now + 5
    # last_alive_ts also updated to ~now
    assert out["last_alive_ts"] >= now - 1
