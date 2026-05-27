# tests/integration/test_tool_kodi_files.py
"""Integration tests for lib.tools.kodi_files.

Covers read_log (incl. level filter), write_file path restriction, and
write+delete roundtrip in special://temp/. Re-binds state_paths.xbmcvfs to
the fake registered in conftest so the module-cached `import xbmcvfs`
sees the test FS.

Spec: §4.6.
"""
import os
import sys
import pytest
from tests.integration.fakes import fake_xbmcvfs


@pytest.fixture
def setup_files(tmp_path, monkeypatch):
    # The xbmcvfs fake is already registered in conftest via reset_fake_fs.
    # Re-bind state_paths.xbmcvfs since it caches module-level on first import.
    if "lib.state_paths" in sys.modules:
        monkeypatch.setattr(sys.modules["lib.state_paths"], "xbmcvfs", fake_xbmcvfs)
    # Re-bind kodi_files xbmcvfs too (it's imported lazily inside functions,
    # but conftest already registered the fake in sys.modules).
    from lib import state_paths
    state_paths.ensure_dirs()
    # Pre-create a fake kodi.log
    log_dir = fake_xbmcvfs.translatePath("special://logpath/")
    os.makedirs(log_dir, exist_ok=True)
    with open(os.path.join(log_dir, "kodi.log"), "w") as f:
        f.write("ERROR plugin.video.seren: line1\nINFO line2\nWARNING line3\n")
    return tmp_path


@pytest.mark.integration
def test_read_log_returns_lines(setup_files):
    from lib.tools.kodi_files import read_log
    res = read_log(lines=10)
    assert res.success
    assert "lines" in res.output
    assert len(res.output["lines"]) >= 3


@pytest.mark.integration
def test_read_log_filters_by_level(setup_files):
    from lib.tools.kodi_files import read_log
    res = read_log(lines=10, level="ERROR")
    assert res.success
    assert all("ERROR" in l for l in res.output["lines"])


@pytest.mark.integration
def test_write_file_rejects_disallowed_path(setup_files):
    from lib.tools.kodi_files import write_file
    res = write_file(path="/etc/passwd", content="x")
    assert not res.success
    assert "allowed prefixes" in res.error


@pytest.mark.integration
def test_write_then_delete_in_temp(setup_files):
    from lib.tools.kodi_files import write_file, delete_file
    res1 = write_file(path="special://temp/test.txt", content="hello")
    assert res1.success
    res2 = delete_file(path="special://temp/test.txt")
    assert res2.success
