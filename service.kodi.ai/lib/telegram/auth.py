"""Telegram auth: setup_secret + chat_allowlist.
Spec §5.2."""
from __future__ import annotations
import json
import os
import secrets as _secrets
import time
from .. import state_paths, secrets


def generate_setup_secret() -> str:
    s = _secrets.token_urlsafe(8)
    secrets.set_secret("setup_secret", s)
    return s


def current_setup_secret() -> str | None:
    return secrets.get_secret("setup_secret")


def _allowlist_path() -> str:
    return state_paths.profile_path("chat_allowlist.json")


def chat_allowlist() -> list[int]:
    p = _allowlist_path()
    if not os.path.exists(p):
        return []
    try:
        with open(p) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def _save_allowlist(allowlist: list[int]) -> None:
    blob = json.dumps(allowlist, separators=(",", ":")).encode("utf-8")
    state_paths.atomic_write(_allowlist_path(), blob)


def try_authorize_first_start(chat_id: int, provided_secret: str) -> bool:
    current = current_setup_secret()
    if not current or provided_secret != current:
        return False
    allowlist = chat_allowlist()
    if chat_id not in allowlist:
        allowlist.append(chat_id)
        _save_allowlist(allowlist)
    secrets.delete_secret("setup_secret")
    # Try to also delete setup_secret.txt
    try:
        os.remove(state_paths.profile_path("setup_secret.txt"))
    except OSError:
        pass
    return True


def is_authorized(chat_id: int) -> bool:
    return chat_id in chat_allowlist()


def reset_bot_owner() -> str:
    """Clears allowlist + generates new setup_secret. Called from Kodi UI only."""
    _save_allowlist([])
    return generate_setup_secret()
