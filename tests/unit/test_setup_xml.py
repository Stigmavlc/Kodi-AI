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
    """Every <control id="..."> must be unique, INCLUDING non-integer IDs.

    B4: Kodi's atoi() truncates non-integer IDs (e.g. "9110_icon" -> 9110)
    which collides with `<control id="9110">`. The previous version of this
    test skipped non-integer IDs and would have missed exactly that bug.
    """
    tree = ET.parse(SETUP_XML)
    root = tree.getroot()
    seen = set()
    duplicates = []
    atoi_collisions = []
    for el in root.iter("control"):
        cid = el.get("id")
        if not cid:
            continue
        if cid in seen:
            duplicates.append(cid)
        seen.add(cid)
        # Catch atoi() truncation collisions: e.g. "9110_icon" -> "9110".
        m = re.match(r"^(\d+)", cid)
        if m:
            int_prefix = m.group(1)
            # Two controls with the same integer prefix are a Kodi
            # rendering hazard.
            atoi_collisions.append((cid, int_prefix))
    assert not duplicates, f"Duplicate control IDs: {duplicates}"

    # Check that no two controls share an atoi() prefix.
    by_prefix: dict = {}
    for cid, prefix in atoi_collisions:
        by_prefix.setdefault(prefix, []).append(cid)
    collisions = {p: ids for p, ids in by_prefix.items() if len(ids) > 1}
    assert not collisions, (
        f"Control IDs that atoi-collide (Kodi will undefined-render): "
        f"{collisions}"
    )


def test_default_focus_is_not_cancel_button():
    """An idle OK-press on a TV remote should NOT immediately cancel the
    dialog. The default focus must be a non-destructive control."""
    tree = ET.parse(SETUP_XML)
    root = tree.getroot()
    default = root.find("defaultcontrol")
    assert default is not None, "Setup.xml has no <defaultcontrol> — UX risk"
    default_id = (default.text or "").strip()
    assert default_id != "9200", "Default focus must NOT be the Cancel button"


def test_default_focus_is_focusable():
    """B3: defaultcontrol must point at a *focusable* control. Labels are
    not focusable in Kodi -- if defaultcontrol references a label, Kodi
    falls back to the first focusable control (which in this XML is the
    Cancel button 9200) and an idle OK-press dismisses the dialog."""
    tree = ET.parse(SETUP_XML)
    root = tree.getroot()
    default = root.find("defaultcontrol")
    assert default is not None
    default_id = (default.text or "").strip()
    focusable_types = {"button", "togglebutton", "radiobutton", "list",
                       "fixedlist", "wraplist", "panel", "edit"}
    matched = None
    for el in root.iter("control"):
        if el.get("id") == default_id:
            matched = el
            break
    assert matched is not None, (
        f"defaultcontrol references id={default_id} but no <control id={default_id}> exists"
    )
    ctype = (matched.get("type") or "").strip()
    assert ctype in focusable_types, (
        f"defaultcontrol id={default_id} is type={ctype!r} which is not focusable in Kodi; "
        f"Kodi will fall back to the first focusable control (likely Cancel)."
    )


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
