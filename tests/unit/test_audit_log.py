import json
import os
import sys
import pytest
from unittest import mock


@pytest.fixture(autouse=True)
def mock_paths(tmp_path, monkeypatch):
    fake_xbmcvfs = mock.MagicMock()
    fake_xbmcvfs.translatePath.side_effect = lambda p: str(tmp_path / p.replace("special://", ""))
    fake_xbmcvfs.mkdirs.side_effect = lambda p: os.makedirs(fake_xbmcvfs.translatePath(p), exist_ok=True) or True
    monkeypatch.setitem(sys.modules, "xbmcvfs", fake_xbmcvfs)
    # If state_paths was already imported by an earlier test, its module-level
    # `import xbmcvfs` has cached the previous fake. Re-bind `state_paths.xbmcvfs`
    # to this test's fake so per-test tmp_path isolation works.
    # Same pattern as test_state_paths.py + test_settings.py — see HANDOVER §4 #15.
    if "lib.state_paths" in sys.modules:
        monkeypatch.setattr(sys.modules["lib.state_paths"], "xbmcvfs", fake_xbmcvfs)
    from lib import state_paths
    state_paths.ensure_dirs()
    yield


def test_write_event_appends_jsonl(tmp_path):
    from lib import audit_log
    audit_log.write("startup", details={"version": "0.1.0"})
    from lib import state_paths
    path = state_paths.profile_path("audit/audit.jsonl")
    with open(path) as f:
        line = f.readline()
    obj = json.loads(line)
    assert obj["event"] == "startup"
    assert obj["details"] == {"version": "0.1.0"}
    assert "ts" in obj
    assert obj["redacted"] == []


def test_write_event_with_session_id(tmp_path):
    from lib import audit_log
    audit_log.write("session_start", session_id="abc123", details={})
    from lib import state_paths
    with open(state_paths.profile_path("audit/audit.jsonl")) as f:
        obj = json.loads(f.readline())
    assert obj["session_id"] == "abc123"


def test_rotation_at_10mb(tmp_path, monkeypatch):
    from lib import audit_log, state_paths
    # Lower rotation threshold for fast test
    monkeypatch.setattr(audit_log, "_ROTATION_BYTES", 1024)
    # Write enough to trigger rotation twice
    for i in range(200):
        audit_log.write("tool_call", details={"i": i, "padding": "x" * 50})
    files = sorted(os.listdir(state_paths.profile_path("audit")))
    assert "audit.jsonl" in files
    assert "audit.1.jsonl" in files


def test_rotation_caps_at_5_files(tmp_path, monkeypatch):
    from lib import audit_log, state_paths
    monkeypatch.setattr(audit_log, "_ROTATION_BYTES", 256)
    for i in range(500):
        audit_log.write("tool_call", details={"i": i, "padding": "y" * 100})
    files = sorted(os.listdir(state_paths.profile_path("audit")))
    assert "audit.jsonl" in files
    audit_n = [f for f in files if f.startswith("audit.") and f.endswith(".jsonl")]
    # Max 5 numbered rotation files + audit.jsonl
    assert len(audit_n) <= 6


def test_redacted_field_recorded():
    from lib import audit_log
    audit_log.write("tool_call", details={"value": "<redacted>"},
                    redacted=["details.value"])
    from lib import state_paths
    with open(state_paths.profile_path("audit/audit.jsonl")) as f:
        obj = json.loads(f.readline())
    assert obj["redacted"] == ["details.value"]
