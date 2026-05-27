"""T3 long-poll Telegram bot.

requests.get(getUpdates, timeout=(3,10)) — accepts 10s worst-case shutdown.
Auth via lib/telegram/auth.py. Dispatches via lib/telegram/commands.py and
lib/telegram/callbacks.py.

v0.3.0 inline-setup DM flow:
  After /start <secret> authorizes a new user, if openrouter_key is empty
  we enter AWAITING_OR_KEY state and treat the next non-command message as
  the OpenRouter API key. Once validated we transition to AWAITING_MODE
  and present inline buttons for mode selection (callback_data prefix
  'setup_mode:').

Spec: §1.2, §1.10, §4.5; v0.3.0 settings-inline setup pivot §E.
"""
from __future__ import annotations
import time
import random
import requests
from ..concurrency import abort_event, enqueue, UserMsg, ResumeWork
from . import auth
from . import setup_dm_state


class TelegramBot:
    BASE = "https://api.telegram.org/bot"

    def __init__(self, bot_token: str):
        self.token = bot_token
        self._offset = 0

    def _url(self, method: str) -> str:
        return f"{self.BASE}{self.token}/{method}"

    def send_message(self, chat_id: int, text: str, *, reply_markup: dict | None = None,
                     reply_to_message_id: int | None = None,
                     disable_notification: bool = False,
                     parse_mode: str = "HTML") -> dict:
        payload = {
            "chat_id": chat_id, "text": text, "parse_mode": parse_mode,
            "disable_notification": disable_notification,
        }
        if reply_markup: payload["reply_markup"] = reply_markup
        if reply_to_message_id: payload["reply_to_message_id"] = reply_to_message_id
        r = requests.post(self._url("sendMessage"), json=payload, timeout=(3, 10))
        return r.json()

    def edit_message(self, chat_id: int, message_id: int, text: str,
                     reply_markup: dict | None = None, parse_mode: str = "HTML") -> dict:
        payload = {"chat_id": chat_id, "message_id": message_id, "text": text,
                   "parse_mode": parse_mode}
        if reply_markup: payload["reply_markup"] = reply_markup
        r = requests.post(self._url("editMessageText"), json=payload, timeout=(3, 10))
        return r.json()

    def delete_message(self, chat_id: int, message_id: int) -> dict:
        """Delete a message in the chat (best-effort; ignored on failure).

        Used to scrub the OpenRouter key the user pastes during setup DM
        flow so the plaintext key doesn't sit in their chat history.
        """
        try:
            r = requests.post(
                self._url("deleteMessage"),
                json={"chat_id": chat_id, "message_id": message_id},
                timeout=(3, 5),
            )
            return r.json()
        except Exception:
            return {"ok": False}

    def answer_callback_query(self, callback_id: str, text: str = "") -> None:
        try:
            requests.post(self._url("answerCallbackQuery"),
                          json={"callback_query_id": callback_id, "text": text},
                          timeout=(3, 5))
        except Exception:
            pass

    def get_me(self) -> dict:
        r = requests.get(self._url("getMe"), timeout=(3, 5))
        return r.json()

    def _handle_update(self, upd: dict) -> None:
        # Callback queries → ResumeWork OR setup_mode:* selection
        if "callback_query" in upd:
            cq = upd["callback_query"]
            chat_id = cq["message"]["chat"]["id"]
            if not auth.is_authorized(chat_id):
                self.answer_callback_query(cq["id"])
                return
            data = cq.get("data", "")
            # v0.3.0 setup mode callback handled here so we own the message
            # edit + state transition (no work-queue indirection needed).
            if data.startswith("setup_mode:"):
                from . import setup_callbacks
                try:
                    setup_callbacks.handle_setup_mode_callback(self, cq, data)
                except Exception:
                    pass
                self.answer_callback_query(cq["id"])
                return
            # data format: "resume:<session_id>:<user_reply>"
            parts = data.split(":", 2)
            if len(parts) >= 3 and parts[0] == "resume":
                sid, reply = parts[1], parts[2]
                user_reply = reply if reply not in ("True", "False") else (reply == "True")
                enqueue(ResumeWork(session_id=sid, user_reply=user_reply))
            self.answer_callback_query(cq["id"])
            return
        # Regular messages
        if "message" in upd:
            msg = upd["message"]
            chat_id = msg["chat"]["id"]
            text = (msg.get("text") or "").strip()
            mid = msg.get("message_id")
            reply_to = (msg.get("reply_to_message") or {}).get("message_id")
            # /start <secret> auth flow
            if text.startswith("/start "):
                secret = text[len("/start "):].strip()
                if auth.try_authorize_first_start(chat_id, secret):
                    self._on_first_authorize(chat_id)
                else:
                    self.send_message(chat_id, "Invalid secret. Send /start &lt;secret&gt;.")
                return
            if not auth.is_authorized(chat_id):
                self.send_message(chat_id, "Please send /start &lt;secret&gt; from your Kodi setup.")
                return
            # Authorized — check if we're mid-setup-DM-flow.
            try:
                dm_state = setup_dm_state.get_state(chat_id)
            except Exception:
                dm_state = None
            if dm_state == setup_dm_state.AWAITING_OR_KEY:
                from . import setup_callbacks
                try:
                    setup_callbacks.handle_or_key_message(self, chat_id, text, mid)
                except Exception:
                    self.send_message(
                        chat_id,
                        "Unexpected error validating key. Please try again.",
                    )
                return
            if dm_state == setup_dm_state.AWAITING_MODE:
                # Tell user to use the inline buttons.
                self.send_message(
                    chat_id,
                    "Please tap one of the buttons above to choose agent mode.",
                )
                return
            # Normal flow: enqueue for the reasoner.
            enqueue(UserMsg(chat_id=chat_id, text=text, message_id=mid,
                            reply_to_message_id=reply_to))

    def _on_first_authorize(self, chat_id: int) -> None:
        """User just paired via /start <secret>. Decide whether to enter
        the DM setup flow (if openrouter_key is missing) or just greet."""
        from .. import secrets as lib_secrets
        try:
            has_key = bool(lib_secrets.get_secret("openrouter_key"))
        except Exception:
            has_key = False
        if has_key:
            # All set — normal welcome.
            self.send_message(chat_id, "Welcome — Kodi-AI ready.")
            try:
                setup_dm_state.set_state(chat_id, setup_dm_state.DONE)
            except Exception:
                pass
            return
        # Kick off the DM setup flow: ask for OpenRouter key.
        self.send_message(
            chat_id,
            "Welcome to Kodi-AI! Please send me your OpenRouter API key "
            "(starts with <code>sk-or-</code>).\n\n"
            "Get one at <b>openrouter.ai/keys</b> if you don't have one "
            "(~$5 typical credit).",
        )
        try:
            setup_dm_state.set_state(chat_id, setup_dm_state.AWAITING_OR_KEY)
        except Exception:
            pass

    def run(self) -> None:
        from ..concurrency import startup_complete_event
        startup_complete_event.wait()
        backoff = 1.0
        while not abort_event.is_set():
            try:
                r = requests.get(
                    self._url("getUpdates"),
                    params={"offset": self._offset, "timeout": 10, "allowed_updates": ["message", "callback_query"]},
                    timeout=(3, 12),
                )
                if r.status_code == 429:
                    wait_s = int(r.headers.get("Retry-After", "5"))
                    if abort_event.wait(min(wait_s, 60)):
                        return
                    continue
                if r.status_code >= 500:
                    backoff = min(backoff * 2, 60)
                    if abort_event.wait(backoff + random.random()):
                        return
                    continue
                if r.status_code != 200:
                    if abort_event.wait(5):
                        return
                    continue
                backoff = 1.0
                try:
                    from .. import health as _health
                    _health.record_telegram_rt_ok()
                except Exception:
                    pass
                for upd in r.json().get("result", []):
                    self._offset = max(self._offset, upd["update_id"] + 1)
                    try:
                        self._handle_update(upd)
                    except Exception:
                        pass
            except requests.exceptions.RequestException:
                if abort_event.wait(min(backoff, 30)):
                    return
                backoff = min(backoff * 2, 60)
