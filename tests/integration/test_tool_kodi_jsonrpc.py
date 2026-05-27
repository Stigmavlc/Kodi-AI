# tests/integration/test_tool_kodi_jsonrpc.py
import json, sys, pytest
from unittest import mock


@pytest.fixture
def fake_xbmc(monkeypatch):
    fake = mock.MagicMock()
    fake.executeJSONRPC.side_effect = lambda s: json.dumps({
        "result": {"version": {"major": 13}}
    })
    monkeypatch.setitem(sys.modules, "xbmc", fake)
    # Re-bind for module-cache case: if lib.tools.kodi_jsonrpc was already
    # imported by a previous test, its `xbmc` reference is cached. Re-point
    # it at the fresh fake so this test's assertions reach the right mock.
    if "lib.tools.kodi_jsonrpc" in sys.modules:
        monkeypatch.setattr(sys.modules["lib.tools.kodi_jsonrpc"], "xbmc", fake)
    return fake


@pytest.mark.integration
def test_allowed_method_executes(fake_xbmc):
    from lib.tools.kodi_jsonrpc import kodi_jsonrpc
    res = kodi_jsonrpc(method="JSONRPC.Version", params={})
    assert res.success
    assert "version" in res.output


@pytest.mark.integration
def test_denied_method_blocked(fake_xbmc):
    from lib.tools.kodi_jsonrpc import kodi_jsonrpc
    res = kodi_jsonrpc(method="Application.Quit", params={})
    assert not res.success
    assert "not allowlisted" in res.error


@pytest.mark.integration
def test_call_helper_for_other_tools(fake_xbmc):
    """Internal tools use call() to bypass allowlist (still safe; tools enforce
    their own contracts)."""
    from lib.tools.kodi_jsonrpc import call
    res = call("Settings.SetSettingValue", {"setting": "x", "value": "y"})
    assert "result" in res or "error" in res
