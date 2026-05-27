# tests/unit/test_triage.py
import pytest
from unittest import mock


def test_token_bucket_allows_burst():
    from lib.triage import TokenBucket
    tb = TokenBucket(rate_per_min=6, burst=3)
    for _ in range(3):
        assert tb.try_consume()
    # Burst exhausted; cannot consume immediately
    assert not tb.try_consume()


def test_token_bucket_refills_over_time(monkeypatch):
    from lib.triage import TokenBucket
    t = [100.0]
    monkeypatch.setattr("time.monotonic", lambda: t[0])
    tb = TokenBucket(rate_per_min=60, burst=1)
    assert tb.try_consume()
    assert not tb.try_consume()
    t[0] = 102.0  # 2s → 2 tokens refilled at 60/min
    assert tb.try_consume()


def test_classify_returns_critical_on_keyword():
    from lib import triage
    fake_llm = mock.MagicMock()
    fake_llm.chat.return_value = mock.MagicMock(text="CRITICAL")
    verdict = triage.classify(fake_llm, api_key="ok", model="cheap",
                              cluster_text="user action just failed")
    assert verdict == "CRITICAL"


def test_classify_returns_ignore_default_on_unparseable():
    from lib import triage
    fake_llm = mock.MagicMock()
    fake_llm.chat.return_value = mock.MagicMock(text="i am a chatty model")
    verdict = triage.classify(fake_llm, api_key="ok", model="cheap",
                              cluster_text="anything")
    assert verdict == "IGNORE"


def test_classify_handles_llm_error():
    from lib import triage
    from lib.llm.client import LLMServerError
    fake_llm = mock.MagicMock()
    fake_llm.chat.side_effect = LLMServerError("503")
    verdict = triage.classify(fake_llm, api_key="ok", model="cheap",
                              cluster_text="anything")
    assert verdict == "IGNORE"  # safe default on failure
