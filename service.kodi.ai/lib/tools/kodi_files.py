# service.kodi.ai/lib/tools/kodi_files.py
"""File-read and file-write tools per spec §4.6.

read_log/read_log_old: tail kodi.log / kodi.old.log with optional level/addon
filters (last ~256KB scanned to bound memory; truncated to `lines`).
write_file/delete_file: path restricted to special://profile/, userdata/,
or temp/. Writes go through state_paths.atomic_write for crash-safety.

Spec: §4.6.
"""
from __future__ import annotations
import os
from .. import state_paths
from . import tool, ToolResult


_ALLOWED_PREFIXES = ("special://profile/", "special://userdata/", "special://temp/")


def _check_path_allowed(path: str) -> str | None:
    if not any(path.startswith(p) for p in _ALLOWED_PREFIXES):
        return f"path '{path}' not under allowed prefixes (profile/userdata/temp)"
    return None


def _tail_log(path: str, lines: int, level: str | None, addon: str | None) -> ToolResult:
    if not os.path.exists(path):
        return ToolResult(
            success=True, requested=f"read_log({path})",
            output={"lines": [], "path": path, "note": "log file not present"},
            actual_state_after=None, error=None,
            snapshot_id=None, cost_seconds=0.0,
        )
    try:
        with open(path, "rb") as f:
            # Read last ~256KB and decode — bounds memory while still
            # giving enough context for tail/filter operations.
            f.seek(0, 2)
            size = f.tell()
            start = max(0, size - 256 * 1024)
            f.seek(start)
            text = f.read(size - start).decode("utf-8", errors="replace")
    except OSError as e:
        return ToolResult(
            success=False, requested=f"read_log({path})",
            output=None, actual_state_after=None, error=str(e),
            snapshot_id=None, cost_seconds=0.0,
        )
    all_lines = text.splitlines()
    if level:
        all_lines = [l for l in all_lines if level.upper() in l.upper()]
    if addon:
        all_lines = [l for l in all_lines if f"[{addon}]" in l or addon in l]
    selected = all_lines[-lines:] if lines > 0 else all_lines
    return ToolResult(
        success=True, requested=f"read_log({path})",
        output={"lines": selected, "path": path, "total": len(all_lines)},
        actual_state_after=None, error=None,
        snapshot_id=None, cost_seconds=0.0,
    )


@tool(
    name="read_log",
    description="Read tail of kodi.log. Optional filters: level, addon name, line count.",
    schema={
        "type": "object",
        "properties": {
            "lines": {"type": "integer", "default": 200},
            "level": {"type": ["string", "null"]},
            "addon": {"type": ["string", "null"]},
        },
    },
    tier="immediate", safety_class="read_only",
)
def read_log(lines: int = 200, level: str | None = None, addon: str | None = None) -> ToolResult:
    return _tail_log(state_paths.log_path(), lines, level, addon)


@tool(
    name="read_log_old",
    description="Read tail of kodi.old.log (previous-session diagnosis).",
    schema={
        "type": "object",
        "properties": {
            "lines": {"type": "integer", "default": 200},
            "level": {"type": ["string", "null"]},
            "addon": {"type": ["string", "null"]},
        },
    },
    tier="immediate", safety_class="read_only",
)
def read_log_old(lines: int = 200, level: str | None = None, addon: str | None = None) -> ToolResult:
    return _tail_log(state_paths.old_log_path(), lines, level, addon)


@tool(
    name="write_file",
    description="Write bytes to a path under special://profile/, userdata/, or temp/. Atomic.",
    schema={
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
        },
        "required": ["path", "content"],
    },
    tier="confirm",
)
def write_file(path: str, content: str) -> ToolResult:
    err = _check_path_allowed(path)
    if err:
        return ToolResult(
            success=False, requested=f"write_file({path})",
            output=None, actual_state_after=None, error=err,
            snapshot_id=None, cost_seconds=0.0,
        )
    try:
        import xbmcvfs
        resolved = xbmcvfs.translatePath(path)
        state_paths.atomic_write(resolved, content.encode("utf-8"))
        return ToolResult(
            success=True, requested=f"write_file({path})",
            output={"path": path, "bytes": len(content.encode("utf-8"))},
            actual_state_after={"size": len(content.encode("utf-8"))},
            error=None, snapshot_id=None, cost_seconds=0.0,
        )
    except Exception as e:
        return ToolResult(
            success=False, requested=f"write_file({path})",
            output=None, actual_state_after=None, error=str(e),
            snapshot_id=None, cost_seconds=0.0,
        )


@tool(
    name="delete_file",
    description="Delete file at path under special://profile/, userdata/, or temp/.",
    schema={
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    },
    tier="confirm",
)
def delete_file(path: str) -> ToolResult:
    err = _check_path_allowed(path)
    if err:
        return ToolResult(
            success=False, requested=f"delete_file({path})",
            output=None, actual_state_after=None, error=err,
            snapshot_id=None, cost_seconds=0.0,
        )
    try:
        import xbmcvfs
        resolved = xbmcvfs.translatePath(path)
        if os.path.exists(resolved):
            os.remove(resolved)
        return ToolResult(
            success=True, requested=f"delete_file({path})",
            output={"path": path}, actual_state_after={"exists": False},
            error=None, snapshot_id=None, cost_seconds=0.0,
        )
    except Exception as e:
        return ToolResult(
            success=False, requested=f"delete_file({path})",
            output=None, actual_state_after=None, error=str(e),
            snapshot_id=None, cost_seconds=0.0,
        )
