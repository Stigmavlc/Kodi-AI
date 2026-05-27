import re
import sys
import pytest
from unittest import mock


@pytest.fixture
def mock_xbmc(monkeypatch):
    fake = mock.MagicMock()
    fake.LOGINFO = 1
    captured = []
    fake.log.side_effect = lambda msg, level=1: captured.append((msg, level))
    monkeypatch.setitem(sys.modules, "xbmc", fake)
    if "lib.log_sentinels" in sys.modules:
        monkeypatch.setattr(sys.modules["lib.log_sentinels"], "xbmc", fake)
    fake._captured = captured
    return fake


def test_reason_start_written_at_loginfo(mock_xbmc):
    from lib.log_sentinels import reason_start
    reason_start("abc123")
    msg, level = mock_xbmc._captured[-1]
    assert msg == "[service.kodi.ai] reason-start abc123"
    assert level == mock_xbmc.LOGINFO


def test_reason_end_written_at_loginfo(mock_xbmc):
    from lib.log_sentinels import reason_end
    reason_end("abc123")
    msg, level = mock_xbmc._captured[-1]
    assert msg == "[service.kodi.ai] reason-end abc123"


def test_parse_sentinel_extracts_session_id():
    from lib.log_sentinels import parse_sentinel
    assert parse_sentinel("[service.kodi.ai] reason-start abc123") == ("start", "abc123")
    assert parse_sentinel("[service.kodi.ai] reason-end xyz789") == ("end", "xyz789")
    assert parse_sentinel("some other line") is None
    assert parse_sentinel("[plugin.video.seren] error") is None
