# tests/integration/test_log_watcher_rotation.py
import os
import time
import pytest
from tests.integration.fakes import fake_xbmcvfs


@pytest.mark.integration
def test_size_shrink_detected_as_rotation(tmp_path):
    log_dir = fake_xbmcvfs.translatePath("special://logpath/")
    os.makedirs(log_dir, exist_ok=True)
    path = os.path.join(log_dir, "kodi.log")
    with open(path, "w") as f:
        f.write("INFO: line one\nINFO: line two\n")

    from lib.log_watcher import LogWatcher
    w = LogWatcher(poll_active_ms=10, poll_idle_ms=20)
    w._read_new_bytes()  # advances offset
    assert w._last_offset > 0

    # Truncate to simulate rotation
    with open(path, "w") as f:
        f.write("INFO: fresh start\n")
    chunk = w._read_new_bytes()
    assert "fresh start" in chunk
    # Last offset reset to new file size
    assert w._last_offset == len(b"INFO: fresh start\n")


@pytest.mark.integration
def test_per_tick_1mb_cap(tmp_path):
    log_dir = fake_xbmcvfs.translatePath("special://logpath/")
    os.makedirs(log_dir, exist_ok=True)
    path = os.path.join(log_dir, "kodi.log")
    # Write 3 MB
    with open(path, "w") as f:
        f.write("INFO: a\n" * 400_000)

    from lib.log_watcher import LogWatcher
    w = LogWatcher()
    chunk1 = w._read_new_bytes()
    assert len(chunk1) <= 1_048_576
    chunk2 = w._read_new_bytes()
    assert len(chunk2) > 0  # catch-up on next tick


@pytest.mark.integration
def test_adaptive_cadence_idle_after_no_growth(tmp_path):
    from lib.log_watcher import LogWatcher
    w = LogWatcher(poll_active_ms=100, poll_idle_ms=400)
    # Many ticks with no growth
    for _ in range(50):
        w._read_new_bytes()
    cadence = w._current_cadence_ms()
    assert cadence == 400  # idle
