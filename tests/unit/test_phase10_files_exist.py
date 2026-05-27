"""Phase 10 — verify UI + orchestrator files exist + carry expected symbols.

These tests read the files as text (no import) so they don't require xbmc /
xbmcgui stubs to be present in the test environment.
"""
import os


def test_default_py_exists():
    here = os.path.dirname(os.path.abspath(__file__))
    p = os.path.join(here, "..", "..", "service.kodi.ai", "default.py")
    assert os.path.exists(p), "service.kodi.ai/default.py must exist"
    with open(p, encoding="utf-8") as f:
        content = f.read()
    assert "setup_wizard" in content
    assert "show_secret" in content
    assert "show_status_panel" in content


def test_service_py_exists():
    here = os.path.dirname(os.path.abspath(__file__))
    p = os.path.join(here, "..", "..", "service.kodi.ai", "service.py")
    assert os.path.exists(p), "service.kodi.ai/service.py must exist"
    with open(p, encoding="utf-8") as f:
        content = f.read()
    assert "t4_worker_body" in content
    assert "T2_LogPoll" in content
    assert "T3_TGPoll" in content
    assert "T4_Worker" in content


def test_service_addon_xml_has_service_extension():
    here = os.path.dirname(os.path.abspath(__file__))
    p = os.path.join(here, "..", "..", "service.kodi.ai", "addon.xml")
    with open(p, encoding="utf-8") as f:
        content = f.read()
    assert 'point="xbmc.service"' in content
