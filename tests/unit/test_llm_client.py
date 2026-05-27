import json
import pytest
import responses


@responses.activate
def test_non_streaming_chat_completion():
    responses.add(
        responses.POST,
        "https://openrouter.ai/api/v1/chat/completions",
        json={
            "id": "abc",
            "model": "google/gemini-2.0-flash-001",
            "choices": [{"message": {"role": "assistant", "content": "Hello!"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        },
        status=200,
    )
    from lib.llm.client import chat
    res = chat(
        api_key="sk-or-test",
        model="google/gemini-2.0-flash-001",
        messages=[{"role": "user", "content": "Hi"}],
    )
    assert res.text == "Hello!"
    assert res.tokens_in == 10
    assert res.tokens_out == 5
    assert res.model == "google/gemini-2.0-flash-001"
    assert res.finish_reason == "stop"


@responses.activate
def test_401_raises_specific_error():
    responses.add(
        responses.POST,
        "https://openrouter.ai/api/v1/chat/completions",
        json={"error": "invalid api key"},
        status=401,
    )
    from lib.llm.client import chat, LLMAuthError
    with pytest.raises(LLMAuthError):
        chat(api_key="bad", model="x", messages=[])


@responses.activate
def test_402_raises_specific_error():
    responses.add(
        responses.POST,
        "https://openrouter.ai/api/v1/chat/completions",
        json={"error": "insufficient credit"},
        status=402,
    )
    from lib.llm.client import chat, LLMNoCreditError
    with pytest.raises(LLMNoCreditError):
        chat(api_key="ok", model="x", messages=[])


@responses.activate
def test_404_model_not_found_raises():
    responses.add(
        responses.POST,
        "https://openrouter.ai/api/v1/chat/completions",
        json={"error": "model not found"},
        status=404,
    )
    from lib.llm.client import chat, LLMModelUnavailableError
    with pytest.raises(LLMModelUnavailableError):
        chat(api_key="ok", model="nonexistent", messages=[])


def test_default_preflight_model_constant():
    from lib.llm.client import DEFAULT_PREFLIGHT_MODEL
    assert DEFAULT_PREFLIGHT_MODEL == "google/gemini-2.0-flash-001"
