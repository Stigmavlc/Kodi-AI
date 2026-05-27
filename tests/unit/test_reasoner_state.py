import json
import os
import sys
import pytest
from unittest import mock


@pytest.fixture(autouse=True)
def setup(tmp_path, monkeypatch):
    fake = mock.MagicMock()
    fake.translatePath.side_effect = lambda p: str(tmp_path / p.replace("special://", ""))
    fake.mkdirs.side_effect = lambda p: os.makedirs(fake.translatePath(p), exist_ok=True) or True
    monkeypatch.setitem(sys.modules, "xbmcvfs", fake)
    # Re-bind already-imported state_paths to this test's fake (module-cache
    # isolation per HANDOVER §4 #15 — same pattern as test_audit_log.py et al).
    if "lib.state_paths" in sys.modules:
        monkeypatch.setattr(sys.modules["lib.state_paths"], "xbmcvfs", fake)
    from lib import state_paths
    state_paths.ensure_dirs()
    yield


def test_session_state_to_dict_round_trip():
    from lib.reasoner_state import SessionState
    s = SessionState(
        session_id="abc123",
        messages=[{"role": "user", "content": "hi"}],
        tool_history=[{"name": "read_log", "result": "..."}],
        pending_tool={"name": "set_addon_setting", "args": {"addon_id": "x"}},
        snapshot_ids=["snap_1"],
        terminal_state="paused",
        paused_at=1700000000.0,
        budget_blob={"limit_s": 60, "elapsed_baseline": 5.0, "state": "PAUSED"},
        cluster_id="c1",
    )
    d = s.to_dict()
    s2 = SessionState.from_dict(d)
    assert s2.session_id == "abc123"
    assert s2.terminal_state == "paused"
    assert s2.budget_blob["elapsed_baseline"] == 5.0


def test_persist_and_load():
    from lib.reasoner_state import SessionState, persist, load
    s = SessionState(
        session_id="abc123", messages=[], tool_history=[],
        pending_tool=None, snapshot_ids=[], terminal_state="paused",
        paused_at=1700000000.0,
        budget_blob={"limit_s": 60, "elapsed_baseline": 0.0, "state": "PAUSED"},
        cluster_id=None,
    )
    persist(s)
    loaded = load("abc123")
    assert loaded.session_id == "abc123"
    assert loaded.terminal_state == "paused"


def test_load_missing_returns_none():
    from lib.reasoner_state import load
    assert load("nope") is None


def test_unlink_removes_file():
    from lib.reasoner_state import SessionState, persist, unlink, load
    s = SessionState(session_id="x", messages=[], tool_history=[],
                     pending_tool=None, snapshot_ids=[], terminal_state="paused",
                     paused_at=0.0, budget_blob={"limit_s": 1, "elapsed_baseline": 0, "state": "PAUSED"},
                     cluster_id=None)
    persist(s)
    assert load("x") is not None
    unlink("x")
    assert load("x") is None


def test_list_all_returns_session_ids():
    from lib.reasoner_state import SessionState, persist, list_all
    for sid in ("a1", "b2", "c3"):
        persist(SessionState(session_id=sid, messages=[], tool_history=[],
                             pending_tool=None, snapshot_ids=[], terminal_state="paused",
                             paused_at=0.0, budget_blob={"limit_s": 1, "elapsed_baseline": 0, "state": "PAUSED"},
                             cluster_id=None))
    ids = set(list_all())
    assert {"a1", "b2", "c3"} <= ids


def test_atomic_write_no_partial_tmp(tmp_path):
    """After persist, no .tmp file remains."""
    from lib.reasoner_state import SessionState, persist
    from lib import state_paths
    persist(SessionState(session_id="atomic", messages=[], tool_history=[],
                         pending_tool=None, snapshot_ids=[], terminal_state="paused",
                         paused_at=0.0, budget_blob={"limit_s": 1, "elapsed_baseline": 0, "state": "PAUSED"},
                         cluster_id=None))
    base = state_paths.profile_path("sessions/")
    assert not any(f.endswith(".tmp") for f in os.listdir(base))
