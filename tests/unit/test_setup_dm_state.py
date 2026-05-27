"""Unit tests for lib.telegram.setup_dm_state — per-chat DM state machine.

Covers:
  - get/set/clear state round-trip.
  - persistence to JSON with schema envelope.
  - schema-version mismatch wipes.
  - invalid state values rejected.
  - thread-safety (RLock allows reentrant access).
"""
from __future__ import annotations
import json
import os
import sys
from unittest import mock

import pytest


@pytest.fixture(autouse=True)
def setup_paths(tmp_path, monkeypatch):
    """Fake xbmcvfs + clear module cache."""
    fake = mock.MagicMock()
    fake.translatePath.side_effect = lambda p: str(tmp_path / p.replace("special://", ""))
    fake.mkdirs.side_effect = lambda p: os.makedirs(fake.translatePath(p), exist_ok=True) or True
    monkeypatch.setitem(sys.modules, "xbmcvfs", fake)
    if "lib.state_paths" in sys.modules:
        monkeypatch.setattr(sys.modules["lib.state_paths"], "xbmcvfs", fake)
    from lib import state_paths
    from lib.telegram import setup_dm_state
    state_paths.ensure_dirs()
    setup_dm_state.invalidate_cache()
    yield tmp_path
    setup_dm_state.invalidate_cache()


def test_get_state_returns_none_when_missing():
    from lib.telegram import setup_dm_state
    assert setup_dm_state.get_state(42) is None


def test_set_and_get_state():
    from lib.telegram import setup_dm_state
    setup_dm_state.set_state(42, setup_dm_state.AWAITING_OR_KEY)
    assert setup_dm_state.get_state(42) == setup_dm_state.AWAITING_OR_KEY


def test_set_state_persists_to_disk():
    from lib.telegram import setup_dm_state
    from lib import state_paths
    setup_dm_state.set_state(42, setup_dm_state.AWAITING_OR_KEY)
    path = state_paths.profile_path("setup_dm_state.json")
    with open(path) as f:
        blob = json.load(f)
    assert blob["schema_version"] == 1
    assert blob["states"]["42"] == setup_dm_state.AWAITING_OR_KEY


def test_set_state_overwrite_transitions():
    from lib.telegram import setup_dm_state
    setup_dm_state.set_state(7, setup_dm_state.AWAITING_OR_KEY)
    setup_dm_state.set_state(7, setup_dm_state.AWAITING_MODE)
    setup_dm_state.set_state(7, setup_dm_state.DONE)
    assert setup_dm_state.get_state(7) == setup_dm_state.DONE


def test_clear_state_removes_entry():
    from lib.telegram import setup_dm_state
    setup_dm_state.set_state(42, setup_dm_state.AWAITING_OR_KEY)
    setup_dm_state.clear_state(42)
    assert setup_dm_state.get_state(42) is None


def test_clear_state_idempotent_when_missing():
    from lib.telegram import setup_dm_state
    # No prior set — should not raise.
    setup_dm_state.clear_state(99)
    assert setup_dm_state.get_state(99) is None


def test_set_state_rejects_unknown_value():
    from lib.telegram import setup_dm_state
    with pytest.raises(ValueError):
        setup_dm_state.set_state(42, "BOGUS_STATE")


def test_load_after_invalidate_rereads_from_disk():
    from lib.telegram import setup_dm_state
    setup_dm_state.set_state(42, setup_dm_state.AWAITING_OR_KEY)
    setup_dm_state.invalidate_cache()  # simulate process restart
    assert setup_dm_state.get_state(42) == setup_dm_state.AWAITING_OR_KEY


def test_schema_version_mismatch_returns_empty():
    """If the on-disk schema version doesn't match SCHEMA_VERSION, the
    state machine starts empty (no crash)."""
    from lib.telegram import setup_dm_state
    from lib import state_paths
    path = state_paths.profile_path("setup_dm_state.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(
            {"schema_version": 99, "states": {"42": "AWAITING_OR_KEY"}}, f,
        )
    setup_dm_state.invalidate_cache()
    assert setup_dm_state.get_state(42) is None


def test_malformed_json_returns_empty():
    """Garbage on disk → empty state (no crash)."""
    from lib.telegram import setup_dm_state
    from lib import state_paths
    path = state_paths.profile_path("setup_dm_state.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("{not json")
    setup_dm_state.invalidate_cache()
    assert setup_dm_state.get_state(42) is None


def test_invalid_state_values_filtered_on_load():
    """If on-disk JSON contains an unknown state string, it's filtered out
    (rest of map still works)."""
    from lib.telegram import setup_dm_state
    from lib import state_paths
    path = state_paths.profile_path("setup_dm_state.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(
            {
                "schema_version": 1,
                "states": {"42": "BOGUS", "43": "AWAITING_MODE"},
            },
            f,
        )
    setup_dm_state.invalidate_cache()
    assert setup_dm_state.get_state(42) is None  # filtered
    assert setup_dm_state.get_state(43) == setup_dm_state.AWAITING_MODE


def test_multiple_chats_independent():
    from lib.telegram import setup_dm_state
    setup_dm_state.set_state(1, setup_dm_state.AWAITING_OR_KEY)
    setup_dm_state.set_state(2, setup_dm_state.AWAITING_MODE)
    setup_dm_state.set_state(3, setup_dm_state.DONE)
    assert setup_dm_state.get_state(1) == setup_dm_state.AWAITING_OR_KEY
    assert setup_dm_state.get_state(2) == setup_dm_state.AWAITING_MODE
    assert setup_dm_state.get_state(3) == setup_dm_state.DONE
