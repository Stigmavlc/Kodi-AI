"""extract_keys parsers per spec §4.6: flat-id, path-flatten with [N]
sibling indexing, JSON walker. Used by snapshot_manager for file_keys
staleness checks."""
from __future__ import annotations
import json
import os
import re
import xml.etree.ElementTree as ET


def _strip_ns(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def flat_id_parser(raw: bytes) -> dict[str, str]:
    """For settings.xml / addon.xml: <setting id='X' value='Y'/> → {X: Y}."""
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return {}
    out: dict[str, str] = {}
    for elem in root.iter():
        if _strip_ns(elem.tag) == "setting":
            sid = elem.get("id")
            if sid is not None:
                out[sid] = elem.get("value") or (elem.text or "")
    return out


def path_flatten_parser(raw: bytes) -> dict[str, str]:
    """Walk tree, emit path → value. Repeated siblings → path[N] zero-indexed."""
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return {}
    out: dict[str, str] = {}

    def walk(elem, path):
        children = list(elem)
        # Group children by tag for [N] indexing
        by_tag: dict[str, list] = {}
        for c in children:
            by_tag.setdefault(_strip_ns(c.tag), []).append(c)
        for tag, kids in by_tag.items():
            if len(kids) == 1:
                cp = f"{path}/{tag}"
                if list(kids[0]):
                    walk(kids[0], cp)
                else:
                    out[cp] = (kids[0].text or "").strip()
            else:
                for i, k in enumerate(kids):
                    cp = f"{path}/{tag}[{i}]"
                    if list(k):
                        walk(k, cp)
                    else:
                        out[cp] = (k.text or "").strip()

    walk(root, _strip_ns(root.tag))
    return out


def json_walker(raw: bytes) -> dict[str, any]:
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}
    out: dict[str, any] = {}

    def walk(obj, prefix):
        if isinstance(obj, dict):
            for k, v in obj.items():
                walk(v, f"{prefix}.{k}" if prefix else k)
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                walk(v, f"{prefix}[{i}]")
        else:
            out[prefix] = obj

    walk(data, "")
    return out


_PATH_REGISTRY = {
    "settings.xml": flat_id_parser,
    "addon.xml": flat_id_parser,
    "advancedsettings.xml": path_flatten_parser,
    "sources.xml": path_flatten_parser,
    "mediasources.xml": path_flatten_parser,
}


def parser_for_path(path: str):
    basename = os.path.basename(path)
    if basename in _PATH_REGISTRY:
        return _PATH_REGISTRY[basename]
    if basename.endswith(".json"):
        return json_walker
    return None
