"""Unit tests for lib.telegram.auth — setup_secret + chat_allowlist."""
from __future__ import annotations
import json
import os
import sys
import pytest
from unittest import mock


@pytest.fixture(autouse=True)
def setup(tmp_path, monkeypatch):
    """Fake xbmcvfs + re-bind state_paths.xbmcvfs to this test's fake.
    Same pattern as test_secrets.py / test_state_paths.py."""
    fake = mock.MagicMock()
    fake.translatePath.side_effect = lambda p: str(tmp_path / p.replace("special://", ""))
    fake.mkdirs.side_effect = lambda p: os.makedirs(fake.translatePath(p), exist_ok=True) or True
    monkeypatch.setitem(sys.modules, "xbmcvfs", fake)
    if "lib.state_paths" in sys.modules:
        monkeypatch.setattr(sys.modules["lib.state_paths"], "xbmcvfs", fake)
    from lib import state_paths, secrets
    state_paths.ensure_dirs()
    secrets.invalidate_cache()
    yield


def test_generate_setup_secret_stores_and_returns():
    """generate_setup_secret returns a urlsafe token + writes it to secrets store."""
    from lib.telegram import auth
    from lib import secrets
    s = auth.generate_setup_secret()
    assert isinstance(s, str) and len(s) >= 8
    assert secrets.get_secret("setup_secret") == s
    assert auth.current_setup_secret() == s


def test_current_setup_secret_none_when_unset():
    from lib.telegram import auth
    assert auth.current_setup_secret() is None


def test_chat_allowlist_empty_when_no_file():
    from lib.telegram import auth
    assert auth.chat_allowlist() == []


def test_try_authorize_first_start_success_adds_chat_clears_secret():
    """Valid secret → chat_id appended, setup_secret deleted from secrets store."""
    from lib.telegram import auth
    from lib import secrets
    s = auth.generate_setup_secret()
    ok = auth.try_authorize_first_start(42, s)
    assert ok is True
    assert 42 in auth.chat_allowlist()
    # setup_secret cleared
    assert secrets.get_secret("setup_secret") is None
    # Idempotent: second valid attempt with stale secret fails (cleared)
    ok2 = auth.try_authorize_first_start(99, s)
    assert ok2 is False


def test_try_authorize_first_start_rejects_wrong_secret():
    """Wrong secret → returns False, allowlist unchanged, setup_secret intact."""
    from lib.telegram import auth
    from lib import secrets
    auth.generate_setup_secret()  # generate but don't capture
    ok = auth.try_authorize_first_start(7, "wrong-secret-xyz")
    assert ok is False
    assert auth.chat_allowlist() == []
    assert secrets.get_secret("setup_secret") is not None


def test_is_authorized_reads_allowlist():
    from lib.telegram import auth
    s = auth.generate_setup_secret()
    auth.try_authorize_first_start(123, s)
    assert auth.is_authorized(123) is True
    assert auth.is_authorized(999) is False


def test_reset_bot_owner_clears_allowlist_and_returns_new_secret():
    """reset_bot_owner empties allowlist + generates fresh setup_secret."""
    from lib.telegram import auth
    s1 = auth.generate_setup_secret()
    auth.try_authorize_first_start(42, s1)
    assert 42 in auth.chat_allowlist()
    s2 = auth.reset_bot_owner()
    assert isinstance(s2, str) and len(s2) >= 8
    assert s2 != s1
    assert auth.chat_allowlist() == []
    assert auth.current_setup_secret() == s2
