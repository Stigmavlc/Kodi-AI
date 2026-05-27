"""Validate the Setup.xml WindowXMLDialog skin file.

Checks:
- XML is well-formed.
- All <texture>, <texturefocus>, <texturenofocus> elements point to files
  that exist on disk under the addon root.
- All integer control IDs are unique.
- The default focus is NOT the Cancel button (ID 9200).
"""
from __future__ import annotations
import os
import re
import xml.etree.ElementTree as ET

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ADDON_ROOT = os.path.normpath(os.path.join(HERE, "..", "..", "service.kodi.ai"))
SETUP_XML = os.path.join(ADDON_ROOT, "resources", "skins", "Default", "720p", "Setup.xml")


def test_setup_xml_exists():
    assert os.path.exists(SETUP_XML), f"Setup.xml not found at {SETUP_XML}"


def test_setup_xml_is_well_formed():
    # Raises ParseError on malformed XML.
    ET.parse(SETUP_XML)


def _iter_texture_paths(root: ET.Element):
    """Yield (element-tag, text) for every texture-bearing element."""
    for tag in ("texture", "texturefocus", "texturenofocus"):
        for el in root.iter(tag):
            text = (el.text or "").strip()
            if text:
                yield (tag, text)


def test_all_texture_paths_exist():
    tree = ET.parse(SETUP_XML)
    root = tree.getroot()
    missing = []
    for tag, path in _iter_texture_paths(root):
        # Must use the special://home/addons/service.kodi.ai/... pattern,
        # NOT skin-relative (e.g. DefaultButtonFocus.png — would break on
        # non-Estuary skins).
        assert path.startswith("special://home/addons/service.kodi.ai/"), (
            f"Texture path is not addon-rooted: <{tag}>{path}</{tag}>"
        )
        rel = path.replace("special://home/addons/service.kodi.ai/", "")
        on_disk = os.path.join(ADDON_ROOT, rel)
        if not os.path.exists(on_disk):
            missing.append((tag, path, on_disk))
    assert not missing, (
        "Missing texture files:\n" +
        "\n".join(f"  <{t}>{p}</{t}>  -> {full}" for t, p, full in missing)
    )


def test_all_control_ids_unique():
    tree = ET.parse(SETUP_XML)
    root = tree.getroot()
    seen = set()
    duplicates = []
    for el in root.iter("control"):
        cid = el.get("id")
        if not cid:
            continue
        # Only check integer IDs — non-integer IDs (e.g. "9110_icon") are
        # legal in skin XML but not addressable from Python.
        if not re.fullmatch(r"\d+", cid):
            continue
        if cid in seen:
            duplicates.append(cid)
        seen.add(cid)
    assert not duplicates, f"Duplicate control IDs: {duplicates}"


def test_default_focus_is_not_cancel_button():
    """An idle OK-press on a TV remote should NOT immediately cancel the
    dialog. The default focus must be a non-destructive control."""
    tree = ET.parse(SETUP_XML)
    root = tree.getroot()
    default = root.find("defaultcontrol")
    assert default is not None, "Setup.xml has no <defaultcontrol> — UX risk"
    default_id = (default.text or "").strip()
    assert default_id != "9200", "Default focus must NOT be the Cancel button"


def test_qr_image_uses_keep_aspectratio():
    """A squashed QR is unscannable. Image control 9100 must preserve
    aspect ratio for non-720p skins."""
    tree = ET.parse(SETUP_XML)
    root = tree.getroot()
    for el in root.iter("control"):
        if el.get("id") == "9100":
            ar = el.find("aspectratio")
            assert ar is not None and (ar.text or "").strip() == "keep"
            return
    pytest.fail("Setup.xml has no control with id=9100 (QR image)")


def test_no_skin_relative_textures():
    """Catch the classic Estuary-only failure mode."""
    with open(SETUP_XML, "r", encoding="utf-8") as f:
        content = f.read()
    forbidden = [
        "DefaultButtonFocus.png",
        "DefaultButtonNoFocus.png",
        "DefaultFocus.png",
    ]
    for name in forbidden:
        assert name not in content, (
            f"Setup.xml references skin-relative texture {name} — "
            "use special://home/addons/service.kodi.ai/resources/media/<file>.png instead."
        )


def test_step_labels_present():
    """The 4 step labels (9110-9113) must exist so the polling thread has
    something to update."""
    tree = ET.parse(SETUP_XML)
    root = tree.getroot()
    found = set()
    for el in root.iter("control"):
        cid = el.get("id")
        if cid in {"9110", "9111", "9112", "9113"}:
            found.add(cid)
    assert found == {"9110", "9111", "9112", "9113"}, (
        f"Step labels missing — found only {found}"
    )
