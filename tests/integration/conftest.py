# tests/integration/conftest.py
import sys
import pytest
from tests.integration.fakes import fake_xbmcvfs

# Register xbmcvfs fake so lib.* imports see it
sys.modules["xbmcvfs"] = fake_xbmcvfs


@pytest.fixture(autouse=True)
def reset_fake_fs():
    fake_xbmcvfs.reset_test_fs()
    yield
    fake_xbmcvfs.reset_test_fs()


def pytest_configure(config):
    config.addinivalue_line("markers", "integration: kodistubs-backed integration test")


@pytest.fixture(autouse=True)
def set_startup_complete():
    """Integration tests don't run boot pass — manually signal startup_complete."""
    from lib import concurrency
    concurrency.startup_complete_event.set()
    yield
    # Don't clear — other tests may run after


@pytest.fixture(autouse=True)
def reset_active_calls():
    """active_calls is a module-level singleton; reset state between tests
    so reused call_ids (e.g. 't1') don't leak linger entries that purge
    fresh registrations on the next is_active() call."""
    from lib.concurrency import active_calls
    with active_calls._lock:
        active_calls._active_tools.clear()
        active_calls._active_sessions.clear()
        active_calls._linger.clear()
    yield
    with active_calls._lock:
        active_calls._active_tools.clear()
        active_calls._active_sessions.clear()
        active_calls._linger.clear()


@pytest.fixture(autouse=True)
def drain_work_queue():
    """work_queue is module-level; drain so prior incidents don't bleed
    into the next test's assertion."""
    from lib import concurrency
    while not concurrency.work_queue.empty():
        concurrency.work_queue.get_nowait()
    yield
    while not concurrency.work_queue.empty():
        concurrency.work_queue.get_nowait()


@pytest.fixture(autouse=True)
def reset_active_cluster_ids():
    """active_cluster_ids is a module-level set used for coalescing; reset
    between tests so a stale cluster_id doesn't suppress a fresh enqueue."""
    from lib.concurrency import active_cluster_ids
    active_cluster_ids.clear()
    yield
    active_cluster_ids.clear()
