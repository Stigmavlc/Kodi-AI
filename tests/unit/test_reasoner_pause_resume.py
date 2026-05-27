# tests/unit/test_reasoner_pause_resume.py
"""Reasoner pause/resume + abort_event short-circuit (Task 5.5).

Spec: §1.7 (pause sequence), §1.8 (MonotonicBudget integration), §1.10 (abort).
"""
import pytest
from unittest import mock


class FakeStream:
    """Mimics chat_stream's 4-tuple yield."""
    def __init__(self, items):
        self._items = items
    def __iter__(self):
        return iter(self._items)


def test_pause_emitted_when_tool_requires_user():
    """A tool with .requires_user_confirmation=True triggers pause outcome.

    Reasoner must return terminal_reason='needs_user' with pending_tool,
    pending_args, and messages_so_far populated for serialization to
    SessionState (service.py wires these to telegram_ask + budget.pause).
    """
    from lib.reasoner import Reasoner, ReasonerOutcome
    fake_llm = mock.MagicMock()
    fake_llm.chat_stream.side_effect = [
        FakeStream([
            ("", "tool_calls", {"prompt_tokens": 50, "completion_tokens": 10},
             [{"id": "tc1", "function": {"name": "set_addon_setting",
                                          "arguments": '{"k": "v"}'}}]),
        ]),
    ]
    needs_user_tool = mock.MagicMock(return_value=mock.MagicMock(
        success=False, output=None, error="NEEDS_USER",
        actual_state_after=None, snapshot_id=None,
        requested="set_addon_setting(...)",
    ))
    needs_user_tool.requires_user_confirmation = True  # marker attribute
    fake_registry = {"set_addon_setting": needs_user_tool}
    r = Reasoner(
        llm_client=fake_llm, api_key="k",
        router=mock.MagicMock(pick=lambda c: "m", price_per_mtok=lambda m: (1.0, 5.0)),
        budget=mock.MagicMock(
            pre_call_check=lambda estimated_cost: (True, None),
            mid_stream_check=lambda streamed_cost: True,
            record_actual=lambda c: None,
            incident_cost_usd=0.0,
        ),
        tool_registry=fake_registry,
    )
    out = r.run_with_tools(
        initial_messages=[{"role": "user", "content": "diagnose"}],
        task_class="t1_simple",
        session_id="sX",
        max_turns=5,
    )
    assert out.terminal_reason == "needs_user"
    assert out.pending_tool == "set_addon_setting"
    assert out.pending_args == '{"k": "v"}'
    # messages_so_far must include the assistant+tool messages we just appended
    assert len(out.messages_so_far) >= 2
    # The pending tool was actually executed once (so tool_calls_made=1)
    assert out.tool_calls_made == 1


def test_abort_event_short_circuits_loop():
    """If global abort_event is set at top of turn, return aborted without LLM call."""
    from lib.reasoner import Reasoner
    from lib.concurrency import abort_event
    abort_event.set()
    try:
        fake_llm = mock.MagicMock()
        r = Reasoner(
            llm_client=fake_llm, api_key="k",
            router=mock.MagicMock(pick=lambda c: "m",
                                  price_per_mtok=lambda m: (1.0, 5.0)),
            budget=mock.MagicMock(
                pre_call_check=lambda estimated_cost: (True, None),
                mid_stream_check=lambda streamed_cost: True,
                record_actual=lambda c: None,
                incident_cost_usd=0.0,
            ),
            tool_registry={},
        )
        out = r.run_with_tools(
            initial_messages=[],
            task_class="t1_simple",
            session_id="s1",
            max_turns=5,
        )
        assert out.terminal_reason == "aborted"
        assert not fake_llm.chat_stream.called
    finally:
        abort_event.clear()
