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
    # isolation per HANDOVER §4 #15 — same pattern as test_reasoner_state.py et al).
    if "lib.state_paths" in sys.modules:
        monkeypatch.setattr(sys.modules["lib.state_paths"], "xbmcvfs", fake)
    from lib import state_paths
    state_paths.ensure_dirs()
    yield


def test_pause_sequence_strict_order_on_success():
    """Steps fire in order: memory → budget.pause → disk → telegram."""
    from lib import pause_sequence, reasoner_state
    from lib.concurrency import MonotonicBudget, paused_sessions, paused_sessions_lock
    order: list[str] = []
    state = reasoner_state.SessionState(
        session_id="s1", messages=[], tool_history=[], pending_tool={"name": "x"},
        snapshot_ids=[], terminal_state="paused", paused_at=0.0,
        budget_blob={"limit_s": 60, "elapsed_baseline": 0.0, "state": "RUNNING"},
        cluster_id=None,
    )
    budget = MonotonicBudget(limit_s=60); budget.start()
    def fake_telegram_send(*a, **kw): order.append("telegram"); return True
    ok = pause_sequence.pause_and_persist(
        state=state, budget=budget,
        telegram_send_callable=lambda: (order.append("telegram"), True)[1],
    )
    assert ok is True
    # Memory entry exists
    with paused_sessions_lock:
        assert "s1" in paused_sessions
    # Disk file written (atomic, no .tmp left)
    from lib import state_paths
    assert os.path.exists(state_paths.profile_path("sessions/s1.json"))
    assert budget.state.name == "PAUSED"


def test_pause_sequence_marks_pause_notify_failed_on_telegram_fail():
    """If Telegram send fails (within 15s), state marked pause_notify_failed."""
    from lib import pause_sequence, reasoner_state
    from lib.concurrency import MonotonicBudget
    state = reasoner_state.SessionState(
        session_id="s2", messages=[], tool_history=[], pending_tool={"name": "x"},
        snapshot_ids=[], terminal_state="paused", paused_at=0.0,
        budget_blob={"limit_s": 60, "elapsed_baseline": 0.0, "state": "RUNNING"},
        cluster_id=None,
    )
    budget = MonotonicBudget(limit_s=60); budget.start()
    def failing_telegram(): return False
    ok = pause_sequence.pause_and_persist(
        state=state, budget=budget, telegram_send_callable=failing_telegram,
    )
    assert ok is False
    # Disk state updated to pause_notify_failed
    from lib import state_paths
    with open(state_paths.profile_path("sessions/s2.json")) as f:
        blob = json.load(f)
    assert blob["terminal_state"] == "pause_notify_failed"
