# tests/integration/test_log_watcher_buffer_eval.py
import os
import time
import pytest
from datetime import datetime, timezone
from tests.integration.fakes import fake_xbmcvfs


@pytest.mark.integration
def test_foreign_addon_line_surfaces_during_active_window():
    """When ActiveCalls targets {plugin.video.foo}, a line from
    plugin.video.bar MUST be enqueued (not discarded)."""
    from lib import log_watcher, concurrency
    from lib.concurrency import active_calls
    # Drain queue
    while not concurrency.work_queue.empty():
        concurrency.work_queue.get_nowait()

    log_dir = fake_xbmcvfs.translatePath("special://logpath/")
    os.makedirs(log_dir, exist_ok=True)
    path = os.path.join(log_dir, "kodi.log")
    with open(path, "w") as f:
        f.write("INFO: startup\n")
    w = log_watcher.LogWatcher(quiescence_window_s=0.3)
    w._read_new_bytes()

    # Active tool targets foo
    active_calls.add_tool("t1", target_addons={"plugin.video.foo"})
    try:
        with open(path, "a") as f:
            # bar line is FOREIGN to t1's targets — must surface
            f.write("ERROR [plugin.video.bar]: real new issue\n")
            # foo line is OUR side-effect — must be buffered + later discarded
            f.write("ERROR [plugin.video.foo]: our side-effect\n")
        w._ingest_chunk(w._read_new_bytes())
        # Quiescence + close
        time.sleep(0.4)
        w._close_expired_clusters()
    finally:
        active_calls.schedule_remove_tool("t1", after=0.0)

    # Drain queue, classify
    found_bar = False
    found_foo = False
    while not concurrency.work_queue.empty():
        _, _, item = concurrency.work_queue.get_nowait()
        text = "\n".join(getattr(item, "raw_lines", []))
        if "bar" in text:
            found_bar = True
        if "foo" in text:
            found_foo = True
    assert found_bar, "foreign-addon line MUST surface even during active window"
    assert not found_foo, "target-addon line MUST be discarded post-window"


@pytest.mark.integration
def test_buffer_cap_overflow_emits_synthetic_incident():
    """If buffer exceeds 5MB or 5000 lines, oldest dropped + synthetic
    'post-window eval skipped: buffer overrun' incident emitted."""
    from lib import log_watcher, concurrency
    from lib.concurrency import active_calls
    while not concurrency.work_queue.empty():
        concurrency.work_queue.get_nowait()

    log_dir = fake_xbmcvfs.translatePath("special://logpath/")
    os.makedirs(log_dir, exist_ok=True)
    path = os.path.join(log_dir, "kodi.log")
    with open(path, "w") as f:
        f.write("INFO: x\n")
    w = log_watcher.LogWatcher(quiescence_window_s=0.3, buffer_max_lines=10)
    w._read_new_bytes()
    active_calls.add_tool("t1", target_addons="ALL")  # suppress ALL → forces buffer
    try:
        with open(path, "a") as f:
            for i in range(25):
                f.write(f"ERROR [plugin.video.x{i}]: msg {i}\n")
        w._ingest_chunk(w._read_new_bytes())
    finally:
        active_calls.schedule_remove_tool("t1", after=0.0)
    time.sleep(0.4)
    w._close_expired_clusters()
    saw_overrun = False
    while not concurrency.work_queue.empty():
        _, _, item = concurrency.work_queue.get_nowait()
        if "buffer overrun" in "\n".join(getattr(item, "raw_lines", [])):
            saw_overrun = True
    assert saw_overrun


@pytest.mark.integration
def test_target_addon_line_discarded_after_linger():
    """After ActiveCalls.is_active() goes False (linger expires), buffered
    target-addon lines are evaluated and discarded."""
    from lib import log_watcher, concurrency
    from lib.concurrency import active_calls
    while not concurrency.work_queue.empty():
        concurrency.work_queue.get_nowait()
    log_dir = fake_xbmcvfs.translatePath("special://logpath/")
    os.makedirs(log_dir, exist_ok=True)
    path = os.path.join(log_dir, "kodi.log")
    with open(path, "w") as f:
        f.write("INFO: x\n")
    w = log_watcher.LogWatcher(quiescence_window_s=0.3)
    w._read_new_bytes()
    active_calls.add_tool("t1", target_addons={"plugin.video.foo"})
    with open(path, "a") as f:
        f.write("ERROR [plugin.video.foo]: side effect\n")
    w._ingest_chunk(w._read_new_bytes())
    active_calls.schedule_remove_tool("t1", after=0.05)
    time.sleep(0.5)  # past linger AND quiescence
    w._close_expired_clusters()
    w._evaluate_buffer_post_window()
    found = False
    while not concurrency.work_queue.empty():
        _, _, item = concurrency.work_queue.get_nowait()
        if "foo" in "\n".join(getattr(item, "raw_lines", [])):
            found = True
    assert not found, "target-addon line must be discarded post-window"
