# tests/unit/test_reasoner_tool_loop.py
"""Reasoner tool-use loop tests (combined 5.4 + REVISED — uses chat_stream)."""
import pytest
from unittest import mock


class FakeStream:
    """Mimics chat_stream's 4-tuple yield."""
    def __init__(self, items):
        self._items = items
    def __iter__(self):
        return iter(self._items)


def test_reasoner_dispatches_tool_call_and_continues():
    """LLM streams a tool_call → reasoner dispatches → feeds result → LLM streams final."""
    from lib.reasoner import Reasoner, ReasonerOutcome
    fake_llm = mock.MagicMock()
    # Turn 1: stream emits tool_calls. Turn 2: streams final text.
    fake_llm.chat_stream.side_effect = [
        FakeStream([
            ("", "tool_calls", {"prompt_tokens": 100, "completion_tokens": 20},
             [{"id": "tc1", "function": {"name": "read_log", "arguments": '{"lines": 50}'}}]),
        ]),
        FakeStream([
            ("all clear", None, None, None),
            (None, "stop", {"prompt_tokens": 50, "completion_tokens": 10}, None),
        ]),
    ]
    fake_router = mock.MagicMock(pick=lambda c: "m", price_per_mtok=lambda m: (1.0, 5.0))
    fake_budget = mock.MagicMock(
        pre_call_check=lambda estimated_cost: (True, None),
        mid_stream_check=lambda streamed_cost: True,
        record_actual=lambda c: None,
        incident_cost_usd=0.0,
    )
    fake_registry = {
        "read_log": mock.MagicMock(
            return_value=mock.MagicMock(
                success=True, output="...", actual_state_after=None,
                snapshot_id=None, error=None, requested="read_log(lines=50)",
            ))
    }
    r = Reasoner(llm_client=fake_llm, api_key="k", router=fake_router, budget=fake_budget,
                 tool_registry=fake_registry)
    out = r.run_with_tools(initial_messages=[{"role": "user", "content": "diagnose"}],
                           task_class="t1_simple", session_id="s1", max_turns=15)
    assert out.final_message == "all clear"
    assert out.tool_calls_made == 1
    assert fake_registry["read_log"].called


def test_reasoner_respects_max_turns_cap():
    """Always-tool-call → hits max_turns."""
    from lib.reasoner import Reasoner
    fake_llm = mock.MagicMock()
    def always_tool_call(*a, **kw):
        return FakeStream([
            ("", "tool_calls", {"prompt_tokens": 10, "completion_tokens": 5},
             [{"id": "tc", "function": {"name": "read_log", "arguments": "{}"}}]),
        ])
    fake_llm.chat_stream.side_effect = always_tool_call
    fake_registry = {"read_log": mock.MagicMock(return_value=mock.MagicMock(
        success=True, output="x", actual_state_after=None, snapshot_id=None,
        error=None, requested="read_log()"))}
    r = Reasoner(llm_client=fake_llm, api_key="k",
                 router=mock.MagicMock(pick=lambda c: "m", price_per_mtok=lambda m: (1.0, 5.0)),
                 budget=mock.MagicMock(
                     pre_call_check=lambda estimated_cost: (True, None),
                     mid_stream_check=lambda streamed_cost: True,
                     record_actual=lambda c: None,
                     incident_cost_usd=0.0,
                 ),
                 tool_registry=fake_registry)
    out = r.run_with_tools(initial_messages=[], task_class="t1_simple",
                           session_id="s1", max_turns=3)
    assert out.terminal_reason == "max_turns"
    assert out.tool_calls_made == 3
