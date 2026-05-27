import logging
import sys
import threading
import pytest
from unittest import mock


@pytest.fixture
def mock_xbmc(monkeypatch):
    fake = mock.MagicMock()
    fake.LOGINFO = 1
    fake.LOGERROR = 4
    captured = []
    fake.log.side_effect = lambda msg, level=1: captured.append((msg, level))
    monkeypatch.setitem(sys.modules, "xbmc", fake)
    # If lib.log_capture was already imported by an earlier test, its module-level
    # `import xbmc` has cached the previous fake. Re-bind `lib.log_capture.xbmc`
    # to this test's fake so per-test isolation works.
    # Same pattern as test_state_paths.py + test_settings.py + test_audit_log.py — see HANDOVER §4 #15.
    if "lib.log_capture" in sys.modules:
        monkeypatch.setattr(sys.modules["lib.log_capture"], "xbmc", fake)
    fake._captured = captured
    return fake


def test_install_redirects_stdlib_logging(mock_xbmc):
    from lib.log_capture import install, uninstall
    install()
    try:
        logging.getLogger("requests").error("test error from requests")
        msgs = [m for m, _ in mock_xbmc._captured]
        assert any("test error from requests" in m for m in msgs)
        assert any("[service.kodi.ai]" in m for m in msgs)
    finally:
        uninstall()


def test_install_redirects_stderr(mock_xbmc):
    from lib.log_capture import install, uninstall
    install()
    try:
        sys.stderr.write("native panic\n")
        sys.stderr.flush()
        msgs = [m for m, _ in mock_xbmc._captured]
        assert any("native panic" in m for m in msgs)
        assert any("[service.kodi.ai]" in m for m in msgs)
    finally:
        uninstall()


def test_recursion_guard(mock_xbmc):
    """If xbmc.log itself triggered logging, it would recurse — guard prevents."""
    from lib.log_capture import install, uninstall, _in_handler
    install()
    try:
        # Manually simulate re-entry; thread-local must short-circuit
        _in_handler.value = True
        try:
            logging.getLogger("recursion-test").error("should be dropped")
        finally:
            _in_handler.value = False
        msgs = [m for m, _ in mock_xbmc._captured]
        # The recursive emit was guarded → message NOT captured
        assert not any("should be dropped" in m for m in msgs)
    finally:
        uninstall()


def test_dedup_window_1s(mock_xbmc):
    """Duplicate messages within 1s deduped (library retry loops)."""
    from lib.log_capture import install, uninstall
    install()
    try:
        logging.getLogger("dup").error("same message")
        logging.getLogger("dup").error("same message")  # within 1s
        msgs = [m for m, _ in mock_xbmc._captured if "same message" in m]
        assert len(msgs) == 1
    finally:
        uninstall()
