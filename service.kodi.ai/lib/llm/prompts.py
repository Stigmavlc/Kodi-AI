"""Prompt loader + content-addressable hash.

Each prompt file: frontmatter (---\\n... \\n---) + body. Hash computed over
the entire file MINUS any prompt_hash: line (avoids self-reference).
Recorded in audit log every llm_call for behavior-regression debugging.

Spec: §5.6.
"""
from __future__ import annotations
import hashlib
import os
import re
from dataclasses import dataclass

_PROMPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts")
_HASH_LINE_RE = re.compile(r"^prompt_hash:\s.*\n", re.MULTILINE)
_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)


@dataclass(frozen=True)
class Prompt:
    name: str
    version: str
    body: str
    hash: str


def _hash_body_excluding_prompt_hash(raw: str) -> str:
    """SHA-256 of file content with any prompt_hash line stripped."""
    stripped = _HASH_LINE_RE.sub("", raw)
    return hashlib.sha256(stripped.encode("utf-8")).hexdigest()


def _parse_frontmatter(raw: str) -> tuple[dict, str]:
    m = _FRONTMATTER_RE.match(raw)
    if not m:
        return {}, raw
    frontmatter_text = m.group(1)
    body = raw[m.end():]
    meta = {}
    for line in frontmatter_text.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip()
    return meta, body


_CACHE: dict[str, Prompt] = {}


def load(name: str) -> Prompt:
    if name in _CACHE:
        return _CACHE[name]
    path = os.path.join(_PROMPTS_DIR, f"{name}.md")
    if not os.path.exists(path):
        raise FileNotFoundError(f"prompt not found: {name} ({path})")
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()
    meta, body = _parse_frontmatter(raw)
    p = Prompt(
        name=meta.get("prompt_name", name),
        version=meta.get("prompt_version", "0.0.0"),
        body=body,
        hash=_hash_body_excluding_prompt_hash(raw),
    )
    _CACHE[name] = p
    return p
