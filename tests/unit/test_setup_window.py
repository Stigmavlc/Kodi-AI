"""Unit tests for lib.setup_window — polling thread + state-to-label mapping.

We can't construct a real xbmcgui.WindowXMLDialog without Kodi running, so
these tests exercise the polling logic + state mapping in isolation by
constructing the SetupWindow instance with mocked controls.
"""
from __future__ import annotations
import sys
import threading
import time
from unittest import mock

import pytest


@pytest.fixture
def patched_xbmcgui(monkeypatch):
    """Replace xbmcgui.WindowXMLDialog with a no-op base class so we can
    instantiate SetupWindow without a running Kodi."""
    import xbmcgui as _real_xbmcgui

    class _FakeBase:
        def __init__(self, *args, **kwargs):
            self._controls = {}
        def getControl(self, control_id):  # noqa: N802 — Kodi API
            # Return a sticky MagicMock per control_id so the test can assert
            # what was set on which control.
            c = self._controls.get(control_id)
            if c is None:
                c = mock.MagicMock(name=f"Control({control_id})")
                self._controls[control_id] = c
            return c
        def close(self):
            pass

    monkeypatch.setattr(_real_xbmcgui, "WindowXMLDialog", _FakeBase)
    # Reset cached module so import sees the patched base.
    sys.modules.pop("lib.setup_window", None)
    yield
    sys.modules.pop("lib.setup_window", None)


def test_apply_state_initial_no_labels_change(patched_xbmcgui):
    from lib import setup_window
    w = setup_window.SetupWindow(
        "Setup.xml", "/tmp/addon", "Default", "720p",
        qr_path="/tmp/qr.png", url="http://1.2.3.4/", session_token="t",
        lan_ip="1.2.3.4", port=8088,
    )
    # Pretend onInit happened
    w._apply_state({"step": 1, "openrouter_ok": False, "telegram_ok": False, "paired": False})
    # All 4 step labels should have been set to PENDING text.
    for i, lid in enumerate(setup_window.ID_STEP_LABELS):
        c = w._controls[lid]
        last_set = c.setLabel.call_args
        assert last_set.args[0] == setup_window.STEP_LABELS_PENDING[i]


def test_apply_state_step_2_marks_step_1_done(patched_xbmcgui):
    from lib import setup_window
    w = setup_window.SetupWindow(
        "Setup.xml", "/tmp/addon", "Default", "720p",
        qr_path="", url="", session_token="t", lan_ip="", port=8088,
    )
    w._apply_state({"step": 2, "openrouter_ok": False, "telegram_ok": False, "paired": False})
    c1 = w._controls[setup_window.ID_STEP_LABELS[0]]
    last = c1.setLabel.call_args.args[0]
    assert "(done)" in last
    assert "FF00E676" in last  # green color tag


def test_apply_state_openrouter_ok_marks_step_2_done(patched_xbmcgui):
    from lib import setup_window
    w = setup_window.SetupWindow(
        "Setup.xml", "/tmp/addon", "Default", "720p",
        qr_path="", url="", session_token="t", lan_ip="", port=8088,
    )
    w._apply_state({"step": 2, "openrouter_ok": True, "telegram_ok": False, "paired": False})
    c2 = w._controls[setup_window.ID_STEP_LABELS[1]]
    last = c2.setLabel.call_args.args[0]
    assert "(done)" in last
    # Step 3 still pending.
    c3 = w._controls[setup_window.ID_STEP_LABELS[2]]
    last3 = c3.setLabel.call_args.args[0]
    assert "(done)" not in last3


def test_apply_state_paired_marks_step_4_done(patched_xbmcgui):
    from lib import setup_window
    w = setup_window.SetupWindow(
        "Setup.xml", "/tmp/addon", "Default", "720p",
        qr_path="", url="", session_token="t", lan_ip="", port=8088,
    )
    w._apply_state({"step": 4, "openrouter_ok": True, "telegram_ok": True, "paired": True})
    for lid in setup_window.ID_STEP_LABELS:
        last = w._controls[lid].setLabel.call_args.args[0]
        assert "(done)" in last


def test_apply_state_dedupes_redundant_updates(patched_xbmcgui):
    from lib import setup_window
    w = setup_window.SetupWindow(
        "Setup.xml", "/tmp/addon", "Default", "720p",
        qr_path="", url="", session_token="t", lan_ip="", port=8088,
    )
    state = {"step": 2, "openrouter_ok": True, "telegram_ok": False, "paired": False}
    w._apply_state(state)
    call_count_after_first = sum(
        c.setLabel.call_count for c in w._controls.values()
    )
    w._apply_state(state)
    call_count_after_second = sum(
        c.setLabel.call_count for c in w._controls.values()
    )
    # Second identical apply must be a no-op.
    assert call_count_after_first == call_count_after_second


def test_close_signals_polling_thread_to_stop(patched_xbmcgui):
    from lib import setup_window
    w = setup_window.SetupWindow(
        "Setup.xml", "/tmp/addon", "Default", "720p",
        qr_path="", url="", session_token="t", lan_ip="", port=8088,
    )
    assert not w._closing.is_set()
    w.close()
    assert w._closing.is_set()


def test_on_init_sets_qr_image_and_url_label(patched_xbmcgui):
    from lib import setup_window
    w = setup_window.SetupWindow(
        "Setup.xml", "/tmp/addon", "Default", "720p",
        qr_path="/tmp/qr.png", url="http://lan:8088/setup?token=xyz",
        session_token="xyz", lan_ip="lan", port=8088,
    )
    # Stub xbmc.Monitor so the polling loop exits cleanly.
    import xbmc as _real_xbmc
    fake_monitor = mock.MagicMock()
    fake_monitor.abortRequested.return_value = False
    fake_monitor.waitForAbort.side_effect = [True]  # exit immediately
    _real_xbmc.Monitor = lambda: fake_monitor
    w.onInit()
    # Image control should have been set with useCache=False (positional False).
    img = w._controls[setup_window.ID_QR_IMAGE]
    img.setImage.assert_called_with("/tmp/qr.png", False)
    # URL label set.
    url = w._controls[setup_window.ID_URL_LABEL]
    url.setLabel.assert_called_with("http://lan:8088/setup?token=xyz")
    # Step labels should have been initialised to pending text.
    for i, lid in enumerate(setup_window.ID_STEP_LABELS):
        w._controls[lid].setLabel.assert_called_with(setup_window.STEP_LABELS_PENDING[i])

    # Wait for the polling thread to exit (it should — waitForAbort returned True).
    if w._poll_thread is not None:
        w._poll_thread.join(timeout=2)
        assert not w._poll_thread.is_alive()


def test_polling_thread_polls_status_and_applies_state(patched_xbmcgui, monkeypatch):
    """Drive a full poll cycle: fake xbmc.Monitor + fake requests.get →
    verify _apply_state was called with the response payload."""
    from lib import setup_window

    # Sequence: first waitForAbort returns False (sleep), so loop body runs;
    # second returns True so the loop exits.
    fake_monitor = mock.MagicMock()
    fake_monitor.abortRequested.return_value = False
    fake_monitor.waitForAbort.side_effect = [False, True]
    import xbmc as _real_xbmc
    monkeypatch.setattr(_real_xbmc, "Monitor", lambda: fake_monitor)

    # Fake the GET response.
    fake_resp = mock.MagicMock()
    fake_resp.json.return_value = {
        "step": 3, "openrouter_ok": True, "telegram_ok": True, "paired": False,
    }
    monkeypatch.setattr(setup_window.requests, "get",
                        lambda url, params, timeout: fake_resp)

    w = setup_window.SetupWindow(
        "Setup.xml", "/tmp/addon", "Default", "720p",
        qr_path="", url="", session_token="abc", lan_ip="", port=12345,
    )
    # Drive the polling thread synchronously by calling _poll_loop directly.
    w._poll_loop()

    # Steps 1, 2, 3 should be marked done (3 → openrouter_ok=True → step 2 done,
    # telegram_ok=True → step 3 done, step>=2 means step 1 done).
    for i in (0, 1, 2):
        last = w._controls[setup_window.ID_STEP_LABELS[i]].setLabel.call_args.args[0]
        assert "(done)" in last, f"step {i+1} not marked done: {last}"
    # Step 4 (paired) NOT done yet.
    last4 = w._controls[setup_window.ID_STEP_LABELS[3]].setLabel.call_args.args[0]
    assert "(done)" not in last4


def test_polling_thread_autocloses_on_paired_step_4(patched_xbmcgui, monkeypatch):
    from lib import setup_window

    fake_monitor = mock.MagicMock()
    fake_monitor.abortRequested.return_value = False
    # First waitForAbort: sleep before poll → False.
    # Second waitForAbort: post-pair "hold" delay → False.
    # Then close() is called.
    fake_monitor.waitForAbort.side_effect = [False, False]
    import xbmc as _real_xbmc
    monkeypatch.setattr(_real_xbmc, "Monitor", lambda: fake_monitor)

    fake_resp = mock.MagicMock()
    fake_resp.json.return_value = {
        "step": 4, "openrouter_ok": True, "telegram_ok": True, "paired": True,
    }
    monkeypatch.setattr(setup_window.requests, "get",
                        lambda url, params, timeout: fake_resp)

    w = setup_window.SetupWindow(
        "Setup.xml", "/tmp/addon", "Default", "720p",
        qr_path="", url="", session_token="abc", lan_ip="", port=12345,
    )
    w._poll_loop()
    assert w._closing.is_set()


def test_polling_thread_swallows_transient_network_errors(patched_xbmcgui, monkeypatch):
    """If /api/status raises (e.g. server restarting), the loop keeps going."""
    from lib import setup_window

    fake_monitor = mock.MagicMock()
    fake_monitor.abortRequested.return_value = False
    # Three iterations: connect error, connect error, then exit.
    fake_monitor.waitForAbort.side_effect = [False, False, True]
    import xbmc as _real_xbmc
    monkeypatch.setattr(_real_xbmc, "Monitor", lambda: fake_monitor)

    def _raise(*a, **kw):
        raise ConnectionError("boom")
    monkeypatch.setattr(setup_window.requests, "get", _raise)

    w = setup_window.SetupWindow(
        "Setup.xml", "/tmp/addon", "Default", "720p",
        qr_path="", url="", session_token="abc", lan_ip="", port=12345,
    )
    # Should NOT raise; loop exits cleanly when waitForAbort returns True.
    w._poll_loop()
