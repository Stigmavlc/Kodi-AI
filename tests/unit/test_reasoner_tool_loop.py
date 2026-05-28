# tests/unit/test_reasoner_tool_loop.py
"""Reasoner tool-use loop tests (combined 5.4 + REVISED — uses chat_stream)."""
import json
import threading
import pytest
import responses
from unittest import mock


class FakeStream:
    """Mimics chat_stream's 4-tuple yield."""
    def __init__(self, items):
        self._items = items
    def __iter__(self):
        return iter(self._items)


@responses.activate
def test_reasoner_dispatches_fragmented_streamed_tool_call_end_to_end():
    """HIGH-2 end-to-end: the REAL chat_stream is wired into the reasoner and fed
    a genuinely FRAGMENTED multi-chunk tool call over SSE. The reasoner must
    dispatch EXACTLY ONE tool with the complete name and fully-parsed args (not a
    truncated/unknown call). Mocks the HTTP/SSE layer with `responses` per the
    client test patterns."""
    from lib.llm import client as llm_client
    from lib.reasoner import Reasoner

    # Turn 1: a tool call fragmented across two chunks at the same index, then a
    # terminal finish_reason chunk. Turn 2: a plain completion stream.
    sse_turn1 = (
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"c1",'
        '"type":"function","function":{"name":"set_kodi_setting",'
        '"arguments":"{\\"setting_id\\":\\"loo"}}]}}]}\n\n'
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,'
        '"function":{"arguments":"kandfeel.skin\\",\\"value\\":\\"skin.x\\"}"}}]}}]}\n\n'
        'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}],'
        '"usage":{"prompt_tokens":10,"completion_tokens":5}}\n\n'
        'data: [DONE]\n\n'
    )
    sse_turn2 = (
        'data: {"choices":[{"delta":{"content":"Switched the skin."}}]}\n\n'
        'data: {"choices":[{"delta":{},"finish_reason":"stop"}],'
        '"usage":{"prompt_tokens":12,"completion_tokens":3}}\n\n'
        'data: [DONE]\n\n'
    )
    responses.add(responses.POST, "https://openrouter.ai/api/v1/chat/completions",
                  body=sse_turn1, status=200, content_type="text/event-stream")
    responses.add(responses.POST, "https://openrouter.ai/api/v1/chat/completions",
                  body=sse_turn2, status=200, content_type="text/event-stream")

    captured_args = {}

    def _impl(**kwargs):
        captured_args.update(kwargs)
        # Return a JSON-serializable ToolResult-like (mirrors the _real_tool
        # pattern used across the reasoner tests).
        res = mock.MagicMock()
        res.success = True
        res.output = "ok"
        res.actual_state_after = None
        res.snapshot_id = None
        res.error = None
        res.requested = "set_kodi_setting(...)"
        return res

    set_setting = mock.MagicMock(side_effect=_impl)
    # tier=immediate so it executes without the confirm-gate pausing it.
    set_setting.tier = "immediate"
    set_setting.disruptive_fn = lambda args: False
    set_setting.target_addons_fn = lambda args: set()
    set_setting.snapshot_targets_fn = None
    set_setting.requires_user_confirmation = False
    # Real-@tool metadata so _tool_schemas() emits a JSON-serializable schema
    # (this test wires the REAL chat_stream, which serializes `tools` over HTTP).
    set_setting.tool_name = "set_kodi_setting"
    set_setting.description = "set a Kodi setting"
    set_setting.tool_schema = {"type": "object", "properties": {}}
    set_setting.schema_dict = None  # force the tool_schema branch in _tool_schemas

    r = Reasoner(
        llm_client=llm_client, api_key="k",
        router=mock.MagicMock(pick=lambda c: "m", price_per_mtok=lambda m: (1.0, 5.0)),
        budget=mock.MagicMock(
            pre_call_check=lambda estimated_cost: (True, None),
            mid_stream_check=lambda streamed_cost: True,
            record_actual=lambda c: None,
            incident_cost_usd=0.0,
        ),
        tool_registry={"set_kodi_setting": set_setting},
    )
    out = r.run_with_tools(initial_messages=[{"role": "user", "content": "switch skin"}],
                           task_class="t1_simple", session_id="s1", max_turns=5)
    # EXACTLY ONE dispatch, with the COMPLETE name + fully-parsed args.
    assert set_setting.call_count == 1
    assert captured_args == {"setting_id": "lookandfeel.skin", "value": "skin.x"}
    # tool_history has exactly one well-formed entry (no "unknown tool").
    assert len(out.tool_history) == 1
    assert out.tool_history[0]["name"] == "set_kodi_setting"
    assert out.final_message == "Switched the skin."


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


def test_reasoner_serializes_parallel_tool_calls_one_per_turn():
    """MED-4: when a single turn surfaces MULTIPLE tool calls, the reasoner
    processes only the FIRST (one assistant tool_calls message + one tool result),
    keeping the message history strictly well-formed. The model re-requests the
    rest next turn. Here turn 1 yields two calls; only call A executes, then the
    model completes."""
    from lib.reasoner import Reasoner
    fake_llm = mock.MagicMock()
    fake_llm.chat_stream.side_effect = [
        FakeStream([
            ("", "tool_calls", {"prompt_tokens": 10, "completion_tokens": 5},
             [
                 {"id": "a", "function": {"name": "read_log", "arguments": "{}"}},
                 {"id": "b", "function": {"name": "list_addons", "arguments": "{}"}},
             ]),
        ]),
        FakeStream([
            ("done", None, None, None),
            (None, "stop", {"prompt_tokens": 5, "completion_tokens": 1}, None),
        ]),
    ]
    read_log = mock.MagicMock(return_value=mock.MagicMock(
        success=True, output="x", actual_state_after=None, snapshot_id=None,
        error=None, requested="read_log()"))
    list_addons = mock.MagicMock(return_value=mock.MagicMock(
        success=True, output="y", actual_state_after=None, snapshot_id=None,
        error=None, requested="list_addons()"))
    r = Reasoner(
        llm_client=fake_llm, api_key="k",
        router=mock.MagicMock(pick=lambda c: "m", price_per_mtok=lambda m: (1.0, 5.0)),
        budget=mock.MagicMock(
            pre_call_check=lambda estimated_cost: (True, None),
            mid_stream_check=lambda streamed_cost: True,
            record_actual=lambda c: None,
            incident_cost_usd=0.0,
        ),
        tool_registry={"read_log": read_log, "list_addons": list_addons},
    )
    out = r.run_with_tools(initial_messages=[], task_class="t1_simple",
                           session_id="s1", max_turns=5)
    # Only the FIRST tool of the parallel turn executed.
    assert read_log.called
    assert not list_addons.called
    # Exactly one tool_history entry for that turn's single processed call.
    assert len(out.tool_history) == 1
    assert out.tool_history[0]["name"] == "read_log"
    assert out.final_message == "done"


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
