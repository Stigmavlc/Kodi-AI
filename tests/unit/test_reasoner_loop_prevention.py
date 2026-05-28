# tests/unit/test_reasoner_loop_prevention.py
"""ActiveCalls loop-prevention bracketing + chat toolset restriction (v0.6.0
Part 2, criteria C + E).

C — when the reasoner runs a mutation tool, it must register the call on the
    shared ActiveCalls so log_watcher.is_active() returns True during the window
    and last_window_targets() includes the addon. The log_watcher then BUFFERS
    the mutation's own log lines and, post-window, DISCARDS the ones whose addon
    is "ours" — so the agent's own "add-on X disabled" line does NOT surface as a
    fresh incident.

E — run_with_tools(allowed_tools=...) restricts the exposed schema to the named
    tools; the chat allowlist omits http_get + write_file/delete_file and keeps
    set_kodi_setting etc.

Spec: §1.2 (ActiveCalls), §1.3 (loop prevention), §4.1.
"""
import json
import os
import sys
import pytest
from unittest import mock


@pytest.fixture
def setup_paths(tmp_path, monkeypatch):
    """Fake xbmcvfs so state_paths / secrets work (mirrors the service tests)."""
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


class FakeStream:
    def __init__(self, items):
        self._items = items
    def __iter__(self):
        return iter(self._items)


def _budget():
    return mock.MagicMock(
        pre_call_check=lambda estimated_cost: (True, None),
        mid_stream_check=lambda streamed_cost: True,
        record_actual=lambda c: None,
        incident_cost_usd=0.0,
    )


def _router():
    return mock.MagicMock(pick=lambda c: "m", price_per_mtok=lambda m: (1.0, 5.0))


def _real_tool(name, *, tier="immediate", target_addons=lambda args: set(), returns=None):
    result = returns or mock.MagicMock(
        success=True, output="ok", actual_state_after=None,
        snapshot_id=None, error=None, requested=f"{name}(...)",
    )
    fn = mock.MagicMock(return_value=result)
    fn.tier = tier
    fn.disruptive_fn = lambda args: False
    fn.target_addons_fn = target_addons
    fn.snapshot_targets_fn = None
    fn.requires_user_confirmation = False
    return fn


def test_active_call_bracketing_registers_during_tool_run(monkeypatch):
    """During a tool's execution, active_calls.is_active() is True and the
    addon target is visible via get_active_target_addons()."""
    from lib.reasoner import Reasoner
    from lib import concurrency

    # A read-only-ish tool we can observe FROM INSIDE its body: assert the
    # bracket is live exactly while the tool runs.
    observed = {}

    def tool_body(**kwargs):
        observed["active_during_run"] = concurrency.active_calls.is_active()
        observed["targets_during_run"] = concurrency.active_calls.get_active_target_addons()
        return mock.MagicMock(success=True, output="done", actual_state_after=None,
                              snapshot_id=None, error=None, requested="enable_addon(...)")

    enable_tool = _real_tool(
        "enable_addon", tier="immediate",
        target_addons=lambda args: {args.get("addon_id")},
    )
    enable_tool.side_effect = tool_body

    fake_llm = mock.MagicMock()
    fake_llm.chat_stream.side_effect = [
        FakeStream([
            ("", "tool_calls", {"prompt_tokens": 10, "completion_tokens": 5},
             [{"id": "tc1", "function": {"name": "enable_addon",
                                          "arguments": '{"addon_id": "plugin.video.seren"}'}}]),
        ]),
        FakeStream([
            ("re-enabled", None, None, None),
            (None, "stop", {"prompt_tokens": 5, "completion_tokens": 2}, None),
        ]),
    ]
    # Ensure a clean ActiveCalls for this test (restored after via monkeypatch).
    monkeypatch.setattr(concurrency, "active_calls", concurrency.ActiveCalls())
    r = Reasoner(llm_client=fake_llm, api_key="k", router=_router(), budget=_budget(),
                 tool_registry={"enable_addon": enable_tool})
    out = r.run_with_tools(initial_messages=[], task_class="t2_reason",
                           session_id="s1", max_turns=5)
    assert out.terminal_reason == "complete"
    assert observed["active_during_run"] is True
    assert "plugin.video.seren" in observed["targets_during_run"]


def test_active_call_bracketing_suppresses_self_incident(monkeypatch):
    """End-to-end loop-prevention: a mutation registers an active call scoped to
    addon X; a kodi.log line about addon X that arrives during the window is
    BUFFERED by log_watcher and then DISCARDED post-window (recognized as ours),
    so NO LogIncident is enqueued for it."""
    from lib import concurrency
    from lib.log_watcher import LogWatcher

    # Fresh shared ActiveCalls so the watcher and our bracket agree.
    fresh = concurrency.ActiveCalls()
    monkeypatch.setattr(concurrency, "active_calls", fresh)
    # log_watcher imported active_calls by name at module import — repoint it.
    import lib.log_watcher as lw
    monkeypatch.setattr(lw, "active_calls", fresh)

    # Simulate the reasoner having bracketed a disable_addon on plugin.video.x.
    fresh.add_tool("call1", target_addons={"plugin.video.x"})

    w = LogWatcher()
    # is_active() must see the live bracket → the line is buffered, not clustered.
    assert fresh.is_active() is True

    line = ("2026-05-28 10:00:00.000 ERROR <general> [plugin.video.x] "
            "add-on disabled by user")
    w._ingest_chunk(line + "\n")
    # Buffered (not added to an open cluster) because a window is active.
    assert len(w._window_buffer) == 1
    assert not w._open_clusters

    # Close the bracket; last_window_targets() still includes the addon (linger).
    fresh.schedule_remove_tool("call1", after=1.0)

    enqueued = []
    monkeypatch.setattr(lw, "enqueue", lambda inc: enqueued.append(inc))
    # Post-window eval: the buffered line's addon is "ours" → discarded.
    w._evaluate_buffer_post_window()
    assert enqueued == [], "self-inflicted log line was surfaced as an incident"
    assert w._window_buffer == []


def test_active_call_bracketing_foreign_addon_still_surfaces(monkeypatch):
    """Sanity: a DIFFERENT addon's error during our window is NOT suppressed —
    it surfaces as a new incident post-window (loop-prevention must not blind us
    to genuinely unrelated failures)."""
    from lib import concurrency
    from lib.log_watcher import LogWatcher
    import lib.log_watcher as lw

    fresh = concurrency.ActiveCalls()
    monkeypatch.setattr(concurrency, "active_calls", fresh)
    monkeypatch.setattr(lw, "active_calls", fresh)
    fresh.add_tool("call1", target_addons={"plugin.video.x"})

    w = LogWatcher()
    line = ("2026-05-28 10:00:00.000 ERROR <general> [plugin.video.OTHER] "
            "unrelated crash")
    w._ingest_chunk(line + "\n")
    assert len(w._window_buffer) == 1

    fresh.schedule_remove_tool("call1", after=1.0)
    enqueued = []
    monkeypatch.setattr(lw, "enqueue", lambda inc: enqueued.append(inc))
    w._evaluate_buffer_post_window()
    assert len(enqueued) == 1
    assert enqueued[0].likely_addon == "plugin.video.OTHER"


# ---- E: chat toolset restriction ----

def test_chat_toolset_excludes_http_and_file_write():
    """The schema passed on the chat path omits http_get + write_file/delete_file
    and includes the reversible mutations (set_kodi_setting etc.)."""
    from lib.reasoner import Reasoner
    import service

    # Use the REAL tool registry so we exercise the actual @tool schemas.
    import lib.tools as tools_pkg
    r = Reasoner(llm_client=mock.MagicMock(), api_key="k", router=_router(),
                 budget=_budget(), tool_registry=tools_pkg.registry)

    chat_schemas = r._tool_schemas(service.CHAT_ALLOWED_TOOLS)
    names = {s["function"]["name"] for s in chat_schemas}

    # Dangerous-from-free-text tools are excluded.
    assert "http_get" not in names
    assert "write_file" not in names
    assert "delete_file" not in names
    # Reversible mutations + read-only inspection are present.
    assert "set_kodi_setting" in names
    assert "enable_addon" in names
    assert "disable_addon" in names
    assert "set_addon_setting" in names
    assert "read_log" in names  # read-only file read is OK

    # The FULL (incident) catalog DOES expose the dangerous ones.
    full_schemas = r._tool_schemas(None)
    full_names = {s["function"]["name"] for s in full_schemas}
    assert "http_get" in full_names
    assert "write_file" in full_names


def test_chat_path_passes_restricted_toolset(setup_paths, monkeypatch):
    """_handle_user_msg wires allowed_tools=CHAT_ALLOWED_TOOLS into run_with_tools."""
    import service
    from lib import secrets
    from lib.concurrency import UserMsg
    secrets.set_secret("openrouter_key", "sk-or-test")

    captured = {}

    def fake_get_reasoner(api_key):
        from lib.reasoner import ReasonerOutcome
        fake = mock.MagicMock()
        def run_with_tools(**kwargs):
            captured.update(kwargs)
            return ReasonerOutcome(final_message="ok", terminal_reason="complete")
        fake.run_with_tools.side_effect = run_with_tools
        return fake

    monkeypatch.setattr(service, "_get_reasoner", fake_get_reasoner)
    monkeypatch.setattr(service, "_handle_outcome", lambda *a, **k: None)
    monkeypatch.setattr(service, "_get_budget", lambda: mock.MagicMock())

    holder = mock.MagicMock()
    holder.get.return_value = mock.MagicMock()
    service._handle_user_msg(
        UserMsg(chat_id=5, text="inspect", message_id=1, reply_to_message_id=None),
        holder,
    )
    assert captured.get("allowed_tools") == service.CHAT_ALLOWED_TOOLS


# ---- F: chat confirm -> approve -> execute -> completion reply round trip ----

def test_chat_confirm_approve_execute_replies(setup_paths, monkeypatch):
    """A chat request that triggers a confirm tool pauses; the SessionState is
    chat-tagged (origin_chat_id); on resume+approve the tool executes and the
    completion reply is sent back to the ORIGINATING chat (not broadcast)."""
    import service
    from lib import secrets, reasoner_state
    from lib.concurrency import UserMsg, ResumeWork, paused_sessions, paused_sessions_lock
    secrets.set_secret("openrouter_key", "sk-or-test")

    # Stub xbmcgui for any toast paths.
    fake_gui = mock.MagicMock()
    monkeypatch.setitem(sys.modules, "xbmcgui", fake_gui)
    if "lib.notifier" in sys.modules:
        monkeypatch.setattr(sys.modules["lib.notifier"], "xbmcgui", fake_gui)

    confirm_tool = _real_tool("set_kodi_setting", tier="confirm",
                              target_addons=lambda args: "ALL")

    # Turn 1 (chat): model requests the confirm tool → reasoner pauses.
    # Turn 2 (resume): model re-issues the approved tool → executes → final text.
    stream_turn1 = FakeStream([
        ("", "tool_calls", {"prompt_tokens": 10, "completion_tokens": 5},
         [{"id": "tc1", "function": {"name": "set_kodi_setting",
                                      "arguments": '{"setting_id": "lookandfeel.skin", "value": "skin.estuary"}'}}]),
    ])
    stream_turn2 = FakeStream([
        ("Done - switched the skin to Estuary.", None, None, None),
        (None, "stop", {"prompt_tokens": 5, "completion_tokens": 3}, None),
    ])
    fake_llm = mock.MagicMock()
    fake_llm.chat_stream.side_effect = [stream_turn1, stream_turn2]

    real_reasoner = service.reasoner_mod.Reasoner(
        llm_client=fake_llm, api_key="k", router=_router(), budget=_budget(),
        tool_registry={"set_kodi_setting": confirm_tool},
    )
    monkeypatch.setattr(service, "_get_reasoner", lambda api_key: real_reasoner)
    monkeypatch.setattr(service, "_get_budget", lambda: mock.MagicMock())

    sent = []

    class Bot:
        def send_message(self, chat_id, text, **kw):
            sent.append((chat_id, text))
            return {"ok": True, "result": {"message_id": 111}}

    bot = Bot()
    holder = mock.MagicMock()
    holder.get.return_value = bot

    # Step 1: user message → pause + confirm prompt to chat 77.
    service._handle_user_msg(
        UserMsg(chat_id=77, text="switch skin to estuary", message_id=1,
                reply_to_message_id=None),
        holder,
    )
    # A confirm prompt was sent to the originating chat.
    assert sent and sent[0][0] == 77
    assert "Confirm tool" in sent[0][1]
    # The tool did NOT execute yet (gate fired pre-exec).
    assert not confirm_tool.called

    # The paused session is recorded with origin_chat_id=77.
    with paused_sessions_lock:
        sids = list(paused_sessions.keys())
    assert sids, "no paused session recorded"
    sid = sids[-1]
    st = reasoner_state.load(sid) or paused_sessions[sid]
    assert st.origin_chat_id == 77

    sent.clear()
    # Step 2: user approves → resume → tool executes → completion reply to chat 77.
    service._handle_resume_work(ResumeWork(session_id=sid, user_reply=True), holder)
    assert confirm_tool.called, "approved tool did not execute on resume"
    # The completion reply went back to the originating chat (not broadcast).
    assert sent and sent[-1][0] == 77
    assert "switched the skin" in sent[-1][1].lower()

    # Cleanup the global paused_sessions to keep isolation.
    with paused_sessions_lock:
        paused_sessions.pop(sid, None)
