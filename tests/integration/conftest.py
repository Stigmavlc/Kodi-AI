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
