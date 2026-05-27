# tests/unit/test_tool_telegram_ask.py
"""ask_user — pause-signal tool. Returns NEEDS_USER marker; reasoner detects
.requires_user_confirmation=True and triggers pause flow.

Spec: §1.7.
"""


def test_ask_user_returns_needs_user_marker():
    from lib.tools.telegram_ask import ask_user
    res = ask_user(question="Apply this fix?", options=["Yes", "No"])
    assert not res.success
    assert res.error == "NEEDS_USER"
    assert res.output["question"] == "Apply this fix?"
    assert ask_user.requires_user_confirmation is True
