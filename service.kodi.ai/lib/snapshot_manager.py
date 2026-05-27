# service.kodi.ai/lib/snapshot_manager.py
"""Snapshot create + staleness-validated restore.

Snapshots live OUTSIDE addon dir (Kodi-AI-snapshots/ under userdata/) so
they survive addon reinstall. LRU 100 snapshots / 200 MB cap.

Spec: §1.13, §5.4.
"""
from __future__ import annotations
import json
import os
import time
import secrets as _secrets
from dataclasses import dataclass, field
from typing import Any, Callable, Literal
from . import state_paths

MAX_SNAPSHOTS = 100
MAX_BYTES = 200 * 1024 * 1024
READ_BACK_DEADLINE_S = 2.0
MAX_TARGETS_PER_TOOL = 10


@dataclass(frozen=False)
class SnapshotTarget:
    kind: Literal["kodi_setting", "addon_setting", "file", "file_keys", "addon_state"]
    identifier: str
    read_back: Callable[[], Any]
    equality: Callable[[Any, Any], bool]
    extract_keys: Callable[[bytes], dict] | None = None


def _root() -> str:
    return state_paths.snapshots_path()


def _snap_dir(sid: str) -> str:
    return os.path.join(_root(), sid)


def create(*, label: str, targets: list[SnapshotTarget], session_id: str) -> str:
    if len(targets) > MAX_TARGETS_PER_TOOL:
        raise ValueError(f"too many snapshot targets ({len(targets)} > {MAX_TARGETS_PER_TOOL})")
    sid = "snap_" + _secrets.token_hex(6)
    d = _snap_dir(sid)
    os.makedirs(d, exist_ok=True)
    manifest = {"id": sid, "label": label, "session_id": session_id,
                "created_at": time.time(), "targets": []}
    for t in targets:
        try:
            # 2s soft deadline — for V1 the read_back functions are fast (in-memory
            # or single JSON-RPC). True deadline enforced via signal in Phase 7.
            value = t.read_back()
        except Exception as e:
            value = {"__read_back_error__": str(e)}
        manifest["targets"].append({
            "kind": t.kind, "identifier": t.identifier, "value": value,
        })
    with open(os.path.join(d, "manifest.json"), "w") as f:
        json.dump(manifest, f, separators=(",", ":"), default=str)
    _gc_lru()
    return sid


def restore(snapshot_id: str) -> tuple[bool, list[dict]]:
    """Restore snapshot. Returns (ok, stale_list).
    On stale: refuse auto-restore, return stale targets for user prompt."""
    d = _snap_dir(snapshot_id)
    mfp = os.path.join(d, "manifest.json")
    if not os.path.exists(mfp):
        return False, []
    with open(mfp) as f:
        manifest = json.load(f)
    # Stale check — caller MUST supply a re-resolution of read_back/equality
    # In V1: tools that create snapshots register their post-call read_back
    # in a side registry (lib/snapshot_runtime.py — Phase 7). For now:
    # equality is identity check (read_back returns recorded value → ok).
    # This is the contract the tool layer wires up.
    stale: list[dict] = []
    for t in manifest["targets"]:
        # The actual read_back is callable in-process; for cross-session
        # restore the caller must inject runtime resolvers. For V1: if no
        # runtime resolver, treat as "stale" (force user prompt).
        # See lib/snapshot_runtime.py (Phase 7) for the production wiring.
        resolver = _get_runtime_resolver(t["kind"], t["identifier"])
        if resolver is None:
            stale.append(t)
            continue
        try:
            current = resolver()
            if current != t["value"]:
                stale.append(t)
        except Exception:
            stale.append(t)
    if stale:
        return False, stale
    # Apply restoration
    for t in manifest["targets"]:
        applier = _get_runtime_applier(t["kind"], t["identifier"])
        if applier:
            applier(t["value"])
    return True, []


_RUNTIME_RESOLVERS: dict[tuple[str, str], Callable] = {}
_RUNTIME_APPLIERS: dict[tuple[str, str], Callable] = {}


def register_runtime_handlers(kind: str, identifier: str, *,
                              resolver: Callable, applier: Callable) -> None:
    _RUNTIME_RESOLVERS[(kind, identifier)] = resolver
    _RUNTIME_APPLIERS[(kind, identifier)] = applier


def _get_runtime_resolver(kind: str, identifier: str) -> Callable | None:
    return _RUNTIME_RESOLVERS.get((kind, identifier))


def _get_runtime_applier(kind: str, identifier: str) -> Callable | None:
    return _RUNTIME_APPLIERS.get((kind, identifier))


def list_snapshots(*, session_id: str | None = None, limit: int = 20) -> list[dict]:
    root = _root()
    if not os.path.exists(root):
        return []
    entries = []
    for name in os.listdir(root):
        if not name.startswith("snap_"):
            continue
        mfp = os.path.join(root, name, "manifest.json")
        if not os.path.exists(mfp):
            continue
        try:
            with open(mfp) as f:
                m = json.load(f)
        except Exception:
            continue
        if session_id and m.get("session_id") != session_id:
            continue
        entries.append({"id": name, "label": m.get("label"),
                        "created_at": m.get("created_at"),
                        "session_id": m.get("session_id")})
    entries.sort(key=lambda e: e.get("created_at", 0), reverse=True)
    return entries[:limit]


def _gc_lru() -> None:
    """Drop oldest snapshots over MAX_SNAPSHOTS or MAX_BYTES."""
    root = _root()
    if not os.path.exists(root):
        return
    snaps = [(name, os.path.join(root, name)) for name in os.listdir(root) if name.startswith("snap_")]
    snaps_sized = []
    for name, path in snaps:
        if not os.path.isdir(path):
            continue
        try:
            total = sum(os.path.getsize(os.path.join(path, f)) for f in os.listdir(path)
                        if os.path.isfile(os.path.join(path, f)))
            mtime = os.path.getmtime(path)
        except OSError:
            continue
        snaps_sized.append((mtime, total, name, path))
    snaps_sized.sort()
    while len(snaps_sized) > MAX_SNAPSHOTS or sum(s[1] for s in snaps_sized) > MAX_BYTES:
        if not snaps_sized:
            break
        _, _, _, path = snaps_sized.pop(0)
        import shutil
        shutil.rmtree(path, ignore_errors=True)
