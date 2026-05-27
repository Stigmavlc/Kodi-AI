"""Unit tests for lib.setup_monitor.KodiAiMonitor (v0.3.0 settings-inline setup).

KodiAiMonitor subclasses xbmc.Monitor. onSettingsChanged() must:
  - Enqueue a SettingsChanged item on the work_queue (priority 30).
  - Never raise (it's called on Kodi's GUI thread).
  - Tolerate a full queue (drop silently).
"""
from __future__ import annotations
import pytest

from lib import concurrency
from lib import setup_monitor


@pytest.fixture(autouse=True)
def _drain_queue():
    while not concurrency.work_queue.empty():
        try:
            concurrency.work_queue.get_nowait()
        except Exception:
            break
    yield
    while not concurrency.work_queue.empty():
        try:
            concurrency.work_queue.get_nowait()
        except Exception:
            break


def test_on_settings_changed_enqueues_settings_changed():
    """Calling onSettingsChanged once enqueues exactly one SettingsChanged."""
    m = setup_monitor.KodiAiMonitor()
    assert concurrency.work_queue.empty()
    m.onSettingsChanged()
    assert not concurrency.work_queue.empty()
    prio, _seq, payload = concurrency.work_queue.get_nowait()
    assert prio == 30
    assert isinstance(payload, concurrency.SettingsChanged)


def test_on_settings_changed_multiple_calls_enqueues_multiple():
    """Each call enqueues another item (so successive edits all see drain)."""
    m = setup_monitor.KodiAiMonitor()
    for _ in range(3):
        m.onSettingsChanged()
    # 3 items enqueued, all SettingsChanged
    items = []
    while not concurrency.work_queue.empty():
        items.append(concurrency.work_queue.get_nowait())
    assert len(items) == 3
    for prio, _seq, payload in items:
        assert prio == 30
        assert isinstance(payload, concurrency.SettingsChanged)


def test_on_settings_changed_does_not_raise_when_queue_full(monkeypatch):
    """If put_nowait raises queue.Full, onSettingsChanged returns silently."""
    import queue as _queue
    m = setup_monitor.KodiAiMonitor()

    def boom(_item):
        raise _queue.Full

    monkeypatch.setattr(concurrency.work_queue, "put_nowait", boom)
    # Must not raise.
    m.onSettingsChanged()


def test_on_settings_changed_swallows_unexpected_exception(monkeypatch):
    """Even non-Full exceptions in put_nowait must not propagate to GUI thread."""
    m = setup_monitor.KodiAiMonitor()

    def boom(_item):
        raise RuntimeError("synthetic GUI-thread error")

    monkeypatch.setattr(concurrency.work_queue, "put_nowait", boom)
    m.onSettingsChanged()


def test_kodi_ai_monitor_is_xbmc_monitor_subclass():
    """Sanity: subclass relationship verified so Kodi will invoke
    onSettingsChanged on the right registry."""
    import xbmc
    m = setup_monitor.KodiAiMonitor()
    assert isinstance(m, xbmc.Monitor)
    # waitForAbort is the inherited method we rely on in service.main().
    assert hasattr(m, "waitForAbort")
    assert hasattr(m, "abortRequested")
