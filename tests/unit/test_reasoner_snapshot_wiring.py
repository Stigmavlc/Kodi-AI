# tests/unit/test_reasoner_snapshot_wiring.py
"""Reasoner pre-call snapshot wiring (Task 7.10).

run_with_tools must inspect tool.snapshot_targets_fn(args) before dispatch:
  - non-None + non-empty targets → snapshot_manager.create(label, targets, session_id)
    → attach snapshot_id to tool_result + append to outcome.snapshot_ids.
  - empty targets / None → no snapshot, no exception.

Spec: §1.13, §4.1.
"""
import pytest
from unittest import mock


class FakeStream:
    def __init__(self, items):
        self._items = items
    def __iter__(self):
        return iter(self._items)


def test_run_with_tools_creates_snapshot_when_tool_declares_targets():
    """Tool with snapshot_targets_fn returning targets → pre-call create()."""
    from lib.reasoner import Reasoner

    fake_llm = mock.MagicMock()
    fake_llm.chat_stream.side_effect = [
        FakeStream([
            ("", "tool_calls", {"prompt_tokens": 10, "completion_tokens": 5},
             [{"id": "t1", "function": {"name": "fake_mut_tool", "arguments": "{}"}}]),
        ]),
        FakeStream([
            ("done", None, None, None),
            (None, "stop", {"prompt_tokens": 5, "completion_tokens": 1}, None),
        ]),
    ]

    # Create a tool that declares snapshot_targets returning EMPTY list →
    # snapshot NOT created (empty targets short-circuit).
    fake_tool = mock.MagicMock()
    fake_tool.snapshot_targets_fn = lambda args: []  # empty targets → snapshot NOT created
    fake_tool.requires_user_confirmation = False
    fake_tool.return_value = mock.MagicMock(
        success=True, output="ok", actual_state_after=None,
        snapshot_id=None, error=None, requested="fake_mut_tool()",
    )

    r = Reasoner(
        llm_client=fake_llm, api_key="k",
        router=mock.MagicMock(pick=lambda c: "m", price_per_mtok=lambda m: (1.0, 5.0)),
        budget=mock.MagicMock(
            pre_call_check=lambda estimated_cost: (True, None),
            mid_stream_check=lambda streamed_cost: True,
            record_actual=lambda c: None,
            incident_cost_usd=0.0,
        ),
        tool_registry={"fake_mut_tool": fake_tool},
    )
    out = r.run_with_tools(initial_messages=[], task_class="t1_simple",
                           session_id="s1", max_turns=5)
    # Tool was called
    assert fake_tool.called
    # No snapshot created (empty targets)
    assert out.snapshot_ids == []


def test_run_with_tools_creates_snapshot_when_targets_non_empty():
    """Non-empty snapshot_targets → snapshot_manager.create() called once."""
    from lib.reasoner import Reasoner
    from lib import snapshot_manager

    fake_llm = mock.MagicMock()
    fake_llm.chat_stream.side_effect = [
        FakeStream([
            ("", "tool_calls", {"prompt_tokens": 10, "completion_tokens": 5},
             [{"id": "t1", "function": {"name": "fake_mut_tool",
                                          "arguments": '{"x": 1}'}}]),
        ]),
        FakeStream([
            ("done", None, None, None),
            (None, "stop", {"prompt_tokens": 5, "completion_tokens": 1}, None),
        ]),
    ]

    # Tool with non-empty snapshot targets — reasoner should call
    # snapshot_manager.create() before dispatch.
    fake_tool = mock.MagicMock()
    fake_tool.snapshot_targets_fn = lambda args: ["target_a"]
    fake_tool.requires_user_confirmation = False
    fake_tool.return_value = mock.MagicMock(
        success=True, output="ok", actual_state_after=None,
        snapshot_id=None, error=None, requested="fake_mut_tool(...)",
    )

    with mock.patch.object(snapshot_manager, "create", return_value="snap_abc123") as m_create:
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
            tool_registry={"fake_mut_tool": fake_tool},
        )
        out = r.run_with_tools(initial_messages=[], task_class="t1_simple",
                               session_id="sX", max_turns=5)
        # snapshot_manager.create() was invoked with the targets the tool declared
        m_create.assert_called_once()
        call_kwargs = m_create.call_args.kwargs
        assert call_kwargs["label"] == "pre_fake_mut_tool"
        assert call_kwargs["targets"] == ["target_a"]
        assert call_kwargs["session_id"] == "sX"
    # snapshot_id propagated to outcome
    assert "snap_abc123" in out.snapshot_ids


def test_run_with_tools_handles_snapshot_create_exception_gracefully():
    """If snapshot_manager.create() raises, the tool still runs and outcome
    has no spurious snapshot_id."""
    from lib.reasoner import Reasoner
    from lib import snapshot_manager

    fake_llm = mock.MagicMock()
    fake_llm.chat_stream.side_effect = [
        FakeStream([
            ("", "tool_calls", {"prompt_tokens": 10, "completion_tokens": 5},
             [{"id": "t1", "function": {"name": "fake_mut_tool",
                                          "arguments": '{}'}}]),
        ]),
        FakeStream([
            ("done", None, None, None),
            (None, "stop", {"prompt_tokens": 5, "completion_tokens": 1}, None),
        ]),
    ]

    fake_tool = mock.MagicMock()
    fake_tool.snapshot_targets_fn = lambda args: ["target_a"]
    fake_tool.requires_user_confirmation = False
    fake_tool.return_value = mock.MagicMock(
        success=True, output="ok", actual_state_after=None,
        snapshot_id=None, error=None, requested="fake_mut_tool()",
    )

    with mock.patch.object(snapshot_manager, "create", side_effect=RuntimeError("disk full")):
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
            tool_registry={"fake_mut_tool": fake_tool},
        )
        out = r.run_with_tools(initial_messages=[], task_class="t1_simple",
                               session_id="s1", max_turns=5)
    # Tool was still dispatched despite snapshot failure
    assert fake_tool.called
    assert out.snapshot_ids == []
