# tests/unit/test_reasoner_tool_history.py
"""tool_history with output_signature (Task 5.4-AMENDMENT — H7 dead-code fix)."""
import pytest
from unittest import mock


class FakeStream:
    def __init__(self, items):
        self._items = items
    def __iter__(self):
        return iter(self._items)


def test_run_with_tools_records_output_signature_per_tool():
    """Each tool call should append to outcome.tool_history with output_signature."""
    from lib.reasoner import Reasoner, ReasonerOutcome
    fake_llm = mock.MagicMock()
    fake_llm.chat_stream.side_effect = [
        FakeStream([
            ("", "tool_calls", {"prompt_tokens": 100, "completion_tokens": 20},
             [{"id": "t1", "function": {"name": "read_log", "arguments": "{}"}}]),
        ]),
        FakeStream([
            ("all clear", None, None, None),
            (None, "stop", {"prompt_tokens": 50, "completion_tokens": 10}, None),
        ]),
    ]
    fake_registry = {
        "read_log": mock.MagicMock(
            return_value=mock.MagicMock(
                success=True, output="log lines here", actual_state_after=None,
                snapshot_id=None, error=None, requested="read_log()",
            ))
    }
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
        task_class="t1_simple", session_id="s1", max_turns=5,
    )
    assert len(out.tool_history) == 1
    entry = out.tool_history[0]
    assert entry["name"] == "read_log"
    assert "output_signature" in entry
    from lib.prefilter import cluster_id_for
    assert entry["output_signature"] == cluster_id_for("log lines here")
