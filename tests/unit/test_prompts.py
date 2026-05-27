import hashlib
import pytest


def test_load_prompt_returns_body_and_metadata():
    from lib.llm.prompts import load
    p = load("triage_system")
    assert p.name == "triage_system"
    assert p.version == "1.0.0"
    assert "CRITICAL" in p.body
    assert "ADVISORY" in p.body
    assert "IGNORE" in p.body
    assert "---" not in p.body  # frontmatter stripped


def test_load_reasoner_prompt():
    from lib.llm.prompts import load
    p = load("reasoner_system")
    assert p.version == "1.0.0"
    assert "Kodi-AI" in p.body


def test_load_chat_prompt():
    from lib.llm.prompts import load
    p = load("chat_system")
    assert p.version == "1.0.0"


def test_prompt_hash_stable():
    from lib.llm.prompts import load
    p1 = load("triage_system")
    p2 = load("triage_system")
    assert p1.hash == p2.hash
    # Hash is sha256 hex (64 chars)
    assert len(p1.hash) == 64


def test_prompt_hash_omits_prompt_hash_line():
    """Spec §5.6: hash entire file with prompt_hash line stripped."""
    from lib.llm.prompts import load, _hash_body_excluding_prompt_hash
    body = "---\nprompt_name: x\nprompt_version: 1.0.0\nprompt_hash: abc\n---\nbody"
    body_without = "---\nprompt_name: x\nprompt_version: 1.0.0\n---\nbody"
    h1 = _hash_body_excluding_prompt_hash(body)
    h2 = _hash_body_excluding_prompt_hash(body_without)
    assert h1 == h2


def test_unknown_prompt_raises():
    from lib.llm.prompts import load
    with pytest.raises(FileNotFoundError):
        load("nonexistent_prompt")
