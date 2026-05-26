"""Integration test fixtures. Fakes for xbmc/xbmcgui/xbmcvfs are wired here
before any lib.* import. See Task 4.x for fake_xbmc / fake_xbmcvfs / etc."""
import sys

# Placeholder — will be replaced by real fake registration in later tasks.
def pytest_configure(config):
    config.addinivalue_line("markers", "integration: kodistubs-backed integration test")
