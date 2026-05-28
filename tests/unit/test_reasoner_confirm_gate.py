# tests/unit/test_reasoner_confirm_gate.py
"""Confirm-gate: reasoner must route tool calls through tool_routing_decision
BEFORE executing them (v0.6.0 Part 2).

A tier="confirm" (or disruptive) tool call PAUSES the reasoner without
executing — taking the existing needs_user pause path so the Telegram
[Apply]/[No]/resume flow runs. On resume after approval, the previously
pending tool executes exactly once (no infinite re-pause loop).

Read-only / immediate tools execute immediately (no false pause).

Spec: §1.6, §1.7, §1.9 (tool_routing_decision), §4.1.
"""
import json
import pytest
from unittest import mock


class FakeStream:
    """Mimics chat_stream's 4-tuple yield."""
    def __init__(self, items):
        self._items = items
    def __iter__(self):
        return iter(self._items)


def _real_tool(name, *, tier, disruptive=lambda args: False, returns=None):
    """Build a callable that mimics a real @tool-decorated function:
    has a real string .tier + .disruptive_fn, and returns a ToolResult-like."""
    result = returns or mock.MagicMock(
        success=True, output="ok", actual_state_after=None,
        snapshot_id=None, error=None, requested=f"{name}(...)",
    )
    fn = mock.MagicMock(return_value=result)
    fn.tier = tier
    fn.disruptive_fn = disruptive
    fn.target_addons_fn = lambda args: set()
    fn.snapshot_targets_fn = None
    # IMPORTANT: real tools never set requires_user_confirmation except ask_user;
    # the confirm-gate must key off tier/disruptive, not this marker.
    fn.requires_user_confirmation = False
    return fn


def _budget():
    return mock.MagicMock(
        pre_call_check=lambda estimated_cost: (True, None),
        mid_stream_check=lambda streamed_cost: True,
        record_actual=lambda c: None,
        incident_cost_usd=0.0,
    )


def _router():
    return mock.MagicMock(pick=lambda c: "m", price_per_mtok=lambda m: (1.0, 5.0))


def test_reasoner_confirm_tier_tool_pauses_not_executes():
    """A tier=confirm tool the model requests → reasoner returns needs_user
    with pending_tool set, and the tool is NOT executed."""
    from lib.reasoner import Reasoner

    fake_llm = mock.MagicMock()
    fake_llm.chat_stream.side_effect = [
        FakeStream([
            ("", "tool_calls", {"prompt_tokens": 50, "completion_tokens": 10},
             [{"id": "tc1", "function": {"name": "disable_addon",
                                          "arguments": '{"addon_id": "plugin.video.x"}'}}]),
        ]),
    ]
    confirm_tool = _real_tool("disable_addon", tier="confirm")
    r = Reasoner(
        llm_client=fake_llm, api_key="k", router=_router(), budget=_budget(),
        tool_registry={"disable_addon": confirm_tool},
    )
    out = r.run_with_tools(
        initial_messages=[{"role": "user", "content": "disable it"}],
        task_class="t2_reason", session_id="s1", max_turns=5,
    )
    assert out.terminal_reason == "needs_user"
    assert out.pending_tool == "disable_addon"
    assert out.pending_args == '{"addon_id": "plugin.video.x"}'
    # The tool was NOT executed (the gate fired before dispatch).
    assert not confirm_tool.called
    # messages_so_far carries the assistant tool_calls message for replay.
    assert len(out.messages_so_far) >= 1


def test_reasoner_tool_with_none_tier_is_gated_fail_closed():
    """LOW-1/LOW-2 (fail-closed): a registered tool whose .tier is None (missing
    / malformed — should never happen for a real @tool fn, but defensive) must be
    treated as needs-confirmation and PAUSE, not silently execute. The gate fails
    SAFE: an unknown safety classification is presumed dangerous."""
    from lib.reasoner import Reasoner

    fake_llm = mock.MagicMock()
    fake_llm.chat_stream.side_effect = [
        FakeStream([
            ("", "tool_calls", {"prompt_tokens": 10, "completion_tokens": 5},
             [{"id": "tc1", "function": {"name": "mystery_tool",
                                          "arguments": '{"x": 1}'}}]),
        ]),
    ]
    # A tool object with an explicit tier=None and no requires_user_confirmation.
    none_tier_tool = mock.MagicMock(return_value=mock.MagicMock(
        success=True, output="ran", actual_state_after=None,
        snapshot_id=None, error=None, requested="mystery_tool(...)"))
    none_tier_tool.tier = None
    none_tier_tool.disruptive_fn = lambda args: False
    none_tier_tool.target_addons_fn = lambda args: set()
    none_tier_tool.snapshot_targets_fn = None
    none_tier_tool.requires_user_confirmation = False

    r = Reasoner(
        llm_client=fake_llm, api_key="k", router=_router(), budget=_budget(),
        tool_registry={"mystery_tool": none_tier_tool},
    )
    out = r.run_with_tools(
        initial_messages=[], task_class="t2_reason", session_id="s1", max_turns=5,
    )
    # Gated, not executed.
    assert out.terminal_reason == "needs_user"
    assert out.pending_tool == "mystery_tool"
    assert not none_tier_tool.called


def test_reasoner_disruptive_immediate_tool_pauses_not_executes():
    """A tier=immediate tool whose disruptive(args) is True → also pauses."""
    from lib.reasoner import Reasoner

    fake_llm = mock.MagicMock()
    fake_llm.chat_stream.side_effect = [
        FakeStream([
            ("", "tool_calls", {"prompt_tokens": 10, "completion_tokens": 5},
             [{"id": "tc1", "function": {"name": "clear_addon_cache",
                                          "arguments": '{"addon_id": "plugin.video.x"}'}}]),
        ]),
    ]
    disruptive_tool = _real_tool(
        "clear_addon_cache", tier="immediate", disruptive=lambda args: True,
    )
    r = Reasoner(
        llm_client=fake_llm, api_key="k", router=_router(), budget=_budget(),
        tool_registry={"clear_addon_cache": disruptive_tool},
    )
    out = r.run_with_tools(
        initial_messages=[], task_class="t2_reason", session_id="s1", max_turns=5,
    )
    assert out.terminal_reason == "needs_user"
    assert out.pending_tool == "clear_addon_cache"
    assert not disruptive_tool.called


def test_reasoner_readonly_tool_executes_without_pause():
    """A read-only (tier=immediate, not disruptive) tool runs immediately."""
    from lib.reasoner import Reasoner

    fake_llm = mock.MagicMock()
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
    ro_tool = _real_tool("read_log", tier="immediate")
    r = Reasoner(
        llm_client=fake_llm, api_key="k", router=_router(), budget=_budget(),
        tool_registry={"read_log": ro_tool},
    )
    out = r.run_with_tools(
        initial_messages=[], task_class="t2_reason", session_id="s1", max_turns=5,
    )
    assert out.terminal_reason == "complete"
    assert out.final_message == "all clear"
    assert ro_tool.called  # executed, no false pause


def test_reasoner_resume_executes_pending_tool():
    """resume_from after approval executes the previously-pending confirm tool
    exactly once (no re-pause loop), then continues to completion."""
    from lib.reasoner import Reasoner
    from lib.reasoner_state import SessionState

    confirm_tool = _real_tool("disable_addon", tier="confirm")

    # On resume the approved pending tool is executed DIRECTLY by resume_from
    # (criterion A3/F) — the model is NOT relied upon to re-request it. The next
    # (and only) stream is the model's completion text after it sees the result.
    fake_llm = mock.MagicMock()
    fake_llm.chat_stream.side_effect = [
        FakeStream([
            ("Done - disabled it.", None, None, None),
            (None, "stop", {"prompt_tokens": 10, "completion_tokens": 5}, None),
        ]),
    ]
    r = Reasoner(
        llm_client=fake_llm, api_key="k", router=_router(), budget=_budget(),
        tool_registry={"disable_addon": confirm_tool},
    )
    state = SessionState(
        session_id="s1",
        messages=[
            {"role": "user", "content": "disable it"},
            {"role": "assistant", "tool_calls": [
                {"id": "tc1", "function": {"name": "disable_addon",
                                            "arguments": '{"addon_id": "plugin.video.x"}'}}]},
        ],
        tool_history=[],
        pending_tool={"name": "disable_addon",
                      "args": '{"addon_id": "plugin.video.x"}'},
        snapshot_ids=[],
        terminal_state="paused",
        paused_at=0.0,
        budget_blob={},
        cluster_id=None,
    )
    out = r.resume_from(state=state, user_reply=True, task_class="t2_reason")
    # The pending tool actually executed on resume.
    assert confirm_tool.called
    assert out.terminal_reason == "complete"
    assert "disabled" in out.final_message.lower()


def test_reasoner_resume_does_not_infinite_pause():
    """Defensive: even though the resumed model re-requests a confirm tool, the
    reasoner must not return needs_user again for the approved pending tool."""
    from lib.reasoner import Reasoner
    from lib.reasoner_state import SessionState

    confirm_tool = _real_tool("set_kodi_setting", tier="confirm")
    # Single stream: the approved tool runs directly on resume; the model then
    # only produces the completion text. If the reasoner instead re-gated the
    # approved tool, this would return needs_user (the assertion below catches it).
    fake_llm = mock.MagicMock()
    fake_llm.chat_stream.side_effect = [
        FakeStream([
            ("Switched the skin.", None, None, None),
            (None, "stop", {"prompt_tokens": 5, "completion_tokens": 2}, None),
        ]),
    ]
    r = Reasoner(
        llm_client=fake_llm, api_key="k", router=_router(), budget=_budget(),
        tool_registry={"set_kodi_setting": confirm_tool},
    )
    state = SessionState(
        session_id="s2",
        messages=[
            {"role": "user", "content": "switch skin"},
            {"role": "assistant", "tool_calls": [
                {"id": "tc1", "function": {"name": "set_kodi_setting",
                                            "arguments": '{"setting_id": "lookandfeel.skin", "value": "skin.x"}'}}]},
        ],
        tool_history=[],
        pending_tool={"name": "set_kodi_setting",
                      "args": '{"setting_id": "lookandfeel.skin", "value": "skin.x"}'},
        snapshot_ids=[],
        terminal_state="paused",
        paused_at=0.0,
        budget_blob={},
        cluster_id=None,
    )
    out = r.resume_from(state=state, user_reply=True, task_class="t2_reason")
    assert out.terminal_reason == "complete"
    assert confirm_tool.called
