# tests/integration/conftest.py
import sys
import pytest
from tests.integration.fakes import fake_xbmcvfs

# Register xbmcvfs fake so lib.* imports see it
sys.modules["xbmcvfs"] = fake_xbmcvfs


@pytest.fixture(autouse=True)
def reset_fake_fs():
    """Wipe the fake test FS between tests AND re-bind state_paths.xbmcvfs
    to the integration fake.

    The re-bind is defensive: unit tests that ran earlier in the same
    pytest invocation may have used monkeypatch.setattr to swap
    state_paths.xbmcvfs to a MagicMock. monkeypatch restores the
    PRE-monkeypatch reference at teardown — which, for unit-only runs,
    is the real kodistubs xbmcvfs (NOT the fake we register above for
    integration). So state_paths.xbmcvfs may end up pointing at the
    kodistubs stub (whose translatePath returns '') by the time
    integration tests run. Re-bind here every test so log_watcher,
    audit_log, etc. consistently see the in-memory test FS.

    See HANDOVER.md Section 4 issue #77 for the cross-suite pollution
    root cause.
    """
    fake_xbmcvfs.reset_test_fs()
    if "lib.state_paths" in sys.modules:
        sys.modules["lib.state_paths"].xbmcvfs = fake_xbmcvfs
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


@pytest.fixture(autouse=True)
def reset_abort_event():
    """abort_event is a module-level shutdown signal; tests that set it
    (e.g. log_watcher tests) must not leak the set state to subsequent
    tests that poll abort_event.wait() in tight loops (e.g. tool
    builtin_with_verify)."""
    from lib.concurrency import abort_event
    abort_event.clear()
    yield
    abort_event.clear()
