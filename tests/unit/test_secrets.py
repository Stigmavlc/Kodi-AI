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
    # Same pattern as test_state_paths.py + test_settings.py + test_audit_log.py
    # — see HANDOVER §4 #15.
    if "lib.state_paths" in sys.modules:
        monkeypatch.setattr(sys.modules["lib.state_paths"], "xbmcvfs", fake)
    from lib import state_paths, secrets
    state_paths.ensure_dirs()
    secrets.invalidate_cache()
    yield


def test_get_secret_returns_none_when_missing():
    from lib import secrets
    assert secrets.get_secret("openrouter_key") is None


def test_set_and_get_secret():
    from lib import secrets
    secrets.set_secret("openrouter_key", "sk-or-test-123")
    assert secrets.get_secret("openrouter_key") == "sk-or-test-123"


def test_set_persists_to_disk():
    from lib import secrets, state_paths
    secrets.set_secret("bot_token", "12345:abc")
    path = state_paths.profile_path("secrets.json")
    with open(path) as f:
        data = json.load(f)
    assert data["bot_token"] == "12345:abc"


def test_get_after_restart_reloads_from_disk():
    from lib import secrets
    secrets.set_secret("openrouter_key", "sk-or-xyz")
    secrets.invalidate_cache()  # simulate process restart
    assert secrets.get_secret("openrouter_key") == "sk-or-xyz"


def test_delete_secret():
    from lib import secrets
    secrets.set_secret("setup_secret", "abc")
    secrets.delete_secret("setup_secret")
    assert secrets.get_secret("setup_secret") is None


def test_atomic_write_used(tmp_path):
    from lib import secrets, state_paths
    secrets.set_secret("openrouter_key", "k1")
    secrets.set_secret("openrouter_key", "k2")
    # no .tmp leftover
    path = state_paths.profile_path("secrets.json")
    assert not os.path.exists(path + ".tmp")
    with open(path) as f:
        assert json.load(f)["openrouter_key"] == "k2"
