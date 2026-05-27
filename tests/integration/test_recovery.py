"""Integration tests for lib.recovery — LKG rotation + session recovery.

Spec §5.4, §7.4, §7.7. Uses xbmcvfs sys.modules patching with state_paths
re-bind so each test gets a fresh tmp_path.
"""
from __future__ import annotations
import os
import sys
import time
import pytest
from unittest import mock


@pytest.fixture(autouse=True)
def setup_paths(tmp_path, monkeypatch):
    """Re-bind state_paths.xbmcvfs to a per-test fake so tmp_path isolation
    works even when other tests have already populated module-level caches."""
    fake = mock.MagicMock()
    fake.translatePath.side_effect = lambda p: str(tmp_path / p.replace("special://", ""))
    fake.mkdirs.side_effect = lambda p: os.makedirs(fake.translatePath(p), exist_ok=True) or True
    monkeypatch.setitem(sys.modules, "xbmcvfs", fake)
    if "lib.state_paths" in sys.modules:
        monkeypatch.setattr(sys.modules["lib.state_paths"], "xbmcvfs", fake)
    from lib import state_paths
    state_paths.ensure_dirs()
    # Reset paused_sessions registry so a leftover from another test doesn't bleed in.
    from lib.concurrency import paused_sessions, paused_sessions_lock
    with paused_sessions_lock:
        paused_sessions.clear()
    yield
    with paused_sessions_lock:
        paused_sessions.clear()


def test_maybe_rotate_lkg_skipped_when_not_24h():
    """maybe_rotate_lkg returns False when crash_free_since < 24h ago."""
    from lib import health, recovery
    # Heartbeat seeds crash_free_since to ~now → < 24h
    health.heartbeat()
    health.record_telegram_rt_ok()
    assert recovery.maybe_rotate_lkg() is False


def test_boot_recovery_keeps_recent_paused():
    """A paused session newer than 24h is restored into paused_sessions."""
    from lib import reasoner_state, recovery
    from lib.concurrency import paused_sessions
    now = time.time()
    st = reasoner_state.SessionState(
        session_id="recent_paused",
        messages=[], tool_history=[], pending_tool=None,
        snapshot_ids=[], terminal_state="paused",
        paused_at=now - 60.0,  # 60s ago
        budget_blob={"limit_s": 60.0, "elapsed_baseline": 0.0, "state": "PAUSED"},
        cluster_id=None,
    )
    reasoner_state.persist(st)
    summary = recovery.boot_recovery_sessions()
    assert summary["resumed"] == 1
    assert summary["expired"] == 0
    assert "recent_paused" in paused_sessions


def test_boot_recovery_expires_stale_paused():
    """A paused session older than 24h is marked terminal_state='expired'."""
    from lib import reasoner_state, recovery
    from lib.concurrency import paused_sessions
    now = time.time()
    st = reasoner_state.SessionState(
        session_id="stale_paused",
        messages=[], tool_history=[], pending_tool=None,
        snapshot_ids=[], terminal_state="paused",
        paused_at=now - (86400 + 3600),  # 25h ago
        budget_blob={"limit_s": 60.0, "elapsed_baseline": 0.0, "state": "PAUSED"},
        cluster_id=None,
    )
    reasoner_state.persist(st)
    summary = recovery.boot_recovery_sessions()
    assert summary["expired"] == 1
    assert summary["resumed"] == 0
    assert "stale_paused" not in paused_sessions
    # On-disk terminal_state should now be 'expired'
    loaded = reasoner_state.load("stale_paused")
    assert loaded is not None
    assert loaded.terminal_state == "expired"
