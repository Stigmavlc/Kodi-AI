"""Unit tests for lib.telegram.formatters — pure functions, no fixtures needed."""
from __future__ import annotations


def test_escape_html_quotes_left_unescaped():
    """escape_html(quote=False) leaves quotes alone but escapes <, >, &."""
    from lib.telegram.formatters import escape_html
    assert escape_html("<b>hi</b>") == "&lt;b&gt;hi&lt;/b&gt;"
    assert escape_html("AT&T") == "AT&amp;T"
    # Quotes intentionally NOT escaped at body level (saves bytes; href escapes them separately)
    assert escape_html('say "hi"') == 'say "hi"'


def test_escape_href_quotes_escaped():
    """escape_href(quote=True) escapes quotes for safe attribute embedding."""
    from lib.telegram.formatters import escape_href
    s = escape_href('https://example.com/?q="a&b"')
    assert "&quot;" in s
    assert "&amp;" in s


def test_format_log_block_wraps_in_pre_and_escapes():
    """format_log_block escapes content before wrapping in <pre>."""
    from lib.telegram.formatters import format_log_block
    out = format_log_block("traceback: <NoneType>")
    assert out == "<pre>traceback: &lt;NoneType&gt;</pre>"


def test_truncate_keeps_short_text_intact():
    """truncate returns text unchanged when under limit; appends marker otherwise."""
    from lib.telegram.formatters import truncate, LIMIT
    assert truncate("hello") == "hello"
    big = "x" * (LIMIT + 500)
    out = truncate(big)
    assert len(out) <= LIMIT
    assert out.endswith("... (truncated, see /status for full)")
    assert out.startswith("x" * (LIMIT - 100))


def test_split_for_telegram_emits_part_headers():
    """split_for_telegram emits (part N/M) header on each chunk when over limit."""
    from lib.telegram.formatters import split_for_telegram, LIMIT
    big = "y" * (LIMIT * 2 + 100)
    parts = split_for_telegram(big)
    assert len(parts) >= 2
    assert parts[0].startswith("(part 1/")
    assert parts[-1].startswith(f"(part {len(parts)}/{len(parts)})")
    # Short text → single part, no header
    short = split_for_telegram("hi")
    assert short == ["hi"]
