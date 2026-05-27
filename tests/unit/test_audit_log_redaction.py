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
    # If state_paths was already imported by an earlier test, its module-level
    # `import xbmcvfs` has cached the previous fake. Re-bind `state_paths.xbmcvfs`
    # to this test's fake so per-test tmp_path isolation works.
    # Same pattern as test_state_paths.py / test_audit_log.py / test_secrets.py /
    # test_settings.py — see HANDOVER §4 #15.
    if "lib.state_paths" in sys.modules:
        monkeypatch.setattr(sys.modules["lib.state_paths"], "xbmcvfs", fake)
    from lib import state_paths
    state_paths.ensure_dirs()
    yield


def test_redact_secret_pair_in_args():
    from lib import audit_log, state_paths
    audit_log.write_tool_call(
        tool_name="set_addon_setting",
        args={"addon_id": "plugin.video.seren", "key": "real_debrid_token", "value": "abc-secret-123"},
        success=True,
        duration_ms=42,
    )
    with open(state_paths.profile_path("audit/audit.jsonl")) as f:
        obj = json.loads(f.readline())
    args = obj["details"]["args"]
    assert args["value"] == "<redacted>"
    # Pair-level: addon_id AND key are obscured for single-key tools
    assert args["addon_id"] == "<redacted-secret-addon>"
    assert args["key"] == "<known-secret-key>"
    assert obj["redacted"] == ["args.addon_id", "args.key", "args.value"]


def test_no_redaction_for_non_secret():
    from lib import audit_log, state_paths
    audit_log.write_tool_call(
        tool_name="set_addon_setting",
        args={"addon_id": "plugin.video.seren", "key": "default_resolver", "value": "premiumize"},
        success=True,
        duration_ms=20,
    )
    with open(state_paths.profile_path("audit/audit.jsonl")) as f:
        obj = json.loads(f.readline())
    args = obj["details"]["args"]
    assert args["value"] == "premiumize"
    assert obj["redacted"] == []
