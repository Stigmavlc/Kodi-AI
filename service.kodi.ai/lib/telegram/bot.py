"""T3 long-poll Telegram bot.

requests.get(getUpdates, timeout=(3,10)) — accepts 10s worst-case shutdown.
Auth via lib/telegram/auth.py. Dispatches via lib/telegram/commands.py and
lib/telegram/callbacks.py.

Spec: §1.2, §1.10, §4.5.
"""
from __future__ import annotations
import time
import random
import requests
from ..concurrency import abort_event, enqueue, UserMsg, ResumeWork
from . import auth


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
        # Callback queries → ResumeWork
        if "callback_query" in upd:
            cq = upd["callback_query"]
            chat_id = cq["message"]["chat"]["id"]
            if not auth.is_authorized(chat_id):
                return
            data = cq.get("data", "")
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
                    self.send_message(chat_id, "Welcome — Kodi-AI ready.")
                else:
                    self.send_message(chat_id, "Invalid secret. Send /start &lt;secret&gt;.")
                return
            if not auth.is_authorized(chat_id):
                self.send_message(chat_id, "Please send /start &lt;secret&gt; from your Kodi setup.")
                return
            enqueue(UserMsg(chat_id=chat_id, text=text, message_id=mid,
                            reply_to_message_id=reply_to))

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
