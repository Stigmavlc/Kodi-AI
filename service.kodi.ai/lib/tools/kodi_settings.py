# service.kodi.ai/lib/tools/kodi_settings.py
"""Kodi settings + addon settings tools per spec §4.6.

V1 scope:
  - get_kodi_setting / set_kodi_setting use Settings.Get/SetSettingValue + read-back.
  - get_addon_setting / set_addon_setting use xbmcaddon.Addon (enabled-addon path
    only). Disabled-addon xmlparse path is deferred (see spec §4.6 "set_addon_setting
    enabled-vs-disabled path" — type-aware xbmcvfs write to settings.xml).
  - DISRUPTIVE_KODI_SETTINGS / CROSS_ADDON_SETTINGS_PREFIXES drive the
    disruptive(args) and target_addons(args) callables.
"""
from __future__ import annotations
import xbmcaddon
from .kodi_jsonrpc import call as jrpc
from . import tool, ToolResult


# Settings that are disruptive (cause restart/reconfig). Mirrors spec §4.6:
# "DISRUPTIVE_KODI_SETTINGS = videoplayer.*, audiooutput.*, videoscreen.*,
# lookandfeel.skin, general.cache*". V1 lists the explicit IDs that have been
# observed in field reports; broad-prefix matching can land in a later
# refinement once the LLM produces real evidence.
DISRUPTIVE_KODI_SETTINGS = {
    "videoplayer.useamcodec",
    "audiooutput.audiodevice",
    "audiooutput.passthrough",
    "lookandfeel.skin",
}

# Cross-addon settings (affect many addons → target_addons=ALL).
CROSS_ADDON_SETTINGS_PREFIXES = ("services.", "general.", "lookandfeel.", "audiooutput.")


def _is_cross_addon(sid: str) -> bool:
    return any(sid.startswith(p) for p in CROSS_ADDON_SETTINGS_PREFIXES)


def _kodi_setting_disruptive(args: dict) -> bool:
    return args.get("setting_id", "") in DISRUPTIVE_KODI_SETTINGS


def _kodi_setting_targets(args: dict):
    sid = args.get("setting_id", "")
    if _is_cross_addon(sid):
        return "ALL"
    return set()


@tool(
    name="get_kodi_setting",
    description="Get a Kodi global setting value.",
    schema={"type": "object",
            "properties": {"setting_id": {"type": "string"}},
            "required": ["setting_id"]},
    tier="immediate", safety_class="read_only",
)
def get_kodi_setting(setting_id: str) -> ToolResult:
    r = jrpc("Settings.GetSettingValue", {"setting": setting_id})
    if "error" in r:
        return ToolResult(success=False,
                          requested=f"get_kodi_setting({setting_id})",
                          output=None, actual_state_after=None,
                          error=str(r["error"]),
                          snapshot_id=None, cost_seconds=0.0)
    value = r.get("result", {}).get("value")
    return ToolResult(success=True,
                      requested=f"get_kodi_setting({setting_id})",
                      output=value,
                      actual_state_after={"value": value},
                      error=None,
                      snapshot_id=None, cost_seconds=0.0)


@tool(
    name="set_kodi_setting",
    description=("Set a Kodi global setting. Disruptive for video/audio/skin "
                 "settings; target_addons='ALL' for cross-addon prefixes."),
    schema={"type": "object",
            "properties": {"setting_id": {"type": "string"}, "value": {}},
            "required": ["setting_id", "value"]},
    tier="confirm",
    disruptive=_kodi_setting_disruptive,
    target_addons=_kodi_setting_targets,
)
def set_kodi_setting(setting_id: str, value) -> ToolResult:
    r = jrpc("Settings.SetSettingValue",
             {"setting": setting_id, "value": value})
    if "error" in r:
        return ToolResult(success=False,
                          requested=f"set_kodi_setting({setting_id})",
                          output=None, actual_state_after=None,
                          error=str(r["error"]),
                          snapshot_id=None, cost_seconds=0.0)
    # Read-back verify.
    rb = jrpc("Settings.GetSettingValue", {"setting": setting_id})
    new_val = rb.get("result", {}).get("value")
    ok = new_val == value
    return ToolResult(
        success=ok,
        requested=f"set_kodi_setting({setting_id})",
        output=None,
        actual_state_after={"value": new_val},
        error=None if ok else f"verify mismatch: got {new_val!r}",
        snapshot_id=None, cost_seconds=0.0,
    )


@tool(
    name="get_addon_setting",
    description=("Get an addon's setting via xbmcaddon.Addon. V1 supports the "
                 "enabled-addon path; disabled-addon xmlparse merge is deferred."),
    schema={"type": "object",
            "properties": {"addon_id": {"type": "string"},
                           "key": {"type": "string"}},
            "required": ["addon_id", "key"]},
    tier="immediate", safety_class="read_only",
)
def get_addon_setting(addon_id: str, key: str) -> ToolResult:
    try:
        val = xbmcaddon.Addon(addon_id).getSetting(key)
        return ToolResult(success=True,
                          requested=f"get_addon_setting({addon_id}.{key})",
                          output=val,
                          actual_state_after={"value": val},
                          error=None,
                          snapshot_id=None, cost_seconds=0.0)
    except Exception as e:
        return ToolResult(success=False,
                          requested=f"get_addon_setting({addon_id}.{key})",
                          output=None, actual_state_after=None,
                          error=str(e),
                          snapshot_id=None, cost_seconds=0.0)


@tool(
    name="set_addon_setting",
    description=("Set an addon's setting (persists across restarts). V1 supports "
                 "the enabled-addon path via xbmcaddon.Addon; disabled-addon "
                 "type-aware xmlparse write is deferred."),
    schema={"type": "object",
            "properties": {"addon_id": {"type": "string"},
                           "key": {"type": "string"},
                           "value": {}},
            "required": ["addon_id", "key", "value"]},
    tier="confirm",
    target_addons=lambda args: {args.get("addon_id", "")},
)
def set_addon_setting(addon_id: str, key: str, value) -> ToolResult:
    try:
        xbmcaddon.Addon(addon_id).setSetting(key, str(value))
        # Read-back verify.
        new_val = xbmcaddon.Addon(addon_id).getSetting(key)
        ok = new_val == str(value)
        return ToolResult(
            success=ok,
            requested=f"set_addon_setting({addon_id}.{key})",
            output=None,
            actual_state_after={"value": new_val},
            error=None if ok else f"verify mismatch: got {new_val!r}",
            snapshot_id=None, cost_seconds=0.0,
        )
    except Exception as e:
        return ToolResult(success=False,
                          requested=f"set_addon_setting({addon_id}.{key})",
                          output=None, actual_state_after=None,
                          error=str(e),
                          snapshot_id=None, cost_seconds=0.0)
