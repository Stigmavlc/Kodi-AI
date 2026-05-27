"""Signature normalization + benign-noise allowlist for log clustering.

Used by lib/log_watcher.py to compute stable cluster_ids so two stack traces
differing only by memory addresses / line numbers / timestamps cluster as
one incident (preventing duplicate triage spend).

is_benign() filters known-harmless Kodi noise before signature hashing.

Spec: §1.4.
"""
from __future__ import annotations
import hashlib
import os
import re

# Patterns applied IN ORDER. Later patterns may match output of earlier.
_NORMALIZERS: list[tuple[re.Pattern, str]] = [
    # Memory addresses
    (re.compile(r"0x[0-9a-fA-F]+"), "<addr>"),
    # Line numbers in tracebacks
    (re.compile(r"\bline\s+\d+\b"), "line <N>"),
    # ISO-8601 timestamps
    (re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})?"), "<ts>"),
    # Unix epoch (10-digit timestamps)
    (re.compile(r"\b1[6789]\d{8}\b"), "<epoch>"),
    # UUIDs
    (re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"), "<uuid>"),
    # File paths (preserve basename)
    (re.compile(r'"(/[^"]+/)([^/"]+)"'), r'"<path>/\2"'),
    # Numbers in trailing details (port numbers, sizes)
    (re.compile(r"\b\d{4,}\b"), "<num>"),
]


def normalize_signature(text: str) -> str:
    out = text
    for pat, repl in _NORMALIZERS:
        out = pat.sub(repl, out)
    return out


def cluster_id_for(text: str) -> str:
    sig = normalize_signature(text)
    return hashlib.sha256(sig.encode("utf-8")).hexdigest()[:16]


_BENIGN_PATTERNS: list[re.Pattern] = [
    re.compile(r"NOTICE:\s*Samba Initialize", re.IGNORECASE),
    re.compile(r"DEBUG:\s*CDvdPlayer::ProcessAudioData done", re.IGNORECASE),
    re.compile(r"INFO:\s*Loading\s+skin\s+settings", re.IGNORECASE),
    re.compile(r"DEBUG:\s*CXBMCApp::onIdle", re.IGNORECASE),
    # Add more as observed in practice (V1 starter list)
]


def is_benign(line: str) -> bool:
    return any(p.search(line) for p in _BENIGN_PATTERNS)
