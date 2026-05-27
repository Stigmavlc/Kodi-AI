import pytest
from unittest import mock


def test_reasoner_returns_outcome_on_simple_final_message():
    from lib.reasoner import Reasoner, ReasonerOutcome
    fake_llm = mock.MagicMock()
    fake_llm.chat.return_value = mock.MagicMock(
        text="diagnosis: nothing actionable", tool_calls=None,
        tokens_in=100, tokens_out=20, model="m", finish_reason="stop",
    )
    r = Reasoner(llm_client=fake_llm, api_key="k", router=mock.MagicMock(pick=lambda c: "m", price_per_mtok=lambda m: (1.0, 5.0)),
                 budget=mock.MagicMock(pre_call_check=lambda estimated_cost: (True, None), record_actual=lambda c: None))
    out = r.run_simple(messages=[{"role": "user", "content": "hi"}], task_class="t1_simple", session_id="s1")
    assert isinstance(out, ReasonerOutcome)
    assert out.final_message == "diagnosis: nothing actionable"
    assert out.tool_calls_made == 0


def test_reasoner_respects_pre_call_budget_refusal():
    from lib.reasoner import Reasoner, ReasonerOutcome
    fake_llm = mock.MagicMock()
    fake_router = mock.MagicMock(pick=lambda c: "m", price_per_mtok=lambda m: (1.0, 5.0))
    fake_budget = mock.MagicMock(pre_call_check=lambda estimated_cost: (False, "daily cap"))
    r = Reasoner(llm_client=fake_llm, api_key="k", router=fake_router, budget=fake_budget)
    out = r.run_simple(messages=[], task_class="t1_simple", session_id="s1")
    assert out.terminal_reason == "budget_refused"
    assert "daily cap" in out.notes
    assert not fake_llm.chat.called
