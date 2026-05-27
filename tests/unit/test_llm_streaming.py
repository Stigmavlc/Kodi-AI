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
    for chunk_text, finish_reason, usage in chat_stream(
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
    for i, (text, _, _) in enumerate(chat_stream(
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
