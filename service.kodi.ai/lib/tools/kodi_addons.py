# service.kodi.ai/lib/tools/kodi_addons.py
"""Addon mutation tools per spec §4.6.

list_addons / get_addon_details (read-only).
install/uninstall/enable/disable/restart/update (mutation w/ snapshot+verify).
clear_addon_cache (folded restart, immediate+disruptive_callable).
"""
from __future__ import annotations
import os
import shutil
import time
from .kodi_jsonrpc import call as jrpc
import xbmc
from . import tool, ToolResult


# ---- builtin_with_verify helper ----
def builtin_with_verify(builtin: str, verify, timeout_s: float = 10.0) -> bool:
    from ..concurrency import abort_event
    xbmc.executebuiltin(builtin)
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if abort_event.wait(0.25):
            return False
        try:
            if verify():
                return True
        except Exception:
            pass
    return False


# ---- helpers ----
def _addon_details(addon_id: str) -> dict | None:
    r = jrpc("Addons.GetAddonDetails", {
        "addonid": addon_id,
        "properties": ["version", "enabled", "broken", "path", "dependencies", "name"],
    })
    if "error" in r:
        return None
    return r.get("result", {}).get("addon")


def addon_owns_active_player(addon_id: str) -> bool:
    pp = jrpc("Player.GetActivePlayers", {})
    if pp.get("result"):
        item = jrpc("Player.GetItem", {"playerid": pp["result"][0]["playerid"],
                                        "properties": []})
        return (item.get("result", {}).get("item", {}).get("addon") == addon_id)
    return False


# ---- list_addons ----
@tool(
    name="list_addons", description="List installed addons. enabled=None returns ALL (use for disabled-dep diagnosis); broken=None returns all incl broken.",
    schema={"type": "object", "properties": {
        "type": {"type": ["string", "null"]},
        "enabled": {"type": ["boolean", "null"], "default": None},
        "broken": {"type": ["boolean", "null"], "default": None},
    }},
    tier="immediate", safety_class="read_only",
)
def list_addons(type=None, enabled=None, broken=None) -> ToolResult:
    params = {"properties": ["version", "enabled", "broken", "path", "name"]}
    if type: params["type"] = type
    # Note: Kodi defaults enabled=True; explicitly pass when caller wants ALL
    if enabled is not None: params["enabled"] = enabled
    r = jrpc("Addons.GetAddons", params)
    if "error" in r:
        return ToolResult(success=False, requested="list_addons", output=None,
                          actual_state_after=None, error=str(r["error"]),
                          snapshot_id=None, cost_seconds=0.0)
    return ToolResult(success=True, requested="list_addons",
                      output=r.get("result", {}).get("addons", []),
                      actual_state_after=None, error=None,
                      snapshot_id=None, cost_seconds=0.0)


# ---- get_addon_details ----
@tool(
    name="get_addon_details", description="Full addon info: version, enabled, broken, path, dependencies.",
    schema={"type": "object", "properties": {"addon_id": {"type": "string"}}, "required": ["addon_id"]},
    tier="immediate", safety_class="read_only",
)
def get_addon_details(addon_id: str) -> ToolResult:
    a = _addon_details(addon_id)
    if a is None:
        return ToolResult(success=False, requested=f"get_addon_details({addon_id})",
                          output=None, actual_state_after=None, error="not found",
                          snapshot_id=None, cost_seconds=0.0)
    return ToolResult(success=True, requested=f"get_addon_details({addon_id})",
                      output=a, actual_state_after=None, error=None,
                      snapshot_id=None, cost_seconds=0.0)


# ---- enable_addon ----
@tool(
    name="enable_addon", description="Enable an installed addon.",
    schema={"type": "object", "properties": {"addon_id": {"type": "string"}}, "required": ["addon_id"]},
    tier="immediate",
    target_addons=lambda args: {args.get("addon_id")},
)
def enable_addon(addon_id: str) -> ToolResult:
    ok = builtin_with_verify(
        f"EnableAddon({addon_id})",
        verify=lambda: (_addon_details(addon_id) or {}).get("enabled") is True,
        timeout_s=10,
    )
    a = _addon_details(addon_id) or {}
    return ToolResult(
        success=ok, requested=f"enable_addon({addon_id})",
        output=None,
        actual_state_after={"enabled": a.get("enabled"), "version": a.get("version")},
        error=None if ok else "EnableAddon did not produce enabled=True within 10s",
        snapshot_id=None, cost_seconds=0.0,
    )


# ---- disable_addon ----
def _disruptive_when_owns_player(args: dict) -> bool:
    aid = args.get("addon_id", "")
    return addon_owns_active_player(aid)


@tool(
    name="disable_addon", description="Disable an installed addon.",
    schema={"type": "object", "properties": {"addon_id": {"type": "string"}}, "required": ["addon_id"]},
    tier="confirm",
    disruptive=_disruptive_when_owns_player,
    target_addons=lambda args: {args.get("addon_id")},
)
def disable_addon(addon_id: str) -> ToolResult:
    ok = builtin_with_verify(
        f"DisableAddon({addon_id})",
        verify=lambda: (_addon_details(addon_id) or {}).get("enabled") is False,
        timeout_s=10,
    )
    a = _addon_details(addon_id) or {}
    return ToolResult(success=ok, requested=f"disable_addon({addon_id})",
                      output=None,
                      actual_state_after={"enabled": a.get("enabled")},
                      error=None if ok else "DisableAddon did not produce enabled=False within 10s",
                      snapshot_id=None, cost_seconds=0.0)


# ---- restart_addon (alias for our purposes: disable+enable) ----
def _restart_disruptive_fn(args: dict) -> bool:
    return _disruptive_when_owns_player(args)


@tool(
    name="restart_addon", description="Disable + enable an addon to restart it (picks up cache clears, settings changes).",
    schema={"type": "object", "properties": {"addon_id": {"type": "string"}}, "required": ["addon_id"]},
    tier="immediate",
    disruptive=_restart_disruptive_fn,
    target_addons=lambda args: {args.get("addon_id")},
)
def restart_addon(addon_id: str) -> ToolResult:
    r1 = disable_addon(addon_id=addon_id)
    if not r1.success:
        return ToolResult(success=False, requested=f"restart_addon({addon_id})",
                          output=None, actual_state_after=r1.actual_state_after,
                          error=f"disable failed: {r1.error}",
                          snapshot_id=None, cost_seconds=0.0)
    r2 = enable_addon(addon_id=addon_id)
    return ToolResult(success=r2.success, requested=f"restart_addon({addon_id})",
                      output=None, actual_state_after=r2.actual_state_after,
                      error=r2.error, snapshot_id=None, cost_seconds=0.0)


# ---- install_addon (with deferred dep_closure target_addons) ----
def _install_target_addons(args: dict) -> set[str]:
    aid = args.get("addon_id", "")
    seen = {aid}
    stack = [aid]
    while stack:
        cur = stack.pop()
        a = _addon_details(cur)
        for d in (a or {}).get("dependencies", []):
            did = d.get("addonid")
            if did and did not in seen:
                seen.add(did); stack.append(did)
    return seen


@tool(
    name="install_addon", description="Install an addon from an already-installed repository (recursively pulls deps).",
    schema={"type": "object", "properties": {"addon_id": {"type": "string"}}, "required": ["addon_id"]},
    tier="confirm",
    target_addons=_install_target_addons,
)
def install_addon(addon_id: str) -> ToolResult:
    ok = builtin_with_verify(
        f"InstallAddon({addon_id})",
        verify=lambda: (_addon_details(addon_id) or {}).get("installed", False)
                       and (_addon_details(addon_id) or {}).get("enabled", False),
        timeout_s=60,
    )
    a = _addon_details(addon_id) or {}
    return ToolResult(success=ok, requested=f"install_addon({addon_id})",
                      output=None,
                      actual_state_after={"enabled": a.get("enabled"),
                                          "installed": a.get("installed"),
                                          "version": a.get("version")},
                      error=None if ok else "InstallAddon did not complete within 60s",
                      snapshot_id=None, cost_seconds=0.0)


# ---- uninstall_addon, update_addon, clear_addon_cache ----
# Pattern repeats; implementation analogous to install/disable. Per spec §4.6:
# - uninstall: tier=confirm, disruptive=owns_player, target_addons={addon_id}
# - update_addon: pre-fetch old version, call UpdateAddon(), verify version changed OR
#   no recurrence in 60s → success "already at latest or repo unreachable" (with warning)
# - clear_addon_cache: tier=immediate, disruptive=owns_player. Delete
#   addon_data/<id>/cache/ + <install_path>/__pycache__/, then restart_addon().

# (Full implementations land in Task 7.4 — same pattern as above.)
