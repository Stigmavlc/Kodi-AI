# tests/integration/test_tool_kodi_settings.py
"""Integration tests for kodi_settings tools (Task 7.5)."""
import json
import sys
import pytest
from unittest import mock


@pytest.fixture
def fake_kodi_settings(monkeypatch):
    state = {
        "kodi_settings": {"lookandfeel.skin": "skin.estuary"},
        "addons": {"plugin.video.seren": {"a": "x", "b": "y"}},
    }
    xbmc = mock.MagicMock()

    def jsonrpc(req_str):
        req = json.loads(req_str)
        m = req["method"]
        p = req.get("params") or {}
        if m == "Settings.GetSettingValue":
            return json.dumps({"result": {"value": state["kodi_settings"].get(p["setting"])}})
        if m == "Settings.SetSettingValue":
            state["kodi_settings"][p["setting"]] = p["value"]
            return json.dumps({"result": True})
        return json.dumps({"result": None})

    xbmc.executeJSONRPC.side_effect = jsonrpc

    xbmcaddon = mock.MagicMock()

    class FakeAddon:
        def __init__(self, aid):
            self.aid = aid

        def getSetting(self, k):
            return state["addons"].get(self.aid, {}).get(k, "")

        def setSetting(self, k, v):
            state["addons"].setdefault(self.aid, {})[k] = str(v)

    xbmcaddon.Addon.side_effect = FakeAddon

    monkeypatch.setitem(sys.modules, "xbmc", xbmc)
    monkeypatch.setitem(sys.modules, "xbmcaddon", xbmcaddon)
    # Re-bind cached module references so tools see the fresh fake.
    if "lib.tools.kodi_jsonrpc" in sys.modules:
        monkeypatch.setattr(sys.modules["lib.tools.kodi_jsonrpc"], "xbmc", xbmc)
    if "lib.tools.kodi_settings" in sys.modules:
        monkeypatch.setattr(sys.modules["lib.tools.kodi_settings"], "xbmcaddon", xbmcaddon)
    return state


@pytest.mark.integration
def test_get_kodi_setting(fake_kodi_settings):
    from lib.tools.kodi_settings import get_kodi_setting
    res = get_kodi_setting(setting_id="lookandfeel.skin")
    assert res.success
    assert res.output == "skin.estuary"


@pytest.mark.integration
def test_set_kodi_setting_round_trip(fake_kodi_settings):
    from lib.tools.kodi_settings import set_kodi_setting
    res = set_kodi_setting(setting_id="lookandfeel.skin", value="skin.confluence")
    assert res.success
    assert fake_kodi_settings["kodi_settings"]["lookandfeel.skin"] == "skin.confluence"


@pytest.mark.integration
def test_get_addon_setting(fake_kodi_settings):
    from lib.tools.kodi_settings import get_addon_setting
    res = get_addon_setting(addon_id="plugin.video.seren", key="a")
    assert res.success
    assert res.output == "x"


@pytest.mark.integration
def test_set_addon_setting_round_trip(fake_kodi_settings):
    from lib.tools.kodi_settings import set_addon_setting
    res = set_addon_setting(addon_id="plugin.video.seren", key="a", value="new_value")
    assert res.success
    assert fake_kodi_settings["addons"]["plugin.video.seren"]["a"] == "new_value"
