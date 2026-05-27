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


@pytest.mark.integration
def test_uninstall_addon_clears_state(fake_kodi):
    # Wire UninstallAddon(...) so the fake state mutates → details return None.
    state = fake_kodi._state
    original_be = fake_kodi.executebuiltin.side_effect
    def be(cmd):
        if cmd.startswith("UninstallAddon("):
            aid = cmd[len("UninstallAddon("):-1]
            state["addons"].pop(aid, None)
            return
        return original_be(cmd)
    fake_kodi.executebuiltin.side_effect = be

    from lib.tools.kodi_addons import uninstall_addon
    res = uninstall_addon(addon_id="plugin.video.seren")
    assert res.success
    assert res.requested.startswith("uninstall_addon")
    assert "plugin.video.seren" not in state["addons"]


@pytest.mark.integration
def test_update_addon_returns_warning_on_no_version_change(fake_kodi, monkeypatch):
    # Shrink the update timeout to 2s for the test.
    from lib.tools import kodi_addons
    monkeypatch.setattr(kodi_addons, "_UPDATE_TIMEOUT_S", 2.0)

    res = kodi_addons.update_addon(addon_id="plugin.video.seren")
    assert res.requested.startswith("update_addon")
    # No version change → success with warning per spec §4.6 round-3.
    assert res.success is True
    assert res.warning == "already at latest or repo unreachable"


@pytest.mark.integration
def test_clear_addon_cache_returns_result(fake_kodi, tmp_path, monkeypatch):
    # Stage a fake cache dir under profile + __pycache__ under install path
    # so clear_addon_cache exercises both delete branches.
    from lib.tools import kodi_addons
    from lib import state_paths
    cache_dir = state_paths.profile_path("addon_data/plugin.video.seren/cache")
    os.makedirs(cache_dir, exist_ok=True)
    with open(os.path.join(cache_dir, "stale.dat"), "w") as f:
        f.write("x")
    install_path = fake_kodi._state["addons"]["plugin.video.seren"]["path"]
    pycache = os.path.join(install_path, "__pycache__")
    os.makedirs(pycache, exist_ok=True)
    with open(os.path.join(pycache, "mod.cpython-314.pyc"), "w") as f:
        f.write("x")

    res = kodi_addons.clear_addon_cache(addon_id="plugin.video.seren")
    assert res.requested.startswith("clear_addon_cache")
    # restart_addon is folded; success depends on disable+enable round-trip,
    # which the fake supports → True.
    assert res.success is True
    # Both cache locations should be gone.
    assert not os.path.exists(cache_dir)
    assert not os.path.exists(pycache)
