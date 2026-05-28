import json
import threading
import pytest
import responses


@responses.activate
def test_chat_stream_yields_chunks():
    sse_body = (
        'data: {"choices":[{"delta":{"content":"Hel"}}]}\n\n'
        'data: {"choices":[{"delta":{"content":"lo"}}]}\n\n'
        'data: {"choices":[{"delta":{"content":"!"},"finish_reason":"stop"}],"usage":{"prompt_tokens":10,"completion_tokens":3}}\n\n'
        'data: [DONE]\n\n'
    )
    responses.add(
        responses.POST,
        "https://openrouter.ai/api/v1/chat/completions",
        body=sse_body,
        status=200,
        content_type="text/event-stream",
    )
    from lib.llm.client import chat_stream
    abort_event = threading.Event()
    chunks = []
    final = None
    for chunk_text, finish_reason, usage, _tool_calls in chat_stream(
        api_key="ok", model="m", messages=[{"role": "user", "content": "x"}],
        abort_event=abort_event,
    ):
        if chunk_text:
            chunks.append(chunk_text)
        if finish_reason:
            final = (finish_reason, usage)
    assert "".join(chunks) == "Hello!"
    assert final[0] == "stop"
    assert final[1]["prompt_tokens"] == 10
    assert final[1]["completion_tokens"] == 3


@responses.activate
def test_chat_stream_aborts_on_event():
    # Body with many chunks; abort early
    sse = "".join(
        f'data: {{"choices":[{{"delta":{{"content":"chunk{i}"}}}}]}}\n\n'
        for i in range(100)
    )
    responses.add(
        responses.POST,
        "https://openrouter.ai/api/v1/chat/completions",
        body=sse, status=200, content_type="text/event-stream",
    )
    from lib.llm.client import chat_stream
    abort_event = threading.Event()
    chunks = []
    for i, (text, _, _, _) in enumerate(chat_stream(
        api_key="ok", model="m", messages=[],
        abort_event=abort_event,
    )):
        if text:
            chunks.append(text)
        if i == 5:
            abort_event.set()
    # Stopped early
    assert len(chunks) < 100


@responses.activate
def test_chat_stream_merges_fragmented_tool_call_by_index():
    """HIGH-2 regression: real OpenAI-compatible streaming fragments a tool call
    across chunks — the first delta carries index/id/name + a PARTIAL
    function.arguments, later deltas carry the SAME index with more arguments
    fragments (no id/name). chat_stream MUST merge by index and surface ONE
    complete tool call (whole id+name, fully concatenated args) at finish."""
    sse_body = (
        # chunk 1: index 0 with id, name, and the FIRST half of the JSON args
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"c1",'
        '"type":"function","function":{"name":"set_kodi_setting",'
        '"arguments":"{\\"setting_id\\":\\"loo"}}]}}]}\n\n'
        # chunk 2: SAME index 0, no id/name, the SECOND half of the args
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,'
        '"function":{"arguments":"kandfeel.skin\\",\\"value\\":\\"skin.x\\"}"}}]}}]}\n\n'
        # terminal chunk: finish_reason tool_calls + usage
        'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}],'
        '"usage":{"prompt_tokens":10,"completion_tokens":5}}\n\n'
        'data: [DONE]\n\n'
    )
    responses.add(
        responses.POST,
        "https://openrouter.ai/api/v1/chat/completions",
        body=sse_body, status=200, content_type="text/event-stream",
    )
    from lib.llm.client import chat_stream
    abort_event = threading.Event()
    final_tool_calls = None
    final_reason = None
    for _chunk, finish_reason, _usage, tool_calls in chat_stream(
        api_key="ok", model="m", messages=[], abort_event=abort_event,
    ):
        if tool_calls:
            final_tool_calls = tool_calls
        if finish_reason:
            final_reason = finish_reason
    assert final_reason == "tool_calls"
    # Exactly ONE assembled tool call.
    assert final_tool_calls is not None
    assert len(final_tool_calls) == 1
    tc = final_tool_calls[0]
    assert tc["id"] == "c1"
    assert tc["function"]["name"] == "set_kodi_setting"
    # Args are the CONCATENATION of both fragments → valid JSON.
    args = json.loads(tc["function"]["arguments"])
    assert args == {"setting_id": "lookandfeel.skin", "value": "skin.x"}


@responses.activate
def test_chat_stream_merges_two_interleaved_tool_calls_by_index():
    """Two parallel tool calls fragmented and interleaved by index → chat_stream
    assembles BOTH, ordered by index, each with complete name + args."""
    sse_body = (
        # index 0 opens
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"a",'
        '"type":"function","function":{"name":"read_log","arguments":"{\\"lin"}}]}}]}\n\n'
        # index 1 opens (interleaved before index 0 finishes)
        'data: {"choices":[{"delta":{"tool_calls":[{"index":1,"id":"b",'
        '"type":"function","function":{"name":"list_addons","arguments":"{}"}}]}}]}\n\n'
        # index 0 continues
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,'
        '"function":{"arguments":"es\\":10}"}}]}}]}\n\n'
        'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}],'
        '"usage":{"prompt_tokens":8,"completion_tokens":4}}\n\n'
        'data: [DONE]\n\n'
    )
    responses.add(
        responses.POST,
        "https://openrouter.ai/api/v1/chat/completions",
        body=sse_body, status=200, content_type="text/event-stream",
    )
    from lib.llm.client import chat_stream
    final_tool_calls = None
    for _chunk, _fr, _usage, tool_calls in chat_stream(
        api_key="ok", model="m", messages=[], abort_event=threading.Event(),
    ):
        if tool_calls:
            final_tool_calls = tool_calls
    assert final_tool_calls is not None
    assert len(final_tool_calls) == 2
    # Ordered by index.
    assert final_tool_calls[0]["function"]["name"] == "read_log"
    assert json.loads(final_tool_calls[0]["function"]["arguments"]) == {"lines": 10}
    assert final_tool_calls[1]["function"]["name"] == "list_addons"
    assert json.loads(final_tool_calls[1]["function"]["arguments"]) == {}


@responses.activate
def test_validate_slugs_returns_missing():
    responses.add(
        responses.GET,
        "https://openrouter.ai/api/v1/models",
        json={"data": [{"id": "google/gemini-2.0-flash-001"}, {"id": "deepseek/deepseek-r1"}]},
        status=200,
    )
    from lib.llm.client import validate_slugs
    expected = {"google/gemini-2.0-flash-001", "deepseek/deepseek-r1", "anthropic/claude-haiku-4.5"}
    available, missing = validate_slugs(api_key="ok", expected=expected)
    assert available == {"google/gemini-2.0-flash-001", "deepseek/deepseek-r1"}
    assert missing == {"anthropic/claude-haiku-4.5"}


@responses.activate
def test_validate_slugs_timeout_returns_empty_set():
    """On timeout, both returned sets empty so callers can warn but proceed."""
    from lib.llm.client import validate_slugs
    # No mock added → urllib raises immediately
    available, missing = validate_slugs(api_key="ok", expected={"x"}, timeout=0.001)
    assert available == set()
    # On unreachable, treat all expected as missing
    assert missing == {"x"}
