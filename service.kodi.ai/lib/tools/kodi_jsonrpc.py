# service.kodi.ai/lib/tools/kodi_jsonrpc.py
"""Raw JSON-RPC tool exposed to LLM (allowlist-only).

call() is the internal helper used by OTHER tools (kodi_addons,
kodi_settings, etc.) — bypasses allowlist because those tools enforce
their own contracts.

Spec: §4.3.
"""
from __future__ import annotations
import json
import xbmc
from . import tool, ToolResult


ALLOWLIST: set[str] = {
    "Addons.GetAddons", "Addons.GetAddonDetails",
    "Settings.GetSettings", "Settings.GetSettingValue", "Settings.GetCategories",
    "System.GetProperties", "Application.GetProperties",
    "Player.GetActivePlayers", "Player.GetItem", "Player.GetProperties", "Player.GetPlayers",
    "JSONRPC.Introspect", "JSONRPC.Permission", "JSONRPC.Version", "JSONRPC.Ping",
    "Files.GetDirectory", "Files.GetFileDetails", "Files.GetSources", "Files.PrepareDownload",
    "GUI.GetProperties",
    "Profiles.GetCurrentProfile", "Profiles.GetProfiles",
    "Textures.GetTextures",
    "PVR.GetProperties", "PVR.GetChannels", "PVR.GetClients",
}


def call(method: str, params: dict | None = None) -> dict:
    """Internal helper for other tools. NOT allowlisted (callers enforce safety)."""
    req = {"jsonrpc": "2.0", "method": method, "params": params or {}, "id": 1}
    raw = xbmc.executeJSONRPC(json.dumps(req))
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {"error": {"message": "invalid JSON-RPC response"}}


@tool(
    name="kodi_jsonrpc",
    description="Call a Kodi JSON-RPC method (read-only allowlist). See spec for allowed methods.",
    schema={
        "type": "object",
        "properties": {
            "method": {"type": "string"},
            "params": {"type": "object", "default": {}},
        },
        "required": ["method"],
    },
    tier="immediate",
    safety_class="read_only",
)
def kodi_jsonrpc(method: str, params: dict | None = None) -> ToolResult:
    if method not in ALLOWLIST:
        return ToolResult(
            success=False, requested=f"kodi_jsonrpc({method})",
            output=None, actual_state_after=None,
            error=f"method '{method}' not allowlisted; use typed tool or request §4 allowlist extension",
            snapshot_id=None, cost_seconds=0.0,
        )
    res = call(method, params or {})
    err = res.get("error")
    if err:
        return ToolResult(success=False, requested=f"kodi_jsonrpc({method})",
                          output=None, actual_state_after=None,
                          error=str(err), snapshot_id=None, cost_seconds=0.0)
    return ToolResult(success=True, requested=f"kodi_jsonrpc({method})",
                      output=res.get("result"), actual_state_after=None,
                      error=None, snapshot_id=None, cost_seconds=0.0)
