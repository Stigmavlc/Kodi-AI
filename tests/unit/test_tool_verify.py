# tests/unit/test_tool_verify.py
"""Unit tests for lib.tools.verify.verify_fix.

V1 minimal: 'default' strategy = 30s log-quiet wait (abort_event interruptible).
Other strategies return a placeholder verdict (full impl deferred to Task 9.1).

Spec: §4.4.
"""


def test_verify_fix_default_strategy_returns_success():
    from lib.tools.verify import verify_fix
    from lib.concurrency import abort_event
    abort_event.set()  # short-circuit immediately
    try:
        res = verify_fix(strategy="default", args={"cluster_id": "abc"})
        # aborted because abort_event was set
        assert res.output["verdict"] == "aborted"
    finally:
        abort_event.clear()


def test_verify_fix_unknown_strategy_returns_placeholder():
    from lib.tools.verify import verify_fix
    res = verify_fix(strategy="playback_fail", args={"cluster_id": "x"})
    assert res.success
    assert "not_yet_implemented" in res.output["verdict"]
