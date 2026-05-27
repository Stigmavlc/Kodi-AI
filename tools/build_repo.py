#!/usr/bin/env python3
"""Build a Kodi addon repository ZIP for Kodi-AI.

Outputs:
- dist/service.kodi.ai-{ver}.zip         — installable addon zip
- dist/repository.kodi-ai-{ver}.zip      — installable repository addon
- dist/repo/addons.xml                   — repo manifest (Kodi reads this)
- dist/repo/addons.xml.md5
- dist/repo/service.kodi.ai/service.kodi.ai-{ver}.zip

Usage:
    python tools/build_repo.py
    python tools/build_repo.py --output dist/
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
import xml.etree.ElementTree as ET
import zipfile

REPO_ID = "repository.kodi-ai.stigmavlc"
REPO_NAME = "Kodi-AI Repository"
REPO_AUTHOR = "Ivan Aguilar Mari"
REPO_BASE_URL = "https://stigmavlc.github.io/Kodi-AI/repo"


def read_addon_version(addon_xml: str) -> tuple[str, str]:
    """Return (addon_id, version) from an addon.xml file."""
    tree = ET.parse(addon_xml)
    root = tree.getroot()
    return root.get("id"), root.get("version")


def zip_addon(src_dir: str, dest_zip: str) -> None:
    """Zip an addon directory, skipping caches/tests/junk."""
    skip_dirs = {"__pycache__", "tests", ".pytest_cache", ".git"}
    skip_files_ext = {".pyc", ".pyo"}
    skip_files = {".gitkeep", ".DS_Store"}
    with zipfile.ZipFile(dest_zip, "w", zipfile.ZIP_DEFLATED) as z:
        for root, dirs, files in os.walk(src_dir):
            dirs[:] = [d for d in dirs if d not in skip_dirs]
            for fn in files:
                if fn in skip_files or any(fn.endswith(e) for e in skip_files_ext):
                    continue
                full = os.path.join(root, fn)
                # Path inside zip is relative to the parent of src_dir so the
                # zip contains the addon dir at its root (Kodi convention).
                rel = os.path.relpath(full, os.path.dirname(src_dir))
                z.write(full, rel)


def make_repository_addon(out_dir: str, version: str) -> str:
    """Create a tiny repository addon pointing at REPO_BASE_URL and zip it."""
    repo_addon_dir = os.path.join(out_dir, REPO_ID)
    os.makedirs(repo_addon_dir, exist_ok=True)
    addon_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<addon id="{REPO_ID}" name="{REPO_NAME}" version="{version}" '
        f'provider-name="{REPO_AUTHOR}">\n'
        f'    <extension point="xbmc.addon.repository" name="{REPO_NAME}">\n'
        '        <dir>\n'
        f'            <info compressed="false">{REPO_BASE_URL}/addons.xml</info>\n'
        f'            <checksum>{REPO_BASE_URL}/addons.xml.md5</checksum>\n'
        f'            <datadir zip="true">{REPO_BASE_URL}/</datadir>\n'
        '        </dir>\n'
        '    </extension>\n'
        '    <extension point="xbmc.addon.metadata">\n'
        '        <summary lang="en_GB">Kodi-AI Repository</summary>\n'
        '        <description lang="en_GB">Repository providing the Kodi-AI service addon.</description>\n'
        '        <platform>all</platform>\n'
        '        <license>MIT</license>\n'
        '    </extension>\n'
        '</addon>\n'
    )
    with open(os.path.join(repo_addon_dir, "addon.xml"), "w", encoding="utf-8") as f:
        f.write(addon_xml)
    out_zip = os.path.join(out_dir, f"{REPO_ID}-{version}.zip")
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(os.path.join(repo_addon_dir, "addon.xml"), f"{REPO_ID}/addon.xml")
    return out_zip


def make_addons_xml(repo_dir: str, addon_xml_path: str) -> None:
    """Build addons.xml + addons.xml.md5 from a single addon's addon.xml."""
    with open(addon_xml_path, encoding="utf-8") as f:
        addon_xml_content = f.read()
    # Strip XML prolog so we can wrap inside <addons>.
    if addon_xml_content.startswith("<?xml"):
        addon_xml_content = addon_xml_content.split("?>", 1)[1].strip()
    full = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<addons>\n'
        + addon_xml_content
        + '\n</addons>\n'
    )
    addons_xml_path = os.path.join(repo_dir, "addons.xml")
    with open(addons_xml_path, "w", encoding="utf-8") as f:
        f.write(full)
    md5 = hashlib.md5(full.encode("utf-8")).hexdigest()
    with open(addons_xml_path + ".md5", "w", encoding="utf-8") as f:
        f.write(md5)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build Kodi-AI addon repository.")
    parser.add_argument("--output", default="dist", help="Output directory (default: dist)")
    args = parser.parse_args(argv)

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    addon_src = os.path.join(repo_root, "service.kodi.ai")
    addon_xml = os.path.join(addon_src, "addon.xml")
    if not os.path.exists(addon_xml):
        print(f"ERROR: addon.xml not found at {addon_xml}", file=sys.stderr)
        return 1

    addon_id, version = read_addon_version(addon_xml)
    out_dir = os.path.join(repo_root, args.output) if not os.path.isabs(args.output) else args.output
    repo_dir = os.path.join(out_dir, "repo")
    addon_repo_dir = os.path.join(repo_dir, addon_id)
    os.makedirs(addon_repo_dir, exist_ok=True)

    # 1. Build addon zip at dist/{id}-{ver}.zip
    addon_zip_name = f"{addon_id}-{version}.zip"
    addon_zip_path = os.path.join(out_dir, addon_zip_name)
    zip_addon(addon_src, addon_zip_path)
    print(f"Built addon: {addon_zip_path}")

    # 2. Mirror it into dist/repo/{id}/ for Kodi repo layout
    shutil.copy2(addon_zip_path, os.path.join(addon_repo_dir, addon_zip_name))
    for asset in ("icon.png", "fanart.jpg"):
        src = os.path.join(addon_src, asset)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(addon_repo_dir, asset))

    # 3. Generate addons.xml + .md5
    make_addons_xml(repo_dir, addon_xml)
    print(f"Generated repo manifest: {os.path.join(repo_dir, 'addons.xml')}")

    # 4. Build the repository addon (so users can one-shot install the repo)
    repo_zip = make_repository_addon(out_dir, version)
    print(f"Built repository addon: {repo_zip}")

    # 5. Small index.html so /repo/ is browsable
    with open(os.path.join(repo_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write(
            '<!doctype html><meta charset=utf-8><title>Kodi-AI Repo</title>'
            '<p>Kodi-AI add-on repository. <a href="../">Project README</a>.</p>'
        )

    print("\nDone. Install order on Kodi:")
    print(f"  1. Install repository.kodi-ai zip first: {os.path.basename(repo_zip)}")
    print(f"  2. Then Add-ons -> Install from repository -> {REPO_NAME} -> Services -> Kodi-AI")
    print(f"OR direct install: copy {addon_zip_name} to a USB stick and 'Install from zip file'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
