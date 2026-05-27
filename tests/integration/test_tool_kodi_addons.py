# tests/integration/test_tool_kodi_addons.py
import json, sys, pytest, os, shutil
from unittest import mock
from tests.integration.fakes import fake_xbmcvfs


@pytest.fixture
def fake_kodi(monkeypatch):
    xbmc = mock.MagicMock()
    state = {"addons": {
        "plugin.video.seren": {"enabled": True, "installed": True, "version": "1.0.0",
                                "path": fake_xbmcvfs.translatePath("special://home/addons/plugin.video.seren"),
                                "dependencies": []},
    }, "play_active": False}
    def jsonrpc(req_str):
        req = json.loads(req_str)
        m = req["method"]; p = req.get("params") or {}
        if m == "Addons.GetAddons":
            # FAKE-BUG-FIX: plan-verbatim fake omitted this branch; supply
            # addons list so list_addons can introspect installed state.
            addons = [{"addonid": aid, **info} for aid, info in state["addons"].items()]
            return json.dumps({"result": {"addons": addons}})
        if m == "Addons.GetAddonDetails":
            aid = p["addonid"]
            a = state["addons"].get(aid)
            if not a:
                return json.dumps({"error": {"message": "not found"}})
            return json.dumps({"result": {"addon": {**a, "addonid": aid}}})
        if m == "Addons.SetAddonEnabled":
            aid = p["addonid"]; en = p["enabled"]
            if aid in state["addons"]:
                state["addons"][aid]["enabled"] = en
            return json.dumps({"result": "OK"})
        if m == "Player.GetActivePlayers":
            # FAKE-BUG-FIX: plan-verbatim fake omitted playerid; real Kodi
            # always supplies it. addon_owns_active_player indexes ["playerid"].
            return json.dumps({"result": [{"playerid": 1, "type": "video"}] if state["play_active"] else []})
        if m == "Player.GetItem":
            return json.dumps({"result": {"item": {"addon": "plugin.video.seren"}}})
        return json.dumps({"result": None})
    xbmc.executeJSONRPC.side_effect = jsonrpc
    builtins_called = []
    def be(cmd):
        builtins_called.append(cmd)
        if cmd.startswith("EnableAddon("):
            aid = cmd[len("EnableAddon("):-1]
            if aid in state["addons"]:
                state["addons"][aid]["enabled"] = True
        if cmd.startswith("DisableAddon("):
            aid = cmd[len("DisableAddon("):-1]
            if aid in state["addons"]:
                state["addons"][aid]["enabled"] = False
        if cmd.startswith("InstallAddon("):
            aid = cmd[len("InstallAddon("):-1]
            state["addons"].setdefault(aid, {"enabled": True, "installed": True,
                                              "version": "0.1.0", "path": "/tmp/x", "dependencies": []})
    xbmc.executebuiltin.side_effect = be
    xbmc._state = state
    xbmc._builtins = builtins_called
    monkeypatch.setitem(sys.modules, "xbmc", xbmc)
    # Re-bind cached module references so tools see the fresh fake.
    if "lib.tools.kodi_addons" in sys.modules:
        monkeypatch.setattr(sys.modules["lib.tools.kodi_addons"], "xbmc", xbmc)
    if "lib.tools.kodi_jsonrpc" in sys.modules:
        monkeypatch.setattr(sys.modules["lib.tools.kodi_jsonrpc"], "xbmc", xbmc)
    yield xbmc


@pytest.mark.integration
def test_list_addons_returns_installed(fake_kodi):
    from lib.tools.kodi_addons import list_addons
    res = list_addons()
    assert res.success
    # output should contain the seren addon
    assert any("seren" in str(a) for a in (res.output or []))


@pytest.mark.integration
def test_enable_disable_round_trip(fake_kodi):
    from lib.tools.kodi_addons import disable_addon, enable_addon
    r1 = disable_addon(addon_id="plugin.video.seren")
    assert r1.success
    assert fake_kodi._state["addons"]["plugin.video.seren"]["enabled"] is False
    r2 = enable_addon(addon_id="plugin.video.seren")
    assert r2.success
    assert fake_kodi._state["addons"]["plugin.video.seren"]["enabled"] is True


@pytest.mark.integration
def test_restart_addon_disruptive_when_player_active(fake_kodi):
    from lib.tools.kodi_addons import restart_addon, _restart_disruptive_fn
    fake_kodi._state["play_active"] = True
    assert _restart_disruptive_fn({"addon_id": "plugin.video.seren"}) is True
    fake_kodi._state["play_active"] = False
    assert _restart_disruptive_fn({"addon_id": "plugin.video.seren"}) is False
