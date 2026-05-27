# service.kodi.ai/lib/recovery.py
"""Boot recovery + LKG ZIP + orphan snapshot quarantine.
Spec §5.4, §7.4, §7.7. PRAGMATIC V1.
"""
from __future__ import annotations
import os
import time
import zipfile
from . import state_paths, reasoner_state, health
from .concurrency import paused_sessions, paused_sessions_lock


def maybe_rotate_lkg() -> bool:
    state = health.get_state()
    if (time.time() - state.get("crash_free_since", 0)) < 86400:
        return False
    if state.get("telegram_last_rt_ok_ts", 0) == 0:
        return False
    addon_root = state_paths.profile_path("")
    if not os.path.exists(addon_root):
        return False
    lkg_dir = state_paths.profile_path("lkg")
    os.makedirs(lkg_dir, exist_ok=True)
    out_path = os.path.join(lkg_dir, f"last_known_good-{int(time.time())}.zip")
    try:
        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
            for root, dirs, files in os.walk(addon_root):
                if "lkg" in dirs:
                    dirs.remove("lkg")
                if "sessions" in dirs:
                    dirs.remove("sessions")
                for fn in files:
                    full = os.path.join(root, fn)
                    rel = os.path.relpath(full, addon_root)
                    z.write(full, f"service.kodi.ai/{rel}")
    except Exception:
        return False
    # Keep last 2
    zips = sorted([f for f in os.listdir(lkg_dir) if f.startswith("last_known_good-")])
    for old in zips[:-2]:
        try:
            os.remove(os.path.join(lkg_dir, old))
        except OSError:
            pass
    return True


def boot_recovery_sessions(send_message_callable=None) -> dict:
    summary = {"resumed": 0, "expired": 0, "completed_cleaned": 0, "leftovers": 0}
    now = time.time()
    for sid in reasoner_state.list_all():
        st = reasoner_state.load(sid)
        if st is None:
            continue
        ts = st.terminal_state or "paused"
        if ts == "paused":
            if (now - st.paused_at) > 86400:
                st.terminal_state = "expired"
                reasoner_state.persist(st)
                summary["expired"] += 1
            else:
                with paused_sessions_lock:
                    paused_sessions[sid] = st
                summary["resumed"] += 1
        elif ts == "fix_complete":
            reasoner_state.unlink(sid)
            summary["completed_cleaned"] += 1
        else:
            summary["leftovers"] += 1
    return summary


def quarantine_orphan_snapshots() -> int:
    try:
        from .snapshot_manager import list_snapshots
    except Exception:
        return 0
    snaps_root = state_paths.snapshots_path()
    if not os.path.exists(snaps_root):
        return 0
    orphaned_dir = state_paths.snapshots_path(".orphaned")
    os.makedirs(orphaned_dir, exist_ok=True)
    with paused_sessions_lock:
        active = set(paused_sessions.keys())
    moved = 0
    for snap in list_snapshots(limit=1000):
        if snap.get("session_id") in active:
            continue
        d = os.path.join(snaps_root, snap["id"])
        if os.path.isdir(d):
            try:
                import shutil
                shutil.move(d, os.path.join(orphaned_dir, snap["id"]))
                moved += 1
            except OSError:
                pass
    return moved
