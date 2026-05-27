# tests/integration/test_log_watcher_basic.py
import os
import time
import threading
import pytest
from tests.integration.fakes import fake_xbmcvfs


@pytest.mark.integration
def test_poll_loop_reads_new_bytes(monkeypatch):
    # Stage a log file
    log_dir = fake_xbmcvfs.translatePath("special://logpath/")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "kodi.log")
    with open(log_path, "w") as f:
        f.write("INFO: kodi started\n")

    from lib import log_watcher, concurrency
    concurrency.abort_event.clear()

    # Drain the queue first
    while not concurrency.work_queue.empty():
        concurrency.work_queue.get_nowait()

    # Run watcher in a thread with fast cadence
    watcher = log_watcher.LogWatcher(poll_active_ms=50, poll_idle_ms=200)
    t = threading.Thread(target=watcher.run, daemon=True)
    t.start()
    time.sleep(0.15)  # let it start + do one read

    # Append an ERROR line
    with open(log_path, "a") as f:
        f.write("ERROR plugin.video.seren: failed to play\n")

    # Wait for incident to be enqueued (allow quiescence wait)
    time.sleep(5.0)  # > quiescence window
    concurrency.abort_event.set()
    t.join(timeout=2.0)

    # Should have at least one LogIncident in the queue
    found = False
    while not concurrency.work_queue.empty():
        _, _, item = concurrency.work_queue.get_nowait()
        if hasattr(item, "raw_lines"):
            if any("seren" in line for line in item.raw_lines):
                found = True
                break
    assert found
