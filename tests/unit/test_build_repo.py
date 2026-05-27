"""Unit tests for tools/build_repo.py.

Invokes the script via subprocess against a temp output dir so the repo's
real dist/ is never touched. Asserts:
- the addon zip exists at the expected path
- the repository manifest (addons.xml) + .md5 exist and md5 matches
- the repository addon zip exists
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import zipfile

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
BUILD_SCRIPT = os.path.join(REPO_ROOT, "tools", "build_repo.py")


def _run_builder(out_dir: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, BUILD_SCRIPT, "--output", out_dir],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )


def test_build_repo_produces_addon_zip(tmp_path):
    out_dir = tmp_path / "dist"
    _run_builder(str(out_dir))

    # service.kodi.ai-0.1.0.zip at dist root
    candidates = list(out_dir.glob("service.kodi.ai-*.zip"))
    assert len(candidates) == 1, f"expected exactly one addon zip, got {candidates}"
    addon_zip = candidates[0]
    assert addon_zip.stat().st_size > 0

    # Verify addon zip has addon.xml at service.kodi.ai/addon.xml inside
    with zipfile.ZipFile(addon_zip) as z:
        names = z.namelist()
    assert "service.kodi.ai/addon.xml" in names
    # No caches/tests should be present
    assert not any("__pycache__" in n for n in names), "addon zip must not contain __pycache__"
    assert not any(n.endswith(".pyc") for n in names), "addon zip must not contain .pyc files"


def test_build_repo_manifest_md5_matches(tmp_path):
    out_dir = tmp_path / "dist"
    _run_builder(str(out_dir))

    addons_xml = out_dir / "repo" / "addons.xml"
    addons_md5 = out_dir / "repo" / "addons.xml.md5"
    assert addons_xml.exists(), "addons.xml must exist in dist/repo"
    assert addons_md5.exists(), "addons.xml.md5 must exist in dist/repo"

    expected = hashlib.md5(addons_xml.read_bytes()).hexdigest()
    actual = addons_md5.read_text().strip()
    assert actual == expected, f"md5 mismatch: file={actual} expected={expected}"


def test_build_repo_produces_repository_addon_zip(tmp_path):
    out_dir = tmp_path / "dist"
    _run_builder(str(out_dir))

    repo_zips = list(out_dir.glob("repository.kodi-ai*.zip"))
    assert len(repo_zips) == 1, f"expected one repository addon zip, got {repo_zips}"

    # And the mirrored addon zip inside dist/repo/service.kodi.ai/
    mirrored = list((out_dir / "repo" / "service.kodi.ai").glob("service.kodi.ai-*.zip"))
    assert len(mirrored) == 1, f"expected mirrored zip in repo dir, got {mirrored}"
