"""Pure unit tests for state_paths. Mocks xbmcvfs via sys.modules patching."""
import sys
import os
import pytest
from unittest import mock


@pytest.fixture(autouse=True)
def mock_xbmcvfs(tmp_path, monkeypatch):
    fake = mock.MagicMock()
    fake.translatePath.side_effect = lambda p: p.replace(
        "special://profile/", str(tmp_path / "profile") + "/"
    ).replace(
        "special://userdata/", str(tmp_path / "userdata") + "/"
    ).replace(
        "special://temp/", str(tmp_path / "temp") + "/"
    )
    fake.mkdirs.side_effect = lambda p: os.makedirs(fake.translatePath(p), exist_ok=True) or True
    fake.exists.side_effect = lambda p: os.path.exists(fake.translatePath(p))
    monkeypatch.setitem(sys.modules, "xbmcvfs", fake)
    # If state_paths was already imported by an earlier test, its module-level
    # `import xbmcvfs` has cached the previous fake. Re-bind `state_paths.xbmcvfs`
    # to this test's fake so per-test tmp_path isolation works.
    if "lib.state_paths" in sys.modules:
        monkeypatch.setattr(sys.modules["lib.state_paths"], "xbmcvfs", fake)
    yield fake


def test_resolve_profile_path(mock_xbmcvfs):
    from lib import state_paths
    p = state_paths.profile_path("foo/bar.json")
    assert p.endswith("/profile/addon_data/service.kodi.ai/foo/bar.json")


def test_ensure_dirs_creates_addon_data(mock_xbmcvfs, tmp_path):
    from lib import state_paths
    state_paths.ensure_dirs()
    assert (tmp_path / "profile" / "addon_data" / "service.kodi.ai").exists()
    assert (tmp_path / "profile" / "addon_data" / "service.kodi.ai" / "sessions").exists()
    assert (tmp_path / "profile" / "addon_data" / "service.kodi.ai" / "audit").exists()
    assert (tmp_path / "userdata" / "Kodi-AI-snapshots").exists()


def test_atomic_write_creates_file(mock_xbmcvfs, tmp_path):
    from lib import state_paths
    state_paths.ensure_dirs()
    p = state_paths.profile_path("test.json")
    state_paths.atomic_write(p, b'{"hello": "world"}')
    with open(p, "rb") as f:
        assert f.read() == b'{"hello": "world"}'
    # No stale .tmp file
    assert not os.path.exists(p + ".tmp")


def test_atomic_write_overwrites_existing(mock_xbmcvfs, tmp_path):
    from lib import state_paths
    state_paths.ensure_dirs()
    p = state_paths.profile_path("test.json")
    state_paths.atomic_write(p, b"first")
    state_paths.atomic_write(p, b"second")
    with open(p, "rb") as f:
        assert f.read() == b"second"
