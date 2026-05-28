"""service.py system-prompt injection + per-session budget reset (v0.6.0 Part 2).

B: _handle_incident prepends the reasoner_system prompt; _handle_user_msg
   prepends the chat_system prompt. A missing prompt must NOT crash (graceful
   fallback to no system prompt + log).
D: budget.reset_incident() is called once at the start of each incident AND
   each chat session so per-incident spend doesn't accumulate across sessions.

These assert against the messages actually passed to reasoner.run_with_tools
(the reasoner is stubbed; we inspect initial_messages).
"""
from __future__ import annotations
import os
import sys
from unittest import mock

import pytest


@pytest.fixture
def setup_paths(tmp_path, monkeypatch):
    fake = mock.MagicMock()
    fake.translatePath.side_effect = lambda p: str(tmp_path / p.replace("special://", ""))
    fake.mkdirs.side_effect = lambda p: os.makedirs(fake.translatePath(p), exist_ok=True) or True
    monkeypatch.setitem(sys.modules, "xbmcvfs", fake)
    if "lib.state_paths" in sys.modules:
        monkeypatch.setattr(sys.modules["lib.state_paths"], "xbmcvfs", fake)
    from lib import state_paths, secrets
    state_paths.ensure_dirs()
    secrets.invalidate_cache()
    yield tmp_path


@pytest.fixture
def stub_xbmcgui(monkeypatch):
    fake = mock.MagicMock()
    fake.Dialog.return_value = mock.MagicMock()
    monkeypatch.setitem(sys.modules, "xbmcgui", fake)
    if "lib.notifier" in sys.modules:
        monkeypatch.setattr(sys.modules["lib.notifier"], "xbmcgui", fake)
    return fake


@pytest.fixture(autouse=True)
def reset_detect_state():
    from lib import notifier
    if hasattr(notifier, "_reset_detect_state_for_tests"):
        notifier._reset_detect_state_for_tests()
    yield
    if hasattr(notifier, "_reset_detect_state_for_tests"):
        notifier._reset_detect_state_for_tests()


def _outcome(terminal_reason="complete", final_message="ok"):
    from lib.reasoner import ReasonerOutcome
    return ReasonerOutcome(final_message=final_message, terminal_reason=terminal_reason)


def _incident(cluster_id="clstr-1", likely_addon="plugin.video.foo"):
    from lib.concurrency import LogIncident
    return LogIncident(
        cluster_id=cluster_id, first_seen=None, last_seen=None, occurrences=1,
        raw_lines=["ERROR: boom"], severity_hint="ERROR",
        likely_addon=likely_addon, likely_action=None, backdated=False,
        from_previous_session=False, triage_deferred=False,
    )


def _capture_reasoner(monkeypatch, service):
    """Stub _get_reasoner; capture the run_with_tools / resume_from kwargs."""
    captured = {}

    def fake_get_reasoner(api_key):
        fake = mock.MagicMock()
        def run_with_tools(**kwargs):
            captured["run_with_tools"] = kwargs
            return _outcome()
        fake.run_with_tools.side_effect = run_with_tools
        return fake

    monkeypatch.setattr(service, "_get_reasoner", fake_get_reasoner)
    return captured


def test_incident_injects_reasoner_system_prompt(setup_paths, stub_xbmcgui, monkeypatch):
    import service
    from lib import secrets
    secrets.set_secret("openrouter_key", "sk-or-test")
    monkeypatch.setattr(service.triage, "classify", lambda *a, **k: "CRITICAL")
    monkeypatch.setattr(service, "_handle_outcome", lambda *a, **k: None)
    captured = _capture_reasoner(monkeypatch, service)

    holder = mock.MagicMock()
    holder.get.return_value = None
    service._handle_incident(_incident(), holder)

    msgs = captured["run_with_tools"]["initial_messages"]
    assert msgs[0]["role"] == "system"
    assert "Kodi-AI" in msgs[0]["content"]
    # The user incident message still follows the system message.
    assert any(m["role"] == "user" for m in msgs[1:])


def test_chat_injects_chat_system_prompt(setup_paths, stub_xbmcgui, monkeypatch):
    import service
    from lib import secrets
    from lib.concurrency import UserMsg
    secrets.set_secret("openrouter_key", "sk-or-test")
    monkeypatch.setattr(service, "_handle_outcome", lambda *a, **k: None)
    captured = _capture_reasoner(monkeypatch, service)

    holder = mock.MagicMock()
    holder.get.return_value = mock.MagicMock()
    service._handle_user_msg(
        UserMsg(chat_id=7, text="why is seren broken?", message_id=1, reply_to_message_id=None),
        holder,
    )

    msgs = captured["run_with_tools"]["initial_messages"]
    assert msgs[0]["role"] == "system"
    assert "Kodi-AI" in msgs[0]["content"]
    assert msgs[1]["role"] == "user"
    assert msgs[1]["content"] == "why is seren broken?"


def test_incident_missing_prompt_does_not_crash(setup_paths, stub_xbmcgui, monkeypatch):
    """A FileNotFoundError from prompts.load must degrade to no system prompt,
    not crash the incident handler."""
    import service
    from lib import secrets
    secrets.set_secret("openrouter_key", "sk-or-test")
    monkeypatch.setattr(service.triage, "classify", lambda *a, **k: "CRITICAL")
    monkeypatch.setattr(service, "_handle_outcome", lambda *a, **k: None)
    monkeypatch.setattr(service.prompts, "load",
                        mock.MagicMock(side_effect=FileNotFoundError("nope")))
    captured = _capture_reasoner(monkeypatch, service)

    holder = mock.MagicMock()
    holder.get.return_value = None
    # Must not raise.
    service._handle_incident(_incident(), holder)

    msgs = captured["run_with_tools"]["initial_messages"]
    # No system message prepended; the user message is still there.
    assert all(m["role"] != "system" for m in msgs)
    assert msgs[0]["role"] == "user"


def test_budget_reset_incident_called_per_session(setup_paths, stub_xbmcgui, monkeypatch):
    """reset_incident() is called once per incident AND once per chat session."""
    import service
    from lib import secrets
    from lib.concurrency import UserMsg
    secrets.set_secret("openrouter_key", "sk-or-test")
    monkeypatch.setattr(service.triage, "classify", lambda *a, **k: "CRITICAL")
    monkeypatch.setattr(service, "_handle_outcome", lambda *a, **k: None)
    _capture_reasoner(monkeypatch, service)

    fake_budget = mock.MagicMock()
    monkeypatch.setattr(service, "_get_budget", lambda: fake_budget)

    holder = mock.MagicMock()
    holder.get.return_value = mock.MagicMock()

    service._handle_incident(_incident(), holder)
    assert fake_budget.reset_incident.call_count == 1

    service._handle_user_msg(
        UserMsg(chat_id=7, text="hi", message_id=1, reply_to_message_id=None),
        holder,
    )
    assert fake_budget.reset_incident.call_count == 2
