import json
import pytest


def test_auto_mode_picks_first_for_task_class():
    from lib.llm.router import TaskModelRouter
    r = TaskModelRouter(mode="auto")
    assert r.pick("t0_triage") == "google/gemini-2.0-flash-001"
    assert r.pick("t1_simple") == "deepseek/deepseek-chat-v3"
    assert r.pick("t2_reason") == "anthropic/claude-haiku-4.5"
    assert r.pick("t3_heroic") == "anthropic/claude-sonnet-4-6"


def test_manual_mode_returns_user_model():
    from lib.llm.router import TaskModelRouter
    r = TaskModelRouter(mode="manual", manual_model="openai/gpt-4o-mini")
    assert r.pick("t0_triage") == "openai/gpt-4o-mini"
    assert r.pick("t3_heroic") == "openai/gpt-4o-mini"


def test_next_fallback_advances():
    from lib.llm.router import TaskModelRouter
    r = TaskModelRouter(mode="auto")
    assert r.pick("t1_simple") == "deepseek/deepseek-chat-v3"
    nxt = r.next_fallback("t1_simple", "deepseek/deepseek-chat-v3")
    assert nxt == "google/gemini-2.5-flash"


def test_next_fallback_exhausts():
    from lib.llm.router import TaskModelRouter
    r = TaskModelRouter(mode="auto")
    # Last in t0_triage chain is claude-haiku-4.5
    nxt = r.next_fallback("t0_triage", "anthropic/claude-haiku-4.5")
    assert nxt is None


def test_price_lookup():
    from lib.llm.router import TaskModelRouter
    r = TaskModelRouter(mode="auto")
    price = r.price_per_mtok("deepseek/deepseek-chat-v3")
    assert price == (0.27, 1.10)


def test_user_override_replaces_defaults():
    from lib.llm.router import TaskModelRouter
    override = json.dumps({
        "t1_simple": [{"id": "my/custom-model", "price_in": 0.5, "price_out": 1.5}]
    })
    r = TaskModelRouter(mode="auto", user_override_json=override)
    assert r.pick("t1_simple") == "my/custom-model"
    # Non-overridden classes use defaults
    assert r.pick("t0_triage") == "google/gemini-2.0-flash-001"


def test_unknown_task_class_raises():
    from lib.llm.router import TaskModelRouter
    r = TaskModelRouter(mode="auto")
    with pytest.raises(KeyError):
        r.pick("t99_unknown")
