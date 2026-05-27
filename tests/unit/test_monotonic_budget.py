import time
import pytest
from freezegun import freeze_time


def test_initial_state_is_idle():
    from lib.concurrency import MonotonicBudget, BudgetState
    b = MonotonicBudget(limit_s=60)
    assert b.state == BudgetState.IDLE
    assert b.elapsed() == 0.0


def test_start_transitions_to_running():
    from lib.concurrency import MonotonicBudget, BudgetState
    b = MonotonicBudget(limit_s=60)
    b.start()
    assert b.state == BudgetState.RUNNING


def test_double_start_raises():
    from lib.concurrency import MonotonicBudget, BudgetStateError
    b = MonotonicBudget(limit_s=60)
    b.start()
    with pytest.raises(BudgetStateError):
        b.start()


def test_pause_from_idle_raises():
    from lib.concurrency import MonotonicBudget, BudgetStateError
    b = MonotonicBudget(limit_s=60)
    with pytest.raises(BudgetStateError):
        b.pause()


def test_elapsed_accumulates_only_when_running(monkeypatch):
    from lib.concurrency import MonotonicBudget
    t = [1000.0]
    monkeypatch.setattr("time.monotonic", lambda: t[0])
    b = MonotonicBudget(limit_s=60)
    b.start()
    t[0] = 1005.0
    assert b.elapsed() == pytest.approx(5.0)
    b.pause()
    t[0] = 1100.0
    # paused — elapsed does NOT advance
    assert b.elapsed() == pytest.approx(5.0)
    b.resume()
    t[0] = 1110.0
    # running again — adds 10s
    assert b.elapsed() == pytest.approx(15.0)


def test_stop_freezes_elapsed(monkeypatch):
    from lib.concurrency import MonotonicBudget, BudgetState
    t = [1000.0]
    monkeypatch.setattr("time.monotonic", lambda: t[0])
    b = MonotonicBudget(limit_s=60)
    b.start()
    t[0] = 1003.0
    b.stop()
    assert b.state == BudgetState.IDLE
    assert b.elapsed() == pytest.approx(3.0)


def test_serialize_and_rehydrate(monkeypatch):
    from lib.concurrency import MonotonicBudget, BudgetState
    t = [1000.0]
    monkeypatch.setattr("time.monotonic", lambda: t[0])
    b = MonotonicBudget(limit_s=60)
    b.start()
    t[0] = 1010.0
    b.pause()
    blob = b.to_dict()
    assert blob == {"limit_s": 60, "elapsed_baseline": 10.0, "state": "PAUSED"}
    # Rehydrate
    t[0] = 2000.0  # later run
    b2 = MonotonicBudget.from_dict(blob)
    assert b2.state == BudgetState.PAUSED
    assert b2.elapsed() == pytest.approx(10.0)
    b2.resume()
    t[0] = 2005.0
    assert b2.elapsed() == pytest.approx(15.0)
