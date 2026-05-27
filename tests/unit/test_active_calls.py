import pytest


def test_initially_inactive():
    from lib.concurrency import ActiveCalls
    ac = ActiveCalls()
    assert not ac.is_active()


def test_add_tool_makes_active(monkeypatch):
    from lib.concurrency import ActiveCalls
    monkeypatch.setattr("time.monotonic", lambda: 100.0)
    ac = ActiveCalls()
    ac.add_tool("t1", target_addons={"plugin.video.seren"})
    assert ac.is_active()


def test_schedule_remove_linger(monkeypatch):
    from lib.concurrency import ActiveCalls
    t = [100.0]
    monkeypatch.setattr("time.monotonic", lambda: t[0])
    ac = ActiveCalls()
    ac.add_tool("t1", target_addons={"a"})
    ac.schedule_remove_tool("t1", after=1.0)
    # still active during linger
    assert ac.is_active()
    t[0] = 100.5
    assert ac.is_active()
    # expires past linger
    t[0] = 101.5
    assert not ac.is_active()


def test_add_session_independent_of_tools(monkeypatch):
    from lib.concurrency import ActiveCalls
    monkeypatch.setattr("time.monotonic", lambda: 100.0)
    ac = ActiveCalls()
    ac.add_session("s1")
    assert ac.is_active()


def test_targets_for_line_unioned_during_overlap(monkeypatch):
    from lib.concurrency import ActiveCalls
    t = [100.0]
    monkeypatch.setattr("time.monotonic", lambda: t[0])
    ac = ActiveCalls()
    ac.add_tool("t1", target_addons={"plugin.video.a"})
    t[0] = 100.5
    ac.add_tool("t2", target_addons={"plugin.video.b"})
    # Both overlap at t=100.5
    targets = ac.get_active_target_addons()
    assert targets == {"plugin.video.a", "plugin.video.b"}


def test_targets_all_takes_precedence(monkeypatch):
    from lib.concurrency import ActiveCalls
    monkeypatch.setattr("time.monotonic", lambda: 100.0)
    ac = ActiveCalls()
    ac.add_tool("t1", target_addons={"plugin.video.a"})
    ac.add_tool("t2", target_addons="ALL")
    assert ac.get_active_target_addons() == "ALL"


def test_update_tool_target_replaces(monkeypatch):
    from lib.concurrency import ActiveCalls
    monkeypatch.setattr("time.monotonic", lambda: 100.0)
    ac = ActiveCalls()
    ac.add_tool("t1", target_addons=set())
    ac.update_tool_target("t1", target_addons={"plugin.video.c"})
    assert ac.get_active_target_addons() == {"plugin.video.c"}


def test_remove_session_with_linger(monkeypatch):
    from lib.concurrency import ActiveCalls
    t = [100.0]
    monkeypatch.setattr("time.monotonic", lambda: t[0])
    ac = ActiveCalls()
    ac.add_session("s1")
    ac.schedule_remove_session("s1", after=2.0)
    assert ac.is_active()
    t[0] = 102.5
    assert not ac.is_active()
