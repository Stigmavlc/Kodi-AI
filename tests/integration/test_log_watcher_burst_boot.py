# tests/integration/test_log_watcher_burst_boot.py
import os
import time
import pytest
from tests.integration.fakes import fake_xbmcvfs


@pytest.mark.integration
def test_burst_mode_emits_synthetic_incident_with_counts(tmp_path):
    from lib import log_watcher, concurrency
    while not concurrency.work_queue.empty():
        concurrency.work_queue.get_nowait()
    log_dir = fake_xbmcvfs.translatePath("special://logpath/")
    os.makedirs(log_dir, exist_ok=True)
    path = os.path.join(log_dir, "kodi.log")
    # Stage > 2MB of ERROR lines from two addons
    with open(path, "w") as f:
        for i in range(30000):
            f.write(f"ERROR [plugin.video.foo]: oops {i}\n")
        for i in range(15000):
            f.write(f"ERROR [plugin.video.bar]: nope {i}\n")
    w = log_watcher.LogWatcher()
    # Simulate burst trigger: fill the work_queue first
    from lib.concurrency import LogIncident
    from datetime import datetime, timezone
    for i in range(420):  # > 80% of 500
        concurrency.work_queue.put_nowait((10, i, LogIncident(
            cluster_id=f"x{i}", first_seen=datetime.now(timezone.utc),
            last_seen=datetime.now(timezone.utc), occurrences=1,
            raw_lines=[], severity_hint="ERROR", likely_addon=None,
            likely_action=None, backdated=False,
            from_previous_session=False, triage_deferred=True,
        )))
    # Trigger burst-mode read — needs 2 ticks above threshold to enter
    w._maybe_enter_burst_mode_and_read()  # tick 1
    w._maybe_enter_burst_mode_and_read()  # tick 2 → enters burst
    # Drain queue, look for synthetic incident
    found = False
    while not concurrency.work_queue.empty():
        _, _, item = concurrency.work_queue.get_nowait()
        if hasattr(item, "raw_lines") and any("log burst" in r for r in item.raw_lines):
            found = True
            assert "plugin.video.foo" in "\n".join(item.raw_lines)
            assert "plugin.video.bar" in "\n".join(item.raw_lines)
            break
    assert found


@pytest.mark.integration
def test_boot_post_mortem_skips_when_old_log_absent(tmp_path):
    from lib import log_watcher
    # No kodi.old.log
    w = log_watcher.LogWatcher()
    # Should not raise
    w.boot_post_mortem()


@pytest.mark.integration
def test_per_tool_boundary_buffers_then_discards_target_lines(tmp_path):
    """During an active tool window with target_addons={'foo'}, lines from foo
    are buffered and discarded when the linger expires. Lines from bar are emitted."""
    from lib import log_watcher, concurrency
    from lib.concurrency import active_calls
    while not concurrency.work_queue.empty():
        concurrency.work_queue.get_nowait()

    log_dir = fake_xbmcvfs.translatePath("special://logpath/")
    os.makedirs(log_dir, exist_ok=True)
    path = os.path.join(log_dir, "kodi.log")
    with open(path, "w") as f:
        f.write("INFO: startup\n")
    w = log_watcher.LogWatcher(quiescence_window_s=0.3)
    w._read_new_bytes()  # consume startup line

    # Begin active tool window targeting 'plugin.video.foo'
    active_calls.add_tool("t1", target_addons={"plugin.video.foo"})
    with open(path, "a") as f:
        f.write("ERROR [plugin.video.foo]: side effect from our action\n")
        f.write("ERROR [plugin.video.bar]: genuine new issue\n")
    w._ingest_chunk(w._read_new_bytes())
    # Foo line should be suppressed during active window; bar passes through
    time.sleep(0.4)
    w._close_expired_clusters()
    found_bar = False
    found_foo = False
    while not concurrency.work_queue.empty():
        _, _, item = concurrency.work_queue.get_nowait()
        text = "\n".join(getattr(item, "raw_lines", []))
        if "bar" in text:
            found_bar = True
        if "foo" in text:
            found_foo = True
    assert found_bar
    assert not found_foo
    # Cleanup
    active_calls.schedule_remove_tool("t1", after=0.0)


@pytest.mark.integration
def test_boot_post_mortem_tracks_per_session_open_close(tmp_path):
    """Two sessions started, only one ended → lines in still-open session
    must remain suppressed (only [service.kodi.ai] lines + tool-history-match
    lines)."""
    from lib import log_watcher, state_paths, concurrency
    while not concurrency.work_queue.empty():
        concurrency.work_queue.get_nowait()
    log_dir = fake_xbmcvfs.translatePath("special://logpath/")
    os.makedirs(log_dir, exist_ok=True)
    old_log = os.path.join(log_dir, "kodi.old.log")
    with open(old_log, "w") as f:
        f.write("[service.kodi.ai] reason-start abc123\n")
        f.write("[service.kodi.ai] some addon-prefixed action log\n")
        f.write("[service.kodi.ai] reason-start def456\n")  # nested second open
        f.write("[service.kodi.ai] another action\n")
        f.write("[service.kodi.ai] reason-end abc123\n")  # closes first
        # def456 STILL OPEN — anything after this should still be in def456 session
        f.write("ERROR [service.kodi.ai] our side-effect from def456\n")
        f.write("ERROR [plugin.video.seren]: GENUINE error from foreign addon\n")
    w = log_watcher.LogWatcher()
    w.boot_post_mortem()
    found_seren = False
    found_our_side_effect = False
    while not concurrency.work_queue.empty():
        _, _, item = concurrency.work_queue.get_nowait()
        text = "\n".join(getattr(item, "raw_lines", []))
        if "seren" in text:
            found_seren = True
        if "side-effect from def456" in text:
            found_our_side_effect = True
    # Foreign-addon error MUST surface as backdated incident
    assert found_seren, "foreign-addon ERROR in dangling-session region MUST surface"
    # Our own [service.kodi.ai]-prefixed line MUST be suppressed
    assert not found_our_side_effect, "[service.kodi.ai] line in dangling session MUST be suppressed"
