"""Append-only JSONL audit log with rotation at 10 MB × 5 files.

Schema:
  {
    "ts": ISO-8601 UTC,
    "event": str,  # tool_call | llm_call | session_start | ... (see spec §5.3)
    "session_id": str | None,
    "details": dict,
    "redacted": list[str]  # JSONPath-style keys redacted in details
  }

Spec: §5.3.
"""
from __future__ import annotations
import json
import os
import threading
from datetime import datetime, timezone
from . import state_paths

_LOCK = threading.Lock()
_ROTATION_BYTES = 10 * 1024 * 1024  # 10 MB
_MAX_ROTATIONS = 5


def _audit_dir() -> str:
    return state_paths.profile_path("audit")


def _current_path() -> str:
    return os.path.join(_audit_dir(), "audit.jsonl")


def _rotated_path(n: int) -> str:
    return os.path.join(_audit_dir(), f"audit.{n}.jsonl")


def _rotate_if_needed() -> None:
    path = _current_path()
    try:
        size = os.path.getsize(path)
    except FileNotFoundError:
        return
    if size < _ROTATION_BYTES:
        return
    # Shift audit.{N-1}.jsonl → audit.{N}.jsonl, drop the oldest.
    oldest = _rotated_path(_MAX_ROTATIONS)
    if os.path.exists(oldest):
        os.remove(oldest)
    for n in range(_MAX_ROTATIONS - 1, 0, -1):
        src = _rotated_path(n)
        if os.path.exists(src):
            os.rename(src, _rotated_path(n + 1))
    os.rename(path, _rotated_path(1))


def write(
    event: str,
    *,
    session_id: str | None = None,
    details: dict | None = None,
    redacted: list[str] | None = None,
) -> None:
    """Append one audit entry. Thread-safe."""
    record = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "event": event,
        "session_id": session_id,
        "details": details or {},
        "redacted": redacted or [],
    }
    line = json.dumps(record, separators=(",", ":"), ensure_ascii=False) + "\n"
    with _LOCK:
        os.makedirs(_audit_dir(), exist_ok=True)
        _rotate_if_needed()
        with open(_current_path(), "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()


# ---- Higher-level helpers with built-in redaction ----
from . import redactor as _redactor


def write_tool_call(
    tool_name: str,
    args: dict,
    *,
    success: bool,
    duration_ms: int,
    snapshot_id: str | None = None,
    session_id: str | None = None,
    error: str | None = None,
) -> None:
    """Write a tool_call audit entry with secret-pair redaction.

    For tools touching (addon_id, key, value) tuples where key is a known
    secret, redact the WHOLE pair, not just the value.
    """
    redacted_keys: list[str] = []
    redacted_args = dict(args)
    addon_id = args.get("addon_id")
    key = args.get("key")
    value = args.get("value")
    if (
        tool_name in ("set_addon_setting", "get_addon_setting")
        and addon_id and key
        and _redactor.should_redact_value(addon_id, key, value)
    ):
        redacted_args["addon_id"] = "<redacted-secret-addon>"
        redacted_args["key"] = "<known-secret-key>"
        redacted_args["value"] = "<redacted>"
        redacted_keys = ["args.addon_id", "args.key", "args.value"]
    # Apply pattern-based redact() to any remaining string values
    for k, v in redacted_args.items():
        if isinstance(v, str):
            new = _redactor.redact(v)
            if new != v:
                redacted_args[k] = new
                if f"args.{k}" not in redacted_keys:
                    redacted_keys.append(f"args.{k}")

    details = {
        "tool_name": tool_name,
        "args": redacted_args,
        "success": success,
        "duration_ms": duration_ms,
    }
    if snapshot_id is not None:
        details["snapshot_id"] = snapshot_id
    if error is not None:
        details["error"] = _redactor.redact(error)
        if details["error"] != error:
            redacted_keys.append("error")

    write("tool_call", session_id=session_id, details=details, redacted=redacted_keys)
