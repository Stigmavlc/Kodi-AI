"""Integration test for B1: budget spend must actually persist to disk.

Regression guard for the v0.4.6 blocker — `BudgetGuard.persist()` was never
called by the running service, so `record_actual()` only mutated the in-memory
counters. `budget_counters.json` was never written, so `/budget` and `/status`
(which build a FRESH guard + `.load()`) always reported $0.00, and caps/spend
reset on every Kodi restart.

The pre-existing unit test (`test_persistence_round_trip`) MANUALLY called
`persist()`, which masked the bug: it proved the round-trip works, not that the
reasoner actually invokes it. This test drives a real `Reasoner.run_with_tools`
incident through a REAL `BudgetGuard` + REAL `TaskModelRouter`, then reads the
counters back from disk via a fresh guard — exactly the production read path.
"""
from __future__ import annotations

import pytest
from unittest import mock


class FakeStream:
    """Mimics client.chat_stream's 4-tuple yield: (text, finish_reason, usage, tool_calls)."""

    def __init__(self, items):
        self._items = items

    def __iter__(self):
        return iter(self._items)


@pytest.mark.integration
def test_reasoner_persists_spend_to_disk_after_real_incident():
    """A real reasoner run that reports token usage must leave non-zero spend
    on disk, readable by a fresh BudgetGuard.load() (the /budget + /status path)."""
    from lib.reasoner import Reasoner
    from lib.llm.budget import BudgetGuard
    from lib.llm.router import TaskModelRouter
    from lib import state_paths

    # Fake LLM: one streamed turn, no tool calls, reports prompt/completion
    # tokens in the final usage so record_actual computes a real cost.
    fake_llm = mock.MagicMock()
    fake_llm.chat_stream.return_value = FakeStream([
        ("diagnosis complete", None, None, None),
        (None, "stop", {"prompt_tokens": 1000, "completion_tokens": 500}, None),
    ])

    # REAL router (auto mode) so price_per_mtok returns real pricing → real cost.
    router = TaskModelRouter(mode="auto")
    model = router.pick("t2_reason")
    in_p, out_p = router.price_per_mtok(model) or (1.0, 5.0)
    expected_cost = (1000 * in_p + 500 * out_p) / 1_000_000
    assert expected_cost > 0, "router pricing must yield a real positive cost"

    # REAL budget guard with caps high enough not to refuse.
    budget = BudgetGuard(per_incident_cap=100.0, daily_cap=100.0, monthly_cap=1000.0)

    r = Reasoner(
        llm_client=fake_llm,
        api_key="test-key",
        router=router,
        budget=budget,
        tool_registry={},  # no tools → single streamed turn → returns final text
    )
    outcome = r.run_with_tools(
        initial_messages=[{"role": "user", "content": "diagnose"}],
        task_class="t2_reason",
        session_id="sess_persist_test",
    )
    assert outcome.terminal_reason == "complete"
    assert outcome.cost_usd == pytest.approx(expected_cost)

    # The file must exist on disk (it was never written before the fix).
    counters_path = state_paths.profile_path("budget_counters.json")
    import os
    assert os.path.exists(counters_path), (
        "budget_counters.json was never written — persist() not wired into reasoner"
    )

    # FRESH guard reading from disk = exactly what cmd_budget/_load_budget does.
    fresh = BudgetGuard(per_incident_cap=100.0, daily_cap=100.0, monthly_cap=1000.0)
    fresh.load()
    assert fresh.daily_cost_usd > 0, "persisted daily spend must be non-zero"
    assert fresh.daily_cost_usd == pytest.approx(expected_cost)
    assert fresh.monthly_cost_usd == pytest.approx(expected_cost)


@pytest.mark.integration
def test_persisted_spend_accumulates_across_two_incidents():
    """Two separate reasoner runs against the SAME in-memory guard must leave the
    SUM on disk — proves persist() reflects cumulative spend, not just the last call."""
    from lib.reasoner import Reasoner
    from lib.llm.budget import BudgetGuard
    from lib.llm.router import TaskModelRouter
    from lib import state_paths
    import os

    router = TaskModelRouter(mode="auto")
    model = router.pick("t2_reason")
    in_p, out_p = router.price_per_mtok(model) or (1.0, 5.0)
    per_call = (1000 * in_p + 500 * out_p) / 1_000_000

    budget = BudgetGuard(per_incident_cap=100.0, daily_cap=100.0, monthly_cap=1000.0)

    def make_llm():
        m = mock.MagicMock()
        m.chat_stream.return_value = FakeStream([
            ("done", None, None, None),
            (None, "stop", {"prompt_tokens": 1000, "completion_tokens": 500}, None),
        ])
        return m

    for i in range(2):
        r = Reasoner(
            llm_client=make_llm(),
            api_key="k",
            router=router,
            budget=budget,
            tool_registry={},
        )
        # reset_incident between incidents (per-incident cap is session-scoped);
        # daily/monthly accumulate, which is what we persist + read.
        budget.reset_incident()
        r.run_with_tools(
            initial_messages=[{"role": "user", "content": f"incident {i}"}],
            task_class="t2_reason",
            session_id=f"sess_{i}",
        )

    counters_path = state_paths.profile_path("budget_counters.json")
    assert os.path.exists(counters_path)

    fresh = BudgetGuard(per_incident_cap=100.0, daily_cap=100.0, monthly_cap=1000.0)
    fresh.load()
    assert fresh.daily_cost_usd == pytest.approx(per_call * 2)
    assert fresh.monthly_cost_usd == pytest.approx(per_call * 2)
