"""HTML formatters for Telegram (parse_mode=HTML, NOT MarkdownV2).
Spec §4.5: html.escape on all dynamic content, href separately escaped
with quote=True, log content in <pre> after escape, 4000-char limit
with multi-part split."""
from __future__ import annotations
import html

LIMIT = 4000

def escape_html(s: str) -> str:
    return html.escape(s, quote=False)

def escape_href(url: str) -> str:
    return html.escape(url, quote=True)

def format_log_block(log_text: str) -> str:
    return f"<pre>{escape_html(log_text)}</pre>"

def truncate(text: str, limit: int = LIMIT) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 100] + "\n\n... (truncated, see /status for full)"

def split_for_telegram(text: str, limit: int = LIMIT) -> list[str]:
    if len(text) <= limit:
        return [text]
    parts: list[str] = []
    pos = 0
    while pos < len(text):
        parts.append(text[pos : pos + limit - 50])
        pos += limit - 50
    return [f"(part {i+1}/{len(parts)})\n{p}" for i, p in enumerate(parts)]
