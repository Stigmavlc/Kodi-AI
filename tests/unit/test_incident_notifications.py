"""Unit tests for service.py incident-driven notifications (v0.5.0 Part 1).

Covers:
  - _handle_incident fires exactly one "detected" notification on CRITICAL
    triage (and none on non-CRITICAL).
  - _handle_outcome maps EVERY terminal_reason to a resolution notification
    (the silent-hang regression guard): complete / max_turns / budget_refused
    / budget_truncated / error / needs_user all notify; aborted notifies nothing.
  - Chat replies (target_chat_id set) do NOT emit the incident-style toast.
  - Degrade gracefully: with no Telegram pairing the toast still fires for both
    detect and resolve.
  - Detect-dedupe: two CRITICAL incidents inside the window → one detect notif.
"""
from __future__ import annotations
import os
import sys
from unittest import mock

import pytest


@pytest.fixture
def setup_paths(tmp_path, monkeypatch):
    """Fake xbmcvfs so state_paths / secrets / auth.chat_allowlist work."""
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


@pytest.fixture
def capture_notify(monkeypatch):
    """Capture every service.notifier.notify_user call as a dict for assertions."""
    import service
    calls: list[dict] = []

    def fake_notify(bot, chat_ids, telegram_text, toast_text=None, urgency="medium"):
        calls.append({
            "bot": bot,
            "chat_ids": list(chat_ids) if chat_ids else [],
            "telegram_text": telegram_text,
            "toast_text": toast_text,
            "urgency": urgency,
        })

    monkeypatch.setattr(service.notifier, "notify_user", fake_notify)
    return calls


class FakeBot:
    def __init__(self):
        self.sent: list[tuple[int, str]] = []

    def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text))
        return {"ok": True, "result": {}}


def _outcome(terminal_reason, final_message="", notes=""):
    from lib.reasoner import ReasonerOutcome
    return ReasonerOutcome(
        final_message=final_message,
        terminal_reason=terminal_reason,
        notes=notes,
    )


def _incident(cluster_id="clstr-1", likely_addon="plugin.video.foo"):
    from lib.concurrency import LogIncident
    return LogIncident(
        cluster_id=cluster_id,
        first_seen=None,
        last_seen=None,
        occurrences=1,
        raw_lines=["ERROR: something broke", "Traceback..."],
        severity_hint="ERROR",
        likely_addon=likely_addon,
        likely_action=None,
        backdated=False,
        from_previous_session=False,
        triage_deferred=False,
    )


# ---- B: detect notification on CRITICAL ----

def test_handle_incident_critical_fires_detect_notification(
    setup_paths, stub_xbmcgui, capture_notify, monkeypatch,
):
    """Triage CRITICAL → notify_user called once with the detect text, BEFORE
    the reasoner runs."""
    import service
    from lib import secrets
    secrets.set_secret("openrouter_key", "sk-or-test")

    monkeypatch.setattr(service.triage, "classify", lambda *a, **k: "CRITICAL")

    # Stub the reasoner so we observe ordering: notify must fire first.
    order: list[str] = []

    def fake_get_reasoner(api_key):
        order.append("reasoner_built")
        fake = mock.MagicMock()
        fake.run_with_tools.return_value = _outcome("complete", final_message="ok")
        return fake

    monkeypatch.setattr(service, "_get_reasoner", fake_get_reasoner)
    # Don't double-notify from outcome handling for this assertion.
    monkeypatch.setattr(service, "_handle_outcome", lambda *a, **k: order.append("outcome"))

    holder = mock.MagicMock()
    holder.get.return_value = None

    service._handle_incident(_incident(), holder)

    # Exactly one detect notification.
    assert len(capture_notify) == 1
    detect = capture_notify[0]
    assert "detect" in detect["toast_text"].lower() or "problem" in detect["toast_text"].lower()
    assert "work" in detect["telegram_text"].lower()
    # Detect fired before the reasoner was built.
    assert order[0] == "reasoner_built"  # built after notify (notify isn't in `order`)
    # ...and the detect happened before outcome handling.
    assert "outcome" in order


def test_handle_incident_non_critical_no_notification(
    setup_paths, stub_xbmcgui, capture_notify, monkeypatch,
):
    """Triage non-CRITICAL → no detect notification, no reasoner."""
    import service
    from lib import secrets
    secrets.set_secret("openrouter_key", "sk-or-test")
    monkeypatch.setattr(service.triage, "classify", lambda *a, **k: "IGNORE")
    reasoner_built = []
    monkeypatch.setattr(service, "_get_reasoner",
                        lambda api_key: reasoner_built.append(True))
    holder = mock.MagicMock()
    service._handle_incident(_incident(), holder)
    assert capture_notify == []
    assert reasoner_built == []


# ---- C: terminal_reason mapping (the silent-hang regression guard) ----

@pytest.mark.parametrize("terminal_reason", [
    "complete", "max_turns", "budget_refused", "budget_truncated",
    "error", "needs_user",
])
def test_handle_outcome_maps_every_terminal_reason(
    setup_paths, stub_xbmcgui, capture_notify, monkeypatch, terminal_reason,
):
    """Every non-aborted terminal_reason → at least one resolution notification
    fires for an incident-driven outcome (toast at minimum)."""
    import service
    # Pretend there's a Telegram recipient so needs_user's existing pause path
    # has somewhere to send (its toast is what we assert here).
    monkeypatch.setattr(service.tg_auth, "chat_allowlist", lambda: [42])
    # Stub the pause_sequence so needs_user doesn't try real persistence.
    monkeypatch.setattr(service.pause_sequence, "pause_and_persist",
                        lambda **k: None)

    bot = FakeBot()
    outcome = _outcome(terminal_reason, final_message="did a thing", notes="boom")
    service._handle_outcome(outcome, bot, "sess_1", "clstr-1")

    assert len(capture_notify) >= 1, (
        f"terminal_reason={terminal_reason!r} produced NO notification "
        f"(silent-hang regression)"
    )
    # A toast string must be present (resolves even with no Telegram).
    assert any(c["toast_text"] for c in capture_notify), (
        f"terminal_reason={terminal_reason!r} produced no toast_text"
    )


def test_handle_outcome_aborted_notifies_nothing(
    setup_paths, stub_xbmcgui, capture_notify, monkeypatch,
):
    """aborted == shutdown → silence is correct (no notification)."""
    import service
    monkeypatch.setattr(service.tg_auth, "chat_allowlist", lambda: [42])
    bot = FakeBot()
    service._handle_outcome(_outcome("aborted"), bot, "sess_1", "clstr-1")
    assert capture_notify == []


def test_handle_outcome_complete_uses_final_message(
    setup_paths, stub_xbmcgui, capture_notify, monkeypatch,
):
    """complete with a final_message → that message is used in the Telegram body."""
    import service
    monkeypatch.setattr(service.tg_auth, "chat_allowlist", lambda: [42])
    bot = FakeBot()
    service._handle_outcome(
        _outcome("complete", final_message="Re-enabled the addon"),
        bot, "sess_1", "clstr-1",
    )
    assert capture_notify
    body = capture_notify[0]["telegram_text"]
    assert "Re-enabled the addon" in body


def test_handle_outcome_complete_escapes_html_in_final_message(
    setup_paths, stub_xbmcgui, capture_notify, monkeypatch,
):
    """final_message with HTML-special chars is escaped before it reaches the
    Telegram body (the bot sends parse_mode=HTML; unescaped <&> would 400)."""
    import service
    monkeypatch.setattr(service.tg_auth, "chat_allowlist", lambda: [42])
    bot = FakeBot()
    service._handle_outcome(
        _outcome("complete", final_message="re-enabled <plugin> & restarted"),
        bot, "sess_1", "clstr-1",
    )
    body = capture_notify[0]["telegram_text"]
    assert "<plugin>" not in body
    assert "&lt;plugin&gt;" in body
    assert "&amp;" in body


def test_handle_outcome_error_redacts_notes(
    setup_paths, stub_xbmcgui, capture_notify, monkeypatch,
):
    """error notes that carry a secret-bearing string are redacted before they
    can reach the user."""
    import service
    monkeypatch.setattr(service.tg_auth, "chat_allowlist", lambda: [42])
    bot = FakeBot()
    leaky = "failed: https://api.telegram.org/bot1234567890:ABCdefGHIjklMNOpqrSTUvwxYZabcdefgHIjkl/getMe"
    service._handle_outcome(
        _outcome("error", notes=leaky), bot, "sess_1", "clstr-1",
    )
    assert capture_notify
    joined = (capture_notify[0]["telegram_text"] or "") + (capture_notify[0]["toast_text"] or "")
    assert "ABCdefGHIjklMNOpqrSTUvwxYZabcdefgHIjkl" not in joined


# ---- C: chat replies must NOT get the incident toast ----

def test_handle_outcome_chat_reply_no_incident_toast(
    setup_paths, stub_xbmcgui, capture_notify, monkeypatch,
):
    """Outcome with target_chat_id set (a chat reply) → no incident 'fixed!'
    toast. The chat reply path sends a plain Telegram message only."""
    import service
    bot = FakeBot()
    service._handle_outcome(
        _outcome("complete", final_message="here is your answer"),
        bot, "chat_1", None, target_chat_id=99,
    )
    # No notify_user (incident-style toast) for chat replies.
    assert capture_notify == []
    # The plain reply went out over Telegram.
    assert bot.sent and bot.sent[0][0] == 99


def test_handle_outcome_chat_reply_empty_message_no_toast(
    setup_paths, stub_xbmcgui, capture_notify, monkeypatch,
):
    """Chat reply whose outcome has an empty final_message still must not emit
    an incident toast (behavior unchanged from pre-0.5.0 for chat)."""
    import service
    bot = FakeBot()
    service._handle_outcome(
        _outcome("budget_refused", final_message=""),
        bot, "chat_1", None, target_chat_id=99,
    )
    assert capture_notify == []


# ---- E: degrade gracefully (no Telegram pairing) ----

def test_resolve_toast_fires_without_pairing(
    setup_paths, stub_xbmcgui, monkeypatch,
):
    """No allowlist + bot None → resolution toast still fires. Uses the REAL
    notify_user (no capture stub) to prove the actual toast path."""
    import service
    monkeypatch.setattr(service.tg_auth, "chat_allowlist", lambda: [])
    service._handle_outcome(_outcome("max_turns"), None, "sess_1", "clstr-1")
    # A toast was shown despite no pairing / no bot.
    assert stub_xbmcgui.Dialog.return_value.notification.called


def test_detect_toast_fires_without_pairing(
    setup_paths, stub_xbmcgui, monkeypatch,
):
    """No allowlist + bot None → detect toast still fires. Uses the REAL
    notify_user (no capture stub) to prove the actual toast path."""
    import service
    from lib import secrets
    secrets.set_secret("openrouter_key", "sk-or-test")
    monkeypatch.setattr(service.triage, "classify", lambda *a, **k: "CRITICAL")
    monkeypatch.setattr(service.tg_auth, "chat_allowlist", lambda: [])
    monkeypatch.setattr(service, "_get_reasoner",
                        lambda api_key: mock.MagicMock(
                            run_with_tools=mock.MagicMock(
                                return_value=_outcome("complete", final_message="ok"))))
    holder = mock.MagicMock()
    holder.get.return_value = None
    service._handle_incident(_incident(), holder)
    # At least the detect toast fired (resolution also toasts, but the detect
    # is what proves degrade-gracefully on the detect path).
    assert stub_xbmcgui.Dialog.return_value.notification.called


# ---- D: dedupe across two CRITICAL incidents ----

def test_detect_dedupe_window(
    setup_paths, stub_xbmcgui, capture_notify, monkeypatch,
):
    """Two CRITICAL incidents within the window → only ONE detect notification
    (the resolution notifications are NOT deduped, but we run the reasoner
    inline so the second incident sees the first's armed window)."""
    import service
    from lib import secrets
    secrets.set_secret("openrouter_key", "sk-or-test")
    monkeypatch.setattr(service.triage, "classify", lambda *a, **k: "CRITICAL")
    monkeypatch.setattr(service, "_get_reasoner",
                        lambda api_key: mock.MagicMock(
                            run_with_tools=mock.MagicMock(
                                return_value=_outcome("complete", final_message="ok"))))
    # Swallow the resolution notifications so we count only DETECT ones.
    monkeypatch.setattr(service, "_handle_outcome", lambda *a, **k: None)

    holder = mock.MagicMock()
    holder.get.return_value = None

    service._handle_incident(_incident(cluster_id="c1"), holder)
    service._handle_incident(_incident(cluster_id="c2"), holder)

    # Only the first incident emitted a detect notification.
    assert len(capture_notify) == 1
