"""DM setup flow handlers (v0.3.0 inline-setup pivot).

Two entrypoints called from TelegramBot._handle_update:

  handle_or_key_message(bot, chat_id, text, message_id):
    Called when an authorized chat in state AWAITING_OR_KEY sends a
    non-command message. We treat the message as a candidate OpenRouter
    key, validate via llm_client.chat with a 1-token ping, on success
    promote to secrets.json + delete the user's message + present the
    mode inline keyboard + transition to AWAITING_MODE.

  handle_setup_mode_callback(bot, callback_query, data):
    Called when a callback_query with data 'setup_mode:auto' or
    'setup_mode:manual' arrives. Verifies the chat is authorized,
    persists the mode setting, edits the bot's message to confirm,
    clears the setup_secret + transitions to DONE.

Spec: v0.3.0 settings-inline setup pivot, §E.
"""
from __future__ import annotations
import xbmc

from .. import secrets as lib_secrets
from .. import settings
from .. import redactor
from ..llm import client as llm_client
from . import auth
from . import setup_dm_state


def _looks_like_or_key(text: str) -> bool:
    """Cheap format check — OpenRouter keys start with 'sk-or-'.

    Spec hardening (v0.3.1): reject early any candidate that doesn't have
    the `sk-or-` prefix. This avoids burning an HTTP round-trip on
    obvious garbage (typos, accidental paste of other tokens) AND keeps
    the bot's response time snappy in the common-mistake case.

    Keys are at least 16 chars in practice; we keep that floor to also
    reject ultra-short inputs early.
    """
    t = text.strip()
    return t.startswith("sk-or-") and len(t) >= 16


def handle_or_key_message(bot, chat_id: int, text: str, message_id: int | None) -> None:
    """Validate text as OpenRouter key; on success: persist + delete user
    message + show mode keyboard + state → AWAITING_MODE.

    On invalid key (auth error): tell user and stay in AWAITING_OR_KEY.
    On other failures (network/etc.): tell user to retry; stay in state.
    """
    candidate = text.strip()

    if not _looks_like_or_key(candidate):
        bot.send_message(
            chat_id,
            "That doesn't look like an OpenRouter key. Keys start with "
            "<code>sk-or-</code>. Get one at <b>openrouter.ai/keys</b>.",
        )
        return

    # Try the key with a 1-token ping. We use the documented preflight
    # model so the user's credit isn't materially consumed.
    try:
        llm_client.chat(
            api_key=candidate,
            model=llm_client.DEFAULT_PREFLIGHT_MODEL,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=1,
            timeout=(5.0, 10.0),
        )
    except llm_client.LLMAuthError:
        bot.send_message(
            chat_id,
            "Invalid key. Get a fresh one at <b>openrouter.ai/keys</b> "
            "and paste it here.",
        )
        return
    except llm_client.LLMNoCreditError:
        bot.send_message(
            chat_id,
            "Key valid but no credit on your OpenRouter account. Add "
            "credit at <b>openrouter.ai/credits</b> and resend.",
        )
        return
    except Exception as e:
        # H2 — redact exception repr() because some HTTP error subclasses
        # echo the full request URL (which may carry the candidate key in
        # an Authorization-bearing context, or, more importantly, the
        # Telegram bot URL if this exception bubbled up from a wrapped
        # send. Always run reprs through the URL-aware redactor before
        # logging or surfacing to the user.
        err = redactor.redact(f"validation error: {e!r}")
        xbmc.log(
            f"[service.kodi.ai] handle_or_key_message: {err}",
            xbmc.LOGWARNING,
        )
        bot.send_message(
            chat_id,
            "Could not reach OpenRouter to validate the key. Please retry "
            "in a moment.",
        )
        return

    # Validated! Persist + scrub user's message (PRIVACY hardening).
    try:
        lib_secrets.set_secret("openrouter_key", candidate)
    except Exception as e:
        err = redactor.redact(f"set_secret failed: {e!r}")
        xbmc.log(
            f"[service.kodi.ai] handle_or_key_message: {err}",
            xbmc.LOGERROR,
        )
        bot.send_message(
            chat_id, "Internal error saving key. Please retry.",
        )
        return
    # B8 — delete_message is best-effort. If it fails (message too old,
    # admin permission gone, network blip), the plaintext key persists in
    # the user's chat history forever. We must warn the user explicitly
    # so they can delete it manually. Do NOT abort the setup — the key
    # was already saved to secrets.json, and aborting would just confuse
    # the user.
    if message_id is not None:
        deleted = False
        delete_err = None
        try:
            result = bot.delete_message(chat_id, message_id)
            # delete_message returns a dict; treat any falsy or
            # explicit ok=False as a failure.
            deleted = bool(isinstance(result, dict) and result.get("ok"))
        except Exception as e:
            deleted = False
            delete_err = redactor.redact(repr(e))
            xbmc.log(
                f"[service.kodi.ai] handle_or_key_message: "
                f"delete_message raised: {delete_err}",
                xbmc.LOGWARNING,
            )
        if not deleted:
            if delete_err is None:
                xbmc.log(
                    "[service.kodi.ai] handle_or_key_message: "
                    "delete_message returned non-ok response — key "
                    "remains in chat history",
                    xbmc.LOGWARNING,
                )
            # Tell the user — they need to manually delete to scrub the
            # plaintext key from their history.
            try:
                bot.send_message(
                    chat_id,
                    "⚠ I couldn't delete your previous message containing "
                    "the API key. Please delete it manually from this chat.",
                )
            except Exception:
                pass

    # Send the mode-choice inline keyboard.
    kb = {
        "inline_keyboard": [
            [
                {"text": "Auto (recommended)", "callback_data": "setup_mode:auto"},
                {"text": "Manual", "callback_data": "setup_mode:manual"},
            ],
        ],
    }
    bot.send_message(
        chat_id,
        "✓ Key verified.\n\nChoose agent mode:\n\n"
        "<b>Auto</b> applies safe fixes automatically.\n"
        "<b>Manual</b> asks before every fix.",
        reply_markup=kb,
    )
    try:
        setup_dm_state.set_state(chat_id, setup_dm_state.AWAITING_MODE)
    except Exception:
        pass


def handle_setup_mode_callback(bot, callback_query: dict, data: str) -> None:
    """Process a 'setup_mode:<choice>' callback. Persists mode, edits the
    keyboard message to a confirmation, clears setup_secret, transitions
    state to DONE."""
    msg = callback_query.get("message") or {}
    chat_id = (msg.get("chat") or {}).get("id")
    message_id = msg.get("message_id")
    if chat_id is None:
        return
    # Auth check — already done by caller in TelegramBot._handle_update,
    # but a defense-in-depth check here is cheap.
    if not auth.is_authorized(chat_id):
        return
    parts = data.split(":", 1)
    if len(parts) != 2:
        return
    choice = parts[1].strip().lower()
    if choice not in ("auto", "manual"):
        return
    try:
        settings.set_string("mode", choice)
    except Exception as e:
        err = redactor.redact(f"set mode failed: {e!r}")
        xbmc.log(
            f"[service.kodi.ai] handle_setup_mode_callback: {err}",
            xbmc.LOGERROR,
        )
        return

    # Edit the keyboard message into a confirmation. Pass empty
    # reply_markup-equivalent? Kodi-AI: we use editMessageText without a
    # keyboard payload so the buttons drop away.
    if message_id is not None:
        try:
            bot.edit_message(
                chat_id, message_id,
                "✓ Setup complete! I'll notify you when something needs "
                "attention.",
            )
        except Exception:
            # Fallback: send a fresh message.
            bot.send_message(
                chat_id,
                "✓ Setup complete! I'll notify you when something needs "
                "attention.",
            )

    # State → DONE; setup_secret is no longer needed.
    try:
        setup_dm_state.set_state(chat_id, setup_dm_state.DONE)
    except Exception:
        pass
    try:
        lib_secrets.delete_secret("setup_secret")
    except Exception:
        pass
