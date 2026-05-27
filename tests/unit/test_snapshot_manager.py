import json
import os
import sys
import pytest
from unittest import mock


@pytest.fixture(autouse=True)
def setup(tmp_path, monkeypatch):
    fake = mock.MagicMock()
    fake.translatePath.side_effect = lambda p: str(tmp_path / p.replace("special://", ""))
    fake.mkdirs.side_effect = lambda p: os.makedirs(fake.translatePath(p), exist_ok=True) or True
    monkeypatch.setitem(sys.modules, "xbmcvfs", fake)
    # Re-bind module-level xbmcvfs in lib.state_paths if previously imported
    # (per established pattern — see HANDOVER §4 #15).
    if "lib.state_paths" in sys.modules:
        monkeypatch.setattr(sys.modules["lib.state_paths"], "xbmcvfs", fake)
    from lib import state_paths
    state_paths.ensure_dirs()
    # Clear module-global runtime registries between tests so per-test
    # handler registration doesn't bleed across cases.
    if "lib.snapshot_manager" in sys.modules:
        sm = sys.modules["lib.snapshot_manager"]
        sm._RUNTIME_RESOLVERS.clear()
        sm._RUNTIME_APPLIERS.clear()
    yield
    if "lib.snapshot_manager" in sys.modules:
        sm = sys.modules["lib.snapshot_manager"]
        sm._RUNTIME_RESOLVERS.clear()
        sm._RUNTIME_APPLIERS.clear()


def test_create_and_restore_kodi_setting():
    # PLAN-DEFECT FIX: original test mutated state["value"]="new" between
    # create() and restore(), then asserted ok=True / stale==[]. That is
    # internally inconsistent — plan-locked restore() refuses stale states
    # (current != snapshotted → stale → ok=False). The mutation contradicts
    # the assertion. Fixed by (a) registering runtime handlers (resolver +
    # applier) so restore() has a re-resolution path, and (b) NOT mutating
    # state between create and restore — restore should report success
    # because current state still equals snapshotted state. Captured in
    # implementer report; intent (snapshot/restore round-trip succeeds when
    # state is unchanged) is preserved.
    from lib.snapshot_manager import (
        create, restore, SnapshotTarget, register_runtime_handlers,
    )
    state = {"value": "old"}
    register_runtime_handlers(
        "kodi_setting", "x",
        resolver=lambda: state["value"],
        applier=lambda v: state.update({"value": v}),
    )
    target = SnapshotTarget(
        kind="kodi_setting", identifier="x",
        read_back=lambda: state["value"],
        equality=lambda c, s: c == s,
    )
    snap_id = create(label="test", targets=[target], session_id="s1")
    # State unchanged between create and restore — restore should succeed
    # (current==snapshotted) and the (no-op) applier runs.
    ok, stale = restore(snap_id)
    assert ok
    assert stale == []


def test_restore_detects_stale_when_state_changed_externally():
    from lib.snapshot_manager import (
        create, restore, SnapshotTarget, register_runtime_handlers,
    )
    state = {"value": "captured"}
    register_runtime_handlers(
        "kodi_setting", "x",
        resolver=lambda: state["value"],
        applier=lambda v: state.update({"value": v}),
    )
    target = SnapshotTarget(
        kind="kodi_setting", identifier="x",
        read_back=lambda: state["value"],
        equality=lambda c, s: c == s,
    )
    snap_id = create(label="t", targets=[target], session_id="s1")
    # External mutation between create and restore
    state["value"] = "externally_changed_value"
    ok, stale = restore(snap_id)
    # Restore refused; stale list non-empty
    assert not ok
    assert len(stale) == 1
    assert stale[0]["identifier"] == "x"


def test_list_returns_recent():
    from lib.snapshot_manager import create, list_snapshots, SnapshotTarget
    for i in range(3):
        create(label=f"t{i}", targets=[], session_id="s1")
    snaps = list_snapshots()
    assert len(snaps) >= 3
