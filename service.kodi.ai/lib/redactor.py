"""Pattern-based redaction + key-name heuristic + allow_list.

Used at every boundary that touches LLM input or audit log. Canary self-test
runs every 100 redactions (called by lib/llm/client.py) — failure disables
LLM calls.

Spec: §5.8.
"""
from __future__ import annotations
import json
import os
import re
import threading
from typing import Any

_LOCK = threading.Lock()
_REDACTION_COUNT = 0
_CANARY_INTERVAL = 100

# --- Patterns ---
_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Telegram bot token embedded in a URL path: api.telegram.org/bot{TOKEN}/...
    # Matched BEFORE the bare-token pattern because the leading `bot` glues
    # the token to a word char on its left, defeating the `\b` in the
    # bare-token regex below. Common leak vector: repr(HTTPError) / repr(
    # JSONDecodeError) embeds the full request URL.
    (re.compile(r"(?i)(/bot)\d{8,12}:[A-Za-z0-9_-]{30,}"), r"\1<redacted-token>"),
    # Telegram bot token: 8-12 digits : 30+ chars
    (re.compile(r"\b\d{8,12}:[A-Za-z0-9_-]{30,}\b"), "<redacted-token>"),
    # OpenRouter, OpenAI, Anthropic key prefixes
    (re.compile(r"\bsk-or-[A-Za-z0-9-]{20,}\b"), "<redacted-or-key>"),
    (re.compile(r"\bsk-ant-[A-Za-z0-9-]{20,}\b"), "<redacted-ant-key>"),
    (re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"), "<redacted-sk-key>"),
    # JWT
    (re.compile(r"\beyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"), "<redacted-jwt>"),
    # Bearer token
    (re.compile(r"(?i)Bearer\s+[A-Za-z0-9._-]{20,}"), "Bearer <redacted>"),
    # Authorization header — consume full header value (case-insensitive)
    (re.compile(r"(?i)Authorization:[^\r\n]+"), "Authorization: <redacted>"),
    # Set-Cookie header (case-insensitive)
    (re.compile(r"(?i)Set-Cookie:\s*[^\r\n]+"), "Set-Cookie: <redacted>"),
    # Basic-auth in URLs: https?://user:pass@host
    (re.compile(r"(https?://)[^:/@\s]+:[^@/\s]+@"), r"\1<redacted-creds>@"),
    # URL query: token=..., apikey=..., api_key=..., key=...
    (re.compile(r"([?&](?:token|apikey|api_key|key|secret|password|access_token)=)[^&\s]+", re.IGNORECASE),
     r"\1<redacted>"),
]

# --- Heuristic key-name regex (default-deny for string values) ---
_HEURISTIC_KEY_RE = re.compile(r"(?i).*(token|secret|password|api_?key|cookie|auth).*")

# --- Allow-lists ---
_BUILTIN_ALLOW_LIST: set[str] = set()
_USER_ALLOW_LIST_EXTRA: set[str] = set()
_KNOWN_SECRET_KEYS: dict[str, set[str]] = {}


def _data_path(filename: str) -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "..", "resources", "data", filename)


def _load_resources_once():
    global _BUILTIN_ALLOW_LIST, _KNOWN_SECRET_KEYS
    if _BUILTIN_ALLOW_LIST:  # already loaded
        return
    try:
        with open(_data_path("redaction_allowlist.json"), "r", encoding="utf-8") as f:
            _BUILTIN_ALLOW_LIST = set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        _BUILTIN_ALLOW_LIST = set()
    try:
        with open(_data_path("known_secret_keys.json"), "r", encoding="utf-8") as f:
            data = json.load(f)
        _KNOWN_SECRET_KEYS = {k: set(v) for k, v in data.items()}
    except (FileNotFoundError, json.JSONDecodeError):
        _KNOWN_SECRET_KEYS = {}


def set_user_allow_list_extra(csv: str) -> None:
    global _USER_ALLOW_LIST_EXTRA
    _USER_ALLOW_LIST_EXTRA = {k.strip() for k in csv.split(",") if k.strip()}


def _effective_allow_list() -> set[str]:
    _load_resources_once()
    return _BUILTIN_ALLOW_LIST | _USER_ALLOW_LIST_EXTRA


def redact(text: str) -> str:
    """Apply all patterns. Returns redacted string. Bumps canary counter."""
    if not isinstance(text, str) or not text:
        return text
    out = text
    for pat, repl in _PATTERNS:
        out = pat.sub(repl, out)
    global _REDACTION_COUNT
    with _LOCK:
        _REDACTION_COUNT += 1
    return out


def should_redact_value(addon_id: str, key: str, value: Any) -> bool:
    """For (addon_id, key, value) tuples — decide if value is a secret.

    Type-aware: only string-typed values get redacted by heuristic.
    Explicit list (known_secret_keys per addon) overrides type check.
    allow_list overrides everything (positive).
    """
    _load_resources_once()
    if key in _effective_allow_list():
        return False
    # Explicit list per addon
    if addon_id in _KNOWN_SECRET_KEYS and key in _KNOWN_SECRET_KEYS[addon_id]:
        return True
    # Heuristic: regex match AND value is string
    if not _HEURISTIC_KEY_RE.match(key):
        return False
    # Type gate — type(v) is bool BEFORE isinstance(v, int) because bool < int
    if type(value) is bool:
        return False
    if isinstance(value, (int, float)):
        return False
    return isinstance(value, str)


def canary_self_test() -> tuple[bool, list[str]]:
    """Run redactor on canary string with all known secret patterns.
    Returns (ok, leaked_patterns)."""
    # Each test case is on its own line so the Authorization regex
    # (which consumes [^\r\n]+) cannot greedily swallow subsequent
    # patterns and mask them from observation. All 10 _PATTERNS entries
    # must be independently observable for the tripwire to be sound.
    canary_input = (
        "tg=1234567890:ABCdefGHIjklMNOpqrSTUvwxYZabcdefgHIjkl\n"
        "or=sk-or-v1-abc123def456ghi789jklmnopqrstuvwx\n"
        "ant=sk-ant-api03-abcdefghijklmnopqrstuvwxyz1234567890\n"
        "openai=sk-abc123def456ghi789jklmnopqrstuvwx\n"
        "jwt=eyJhbGciOiJIUzI1NiIs.eyJzdWIiOiIxMjM0NTY3.SflKxwRJSMeKKF2QT4f\n"
        "bearer=Bearer abc123def456ghi789jklmnopqrstuvwx\n"
        "Authorization: Bearer secret-here-123\n"
        "Set-Cookie: session=abc123; HttpOnly\n"
        "url=https://user:pass@host/x\n"
        "?token=long-secret-value-12345"
    )
    out = redact(canary_input)
    leaked = []
    for raw in ["1234567890:ABCdefGHIjklMNOpqrSTUvwxYZabcdefgHIjkl",
                "sk-or-v1-abc123def456ghi789jklmnopqrstuvwx",
                "sk-ant-api03-abcdefghijklmnopqrstuvwxyz1234567890",
                "sk-abc123def456ghi789jklmnopqrstuvwx",
                "eyJhbGciOiJIUzI1NiIs.eyJzdWIiOiIxMjM0NTY3.SflKxwRJSMeKKF2QT4f",
                "abc123def456ghi789jklmnopqrstuvwx",
                "secret-here-123",
                "session=abc123",
                "user:pass@",
                "token=long-secret-value-12345"]:
        if raw in out:
            leaked.append(raw)
    return (not leaked, leaked)


def should_run_canary() -> bool:
    """Called by LLM client; returns True every _CANARY_INTERVAL redactions."""
    with _LOCK:
        return _REDACTION_COUNT > 0 and _REDACTION_COUNT % _CANARY_INTERVAL == 0
