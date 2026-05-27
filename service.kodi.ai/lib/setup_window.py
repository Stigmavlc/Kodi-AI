"""xbmcgui.WindowXMLDialog subclass for the phone-driven setup flow.

The window:
- Renders the pre-generated QR PNG (caller passes `qr_path`).
- Shows the LAN URL ("http://192.168.1.42:8088/setup?token=...").
- Polls `http://127.0.0.1:<port>/api/status` on a daemon thread, updating
  the 4 step labels as the phone progresses.
- Auto-closes after pairing succeeds (step=4 + paired=True) OR when the
  server signals should_die (rate-limit hard limit hit, B1).

Thread safety:
- `xbmcgui.Control.setLabel()` is documented as safe to call from Python
  threads in Kodi 21 Omega. We call it directly from the polling thread.
- BUT window lifecycle methods (close()) are MAIN-THREAD-ONLY (H2). The
  polling thread MUST NOT call self.close() directly. Instead it sets
  _closing and uses xbmc.executebuiltin("Dialog.Close(id)") which Kodi
  dispatches onto its main thread.

Spec: §1.14 (revised) phone-driven setup.
"""
from __future__ import annotations
import threading
from typing import Any, Optional

import requests
import xbmc  # type: ignore
import xbmcgui  # type: ignore


# Control IDs — must match resources/skins/Default/720p/Setup.xml.
ID_QR_IMAGE = 9100
ID_URL_LABEL = 9101
ID_STEP_LABELS = (9110, 9111, 9112, 9113)
ID_CANCEL_BTN = 9200

# Match Kodi's standard action IDs without depending on xbmcgui constants
# that may differ across Kodi versions.
ACTION_NAV_BACK = 92
ACTION_PREVIOUS_MENU = 10
ACTION_CLOSE_DIALOG = 51

POLL_INTERVAL_SECONDS = 0.75
HTTP_TIMEOUT_SECONDS = 2.0
AUTOCLOSE_DELAY_SECONDS = 2.0

# Step label templates — updated to "done" form when state advances.
STEP_LABELS_PENDING = (
    "1. Waiting for phone",
    "2. OpenRouter key received",
    "3. Telegram bot configured",
    "4. Pairing complete",
)
STEP_LABELS_DONE = (
    "1. Phone connected",
    "2. OpenRouter key received",
    "3. Telegram bot configured",
    "4. Pairing complete",
)


class SetupWindow(xbmcgui.WindowXMLDialog):
    """Modal dialog hosting the QR code + step indicators.

    Kwargs:
        qr_path: absolute path to a PNG of the setup URL QR.
        url: the setup URL displayed below the QR.
        session_token: token used by the polling thread when calling /api/status.
        lan_ip: server LAN IP (informational; the poller hits 127.0.0.1).
        port: server port (used by the poller).
    """

    # Set by __new__/init kwargs — declared here so type-checkers don't trip.
    _qr_path: str
    _url: str
    _session_token: str
    _port: int
    _closing: threading.Event
    _poll_thread: Optional[threading.Thread]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args)
        self._qr_path = kwargs.get("qr_path", "")
        self._url = kwargs.get("url", "")
        self._session_token = kwargs.get("session_token", "")
        self._lan_ip = kwargs.get("lan_ip", "")
        self._port = int(kwargs.get("port", 0))
        self._closing = threading.Event()
        self._poll_thread = None
        # Track last-rendered state to avoid redundant setLabel calls.
        self._last_state: Optional[dict] = None

    # ---- lifecycle -----------------------------------------------------
    def onInit(self) -> None:  # noqa: N802 — Kodi API
        try:
            if self._qr_path:
                self.getControl(ID_QR_IMAGE).setImage(self._qr_path, False)
        except Exception:
            pass
        try:
            self.getControl(ID_URL_LABEL).setLabel(self._url)
        except Exception:
            pass
        # Initial step labels — all pending.
        for idx, label_id in enumerate(ID_STEP_LABELS):
            try:
                self.getControl(label_id).setLabel(STEP_LABELS_PENDING[idx])
            except Exception:
                pass
        self._start_polling()

    def onAction(self, action) -> None:  # noqa: N802 — Kodi API
        aid = getattr(action, "getId", lambda: -1)()
        if aid in (ACTION_NAV_BACK, ACTION_PREVIOUS_MENU, ACTION_CLOSE_DIALOG):
            # onAction fires on the main thread -> safe to call close()
            # directly here.
            self._closing.set()
            self.close()

    def onClick(self, control_id: int) -> None:  # noqa: N802 — Kodi API
        if control_id == ID_CANCEL_BTN:
            # onClick fires on the main thread -> safe to close() directly.
            self._closing.set()
            self.close()

    def close(self) -> None:
        # Signal the polling thread to stop BEFORE delegating to the base
        # close (which tears down the native window). H1: set the flag
        # first so any in-flight poll iteration that's about to call
        # getControl().setLabel() sees it and bails out early.
        self._closing.set()
        try:
            super().close()
        except Exception:
            pass

    def _request_close_from_background(self) -> None:
        """Schedule the dialog close from a background thread.

        Kodi window lifecycle is main-thread only -- calling self.close()
        from the polling thread risks a segfault. Use Kodi's built-in
        Dialog.Close() which dispatches onto the main thread. (H2)
        """
        # Mark closing first to short-circuit re-entry from any further
        # poll iterations.
        self._closing.set()
        try:
            window_id = self.getWindowId()
        except Exception:
            window_id = None
        if window_id:
            try:
                xbmc.executebuiltin(f"Dialog.Close({window_id})")
            except Exception:
                pass

    # ---- polling -------------------------------------------------------
    def _start_polling(self) -> None:
        t = threading.Thread(target=self._poll_loop, daemon=True,
                             name="kodi-ai-setup-poll")
        self._poll_thread = t
        t.start()

    def _poll_loop(self) -> None:
        monitor = xbmc.Monitor()
        url = f"http://127.0.0.1:{self._port}/api/status"
        params = {"token": self._session_token}
        while not self._closing.is_set() and not monitor.abortRequested():
            if monitor.waitForAbort(POLL_INTERVAL_SECONDS):
                break
            if self._closing.is_set():
                break
            try:
                resp = requests.get(url, params=params, timeout=HTTP_TIMEOUT_SECONDS)
                data = resp.json()
            except Exception:
                # Server may be mid-shutdown or just-restarted. Retry next tick.
                continue
            # B1: server-side rate-limit shutdown signal. Server has decided
            # it must die; close the dialog so setup_via_phone's finally
            # block can drive a clean shutdown.
            if data.get("should_die"):
                self._request_close_from_background()
                return
            self._apply_state(data)
            if data.get("step") == 4 and data.get("paired"):
                # Successful pairing. Hold the "all done" frame briefly for
                # readability, then close (via main-thread dispatch -- H2).
                if monitor.waitForAbort(AUTOCLOSE_DELAY_SECONDS):
                    break
                self._request_close_from_background()
                return

    def _apply_state(self, state: dict) -> None:
        """Update step label text based on the status dict.

        Marks step N as "done" when the corresponding flag is true.
        """
        if self._last_state == state:
            return
        self._last_state = dict(state)
        step = int(state.get("step", 1) or 1)
        or_ok = bool(state.get("openrouter_ok"))
        tg_ok = bool(state.get("telegram_ok"))
        paired = bool(state.get("paired"))

        # Map: (label_id, completed?, pending_text, done_text)
        rows = [
            (ID_STEP_LABELS[0], step >= 2,
             STEP_LABELS_PENDING[0], STEP_LABELS_DONE[0]),
            (ID_STEP_LABELS[1], or_ok,
             STEP_LABELS_PENDING[1], STEP_LABELS_DONE[1]),
            (ID_STEP_LABELS[2], tg_ok,
             STEP_LABELS_PENDING[2], STEP_LABELS_DONE[2]),
            (ID_STEP_LABELS[3], paired,
             STEP_LABELS_PENDING[3], STEP_LABELS_DONE[3]),
        ]
        for label_id, done, pending_text, done_text in rows:
            if done:
                text = "[COLOR FF00E676]" + done_text + "  (done)[/COLOR]"
            else:
                text = pending_text
            try:
                self.getControl(label_id).setLabel(text)
            except Exception:
                # Window already torn down — bail out.
                self._closing.set()
                return
