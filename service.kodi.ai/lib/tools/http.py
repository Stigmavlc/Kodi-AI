"""http_get: HTTPS-only (localhost exception), size + timeout caps.

Spec: §4.6.
"""
from __future__ import annotations
import requests
from . import tool, ToolResult


def _is_loopback(url: str) -> bool:
    return any(loop in url for loop in ("//127.0.0.1", "//localhost", "//::1"))


@tool(
    name="http_get",
    description="HTTP GET. HTTPS only (loopback exception). Size + timeout capped.",
    schema={
        "type": "object",
        "properties": {
            "url": {"type": "string"},
            "timeout_s": {"type": "integer", "default": 15},
            "max_bytes": {"type": "integer", "default": 1048576},
        },
        "required": ["url"],
    },
    tier="immediate", safety_class="read_only",
)
def http_get(url: str, timeout_s: int = 15, max_bytes: int = 1_048_576) -> ToolResult:
    if not url.startswith("https://") and not _is_loopback(url):
        return ToolResult(success=False, requested=f"http_get({url})",
                          output=None, actual_state_after=None,
                          error="HTTPS required (loopback exception only)",
                          snapshot_id=None, cost_seconds=0.0)
    try:
        r = requests.get(url, timeout=(3, timeout_s), stream=True)
    except Exception as e:
        return ToolResult(success=False, requested=f"http_get({url})", output=None,
                          actual_state_after=None, error=str(e),
                          snapshot_id=None, cost_seconds=0.0)
    body = r.raw.read(max_bytes, decode_content=True) if r.raw else b""
    body_text = body.decode("utf-8", errors="replace")
    r.close()
    return ToolResult(
        success=True, requested=f"http_get({url})",
        output={"status": r.status_code, "headers": dict(r.headers), "body_text": body_text},
        actual_state_after=None, error=None, snapshot_id=None, cost_seconds=0.0,
    )
