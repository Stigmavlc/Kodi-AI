"""Concurrent-writer stress test for lib.audit_log fcntl locking.

Skipped on non-POSIX. The spec doesn't require Windows-side cross-process
coordination because the addon ships only on Android/Linux.
"""
from __future__ import annotations
import json
import os
import sys
import threading
from unittest import mock

import pytest


@pytest.fixture(autouse=True)
def mock_paths(tmp_path, monkeypatch):
    fake_xbmcvfs = mock.MagicMock()
    fake_xbmcvfs.translatePath.side_effect = lambda p: str(tmp_path / p.replace("special://", ""))
    fake_xbmcvfs.mkdirs.side_effect = lambda p: (
        os.makedirs(fake_xbmcvfs.translatePath(p), exist_ok=True) or True
    )
    monkeypatch.setitem(sys.modules, "xbmcvfs", fake_xbmcvfs)
    if "lib.state_paths" in sys.modules:
        monkeypatch.setattr(sys.modules["lib.state_paths"], "xbmcvfs", fake_xbmcvfs)
    from lib import state_paths
    state_paths.ensure_dirs()
    yield


@pytest.mark.skipif(sys.platform.startswith("win"), reason="fcntl is POSIX-only")
def test_concurrent_writers_produce_all_valid_lines():
    """4 threads × 25 entries each → 100 valid JSON lines, no torn writes."""
    from lib import audit_log, state_paths

    N_THREADS = 4
    N_PER_THREAD = 25

    def _worker(tid: int) -> None:
        for i in range(N_PER_THREAD):
            audit_log.write(
                "stress",
                session_id=f"t{tid}",
                # Large enough to expose torn-write race conditions on
                # platforms whose fcntl is a no-op (we still want >4KB
                # of payload occasionally to overflow internal pipes).
                details={"i": i, "payload": "x" * 256},
            )

    threads = [threading.Thread(target=_worker, args=(t,)) for t in range(N_THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    path = state_paths.profile_path("audit/audit.jsonl")
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    expected_total = N_THREADS * N_PER_THREAD
    assert len(lines) == expected_total, (
        f"Expected {expected_total} lines, got {len(lines)}"
    )
    # Every line must parse as valid JSON.
    parsed = []
    for ln in lines:
        obj = json.loads(ln)  # raises on torn write
        parsed.append(obj)
    # Every thread/index combination must appear exactly once.
    pairs = {(p["session_id"], p["details"]["i"]) for p in parsed}
    expected_pairs = {(f"t{t}", i) for t in range(N_THREADS) for i in range(N_PER_THREAD)}
    assert pairs == expected_pairs
