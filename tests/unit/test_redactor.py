import pytest


def test_redact_telegram_bot_token():
    from lib.redactor import redact
    s = "Got token 1234567890:ABCdefGHIjklMNOpqrSTUvwxYZabcdefgHIjkl in logs"
    assert "1234567890:ABCdefGHIjklMNOpqrSTUvwxYZabcdefgHIjkl" not in redact(s)
    assert "<redacted>" in redact(s) or "<redacted-token>" in redact(s)


def test_redact_openrouter_key():
    from lib.redactor import redact
    s = "Auth: sk-or-v1-abc123def456ghi789jklmnopqrstuvwx"
    assert "sk-or" not in redact(s) or "<redacted>" in redact(s)


def test_redact_anthropic_openai_key():
    from lib.redactor import redact
    s = "key=sk-ant-api03-abcdefghijklmnopqrstuvwxyz1234567890"
    assert "sk-ant" not in redact(s)


def test_redact_jwt():
    from lib.redactor import redact
    jwt = "eyJhbGciOiJIUzI1NiIs.eyJzdWIiOiIxMjM0NTY3.SflKxwRJSMeKKF2QT4f"
    assert jwt not in redact(f"Bearer {jwt}")


def test_redact_authorization_header():
    from lib.redactor import redact
    s = "Authorization: Bearer some-token-here-12345"
    out = redact(s)
    assert "some-token-here-12345" not in out
    assert "<redacted>" in out


def test_redact_basic_auth_url():
    from lib.redactor import redact
    s = "GET https://user:secret@example.com/path"
    out = redact(s)
    assert "user:secret@" not in out


def test_redact_set_cookie_case_insensitive():
    from lib.redactor import redact
    s = "set-cookie: session=abc123; HttpOnly"
    out = redact(s)
    assert "abc123" not in out


def test_redact_preserves_non_secrets():
    from lib.redactor import redact
    s = "This is a normal log message about a thing."
    assert redact(s) == s


def test_canary_self_test_succeeds():
    from lib.redactor import canary_self_test
    ok, leaked = canary_self_test()
    assert ok, f"leaked: {leaked}"


def test_should_redact_value_for_known_secret_addon_key():
    from lib.redactor import should_redact_value
    assert should_redact_value("plugin.video.seren", "real_debrid_token", "abc")


def test_should_redact_value_heuristic_match_string():
    from lib.redactor import should_redact_value
    assert should_redact_value("some.addon", "my_api_token", "abc123")


def test_should_redact_value_heuristic_skips_bool():
    from lib.redactor import should_redact_value
    assert not should_redact_value("some.addon", "api_key_required", True)
    assert not should_redact_value("some.addon", "cookie_consent_shown", False)


def test_should_redact_value_heuristic_skips_int():
    from lib.redactor import should_redact_value
    assert not should_redact_value("some.addon", "password_min_length", 8)


def test_allow_list_overrides_heuristic():
    from lib.redactor import should_redact_value
    # auth_method is in allow_list, regex matches but allow_list wins
    assert not should_redact_value("some.addon", "auth_method", "none")


def test_user_allow_list_extra_merges():
    from lib import redactor
    redactor.set_user_allow_list_extra("my_custom_key,other_key")
    try:
        assert not redactor.should_redact_value("a", "my_custom_key", "abc")
    finally:
        redactor.set_user_allow_list_extra("")
