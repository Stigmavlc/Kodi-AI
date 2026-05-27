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
    # If state_paths was already imported by an earlier test, its module-level
    # `import xbmcvfs` has cached the previous fake. Re-bind `state_paths.xbmcvfs`
    # to this test's fake so per-test tmp_path isolation works.
    # Same pattern as test_state_paths.py + test_settings.py + test_audit_log.py +
    # test_secrets.py + test_audit_log_redaction.py — see HANDOVER §4 #15.
    if "lib.state_paths" in sys.modules:
        monkeypatch.setattr(sys.modules["lib.state_paths"], "xbmcvfs", fake)
    from lib import state_paths
    state_paths.ensure_dirs()
    yield


def test_initial_counters_zero():
    from lib.llm.budget import BudgetGuard
    bg = BudgetGuard(per_incident_cap=0.50, daily_cap=5.0, monthly_cap=30.0)
    assert bg.incident_cost_usd == 0.0
    assert bg.daily_cost_usd == 0.0
    assert bg.monthly_cost_usd == 0.0


def test_pre_call_estimate_allows_under_cap():
    from lib.llm.budget import BudgetGuard
    bg = BudgetGuard(per_incident_cap=0.50, daily_cap=5.0, monthly_cap=30.0)
    # 1k input × $1/Mtok + 100 output × $5/Mtok = $0.0015
    ok, reason = bg.pre_call_check(estimated_cost=0.001)
    assert ok
    assert reason is None


def test_pre_call_estimate_refuses_over_per_incident():
    from lib.llm.budget import BudgetGuard
    bg = BudgetGuard(per_incident_cap=0.10, daily_cap=5.0, monthly_cap=30.0)
    bg.record_actual(0.08)
    ok, reason = bg.pre_call_check(estimated_cost=0.05)
    assert not ok
    assert "per_incident" in reason


def test_pre_call_refuses_over_daily():
    from lib.llm.budget import BudgetGuard
    bg = BudgetGuard(per_incident_cap=10.0, daily_cap=1.0, monthly_cap=30.0)
    bg.record_actual(0.95)
    ok, reason = bg.pre_call_check(estimated_cost=0.10)
    assert not ok
    assert "daily" in reason


def test_pre_call_refuses_over_monthly():
    from lib.llm.budget import BudgetGuard
    bg = BudgetGuard(per_incident_cap=10.0, daily_cap=100.0, monthly_cap=2.0)
    bg.record_actual(1.9)
    ok, reason = bg.pre_call_check(estimated_cost=0.20)
    assert not ok
    assert "monthly" in reason


def test_mid_stream_check_trips_at_100_percent():
    from lib.llm.budget import BudgetGuard
    bg = BudgetGuard(per_incident_cap=0.10, daily_cap=10.0, monthly_cap=30.0)
    # No headroom — exactly at cap trips
    assert bg.mid_stream_check(streamed_cost=0.05) is True  # ok
    bg.record_actual(0.08)
    assert bg.mid_stream_check(streamed_cost=0.025) is False  # 0.08 + 0.025 > 0.10


def test_record_actual_updates_all_counters():
    from lib.llm.budget import BudgetGuard
    bg = BudgetGuard(per_incident_cap=10.0, daily_cap=10.0, monthly_cap=10.0)
    bg.record_actual(0.5)
    assert bg.incident_cost_usd == 0.5
    assert bg.daily_cost_usd == 0.5
    assert bg.monthly_cost_usd == 0.5


def test_reset_incident_resets_only_incident():
    from lib.llm.budget import BudgetGuard
    bg = BudgetGuard(per_incident_cap=10.0, daily_cap=10.0, monthly_cap=10.0)
    bg.record_actual(0.5)
    bg.reset_incident()
    assert bg.incident_cost_usd == 0.0
    assert bg.daily_cost_usd == 0.5
    assert bg.monthly_cost_usd == 0.5


def test_persistence_round_trip():
    from lib.llm.budget import BudgetGuard
    bg = BudgetGuard(per_incident_cap=1.0, daily_cap=5.0, monthly_cap=30.0)
    bg.record_actual(1.23)
    bg.persist()
    # Fresh instance loads
    bg2 = BudgetGuard(per_incident_cap=1.0, daily_cap=5.0, monthly_cap=30.0)
    bg2.load()
    assert bg2.daily_cost_usd == 1.23
    assert bg2.monthly_cost_usd == 1.23
    # incident not persisted (resets per session)
    assert bg2.incident_cost_usd == 0.0
