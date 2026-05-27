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
    # v0.3.0: setup_wizard + show_secret removed; setup lives inline in
    # Configure → Telegram and the bot DM flow handles the rest. default.py
    # now only exposes the status panel + reset_bot action.
    assert "show_status_panel" in content
    assert "reset_bot" in content


def test_service_py_exists():
    here = os.path.dirname(os.path.abspath(__file__))
    p = os.path.join(here, "..", "..", "service.kodi.ai", "service.py")
    assert os.path.exists(p), "service.kodi.ai/service.py must exist"
    with open(p, encoding="utf-8") as f:
        content = f.read()
    assert "t4_worker_body" in content
    assert "T2_LogPoll" in content
    assert "T4_Worker" in content
    # v0.3.0: T3 starts on-demand via BotHolder; the thread-name constant
    # moved to lib/bot_holder.py.
    bot_holder_path = os.path.join(here, "..", "..", "service.kodi.ai", "lib", "bot_holder.py")
    assert os.path.exists(bot_holder_path), "lib/bot_holder.py must exist"
    with open(bot_holder_path, encoding="utf-8") as f:
        bh_content = f.read()
    assert "T3_TGPoll" in bh_content


def test_service_addon_xml_has_service_extension():
    here = os.path.dirname(os.path.abspath(__file__))
    p = os.path.join(here, "..", "..", "service.kodi.ai", "addon.xml")
    with open(p, encoding="utf-8") as f:
        content = f.read()
    assert 'point="xbmc.service"' in content
