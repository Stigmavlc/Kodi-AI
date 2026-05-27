"""Unit tests for lib.verifier — strategy dispatch.

Spec §4.4. PRAGMATIC V1: only the 'default' strategy is fully wired (30s
log-quiet wait); the rest are placeholders pending log_watcher.subscribe.
"""
from __future__ import annotations


def test_default_strategy_aborts_immediately():
    """abort_event set → default strategy returns verdict='aborted' fast."""
    from lib.verifier import run_strategy
    from lib.concurrency import abort_event
    abort_event.set()
    try:
        res = run_strategy("default", {"cluster_id": "c1"})
        assert res["verdict"] == "aborted"
        assert res["cluster_id"] == "c1"
        assert res["strategy"] == "default"
    finally:
        abort_event.clear()


def test_unknown_strategy_placeholder():
    """Unknown strategy → verdict reads '<name>_not_yet_implemented_v1'."""
    from lib.verifier import run_strategy
    res = run_strategy("playback_fail", {"cluster_id": "c1"})
    assert "not_yet_implemented" in res["verdict"]
    assert res["cluster_id"] == "c1"
    assert res["strategy"] == "playback_fail"
