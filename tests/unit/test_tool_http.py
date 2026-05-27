import pytest, responses

@responses.activate
def test_http_get_success():
    responses.add(responses.GET, "https://example.com/x", body="hello", status=200)
    from lib.tools.http import http_get
    res = http_get(url="https://example.com/x")
    assert res.success
    assert res.output["status"] == 200
    assert res.output["body_text"] == "hello"

def test_http_get_rejects_non_https():
    from lib.tools.http import http_get
    res = http_get(url="http://evil.example.com/x")
    assert not res.success
    assert "HTTPS" in res.error

def test_http_get_allows_localhost():
    from lib.tools.http import http_get
    res = http_get(url="http://127.0.0.1:1/x", timeout_s=0.1)
    assert "HTTPS" not in (res.error or "")

@responses.activate
def test_http_get_truncates_at_size_cap():
    responses.add(responses.GET, "https://example.com/big", body="x" * 3_000_000, status=200)
    from lib.tools.http import http_get
    res = http_get(url="https://example.com/big", max_bytes=1024)
    assert res.success
    assert len(res.output["body_text"]) <= 1024
