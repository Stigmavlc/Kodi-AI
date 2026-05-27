import pytest


def test_normalize_strips_memory_addresses():
    from lib.prefilter import normalize_signature
    s = "Object at 0x7f8a1234abcd raised something"
    sig = normalize_signature(s)
    assert "0x" not in sig
    assert "<addr>" in sig


def test_normalize_strips_line_numbers_in_tracebacks():
    from lib.prefilter import normalize_signature
    s = 'File "/foo/bar.py", line 123, in baz'
    sig = normalize_signature(s)
    assert "line 123" not in sig
    assert "line <N>" in sig


def test_normalize_strips_iso_timestamps():
    from lib.prefilter import normalize_signature
    s = "2026-05-26T18:04:11.123Z something happened"
    sig = normalize_signature(s)
    assert "2026" not in sig


def test_normalize_strips_uuids():
    from lib.prefilter import normalize_signature
    s = "Request id 550e8400-e29b-41d4-a716-446655440000 failed"
    sig = normalize_signature(s)
    assert "550e8400" not in sig
    assert "<uuid>" in sig


def test_normalize_basenames_file_paths():
    from lib.prefilter import normalize_signature
    s = 'File "/home/user/.kodi/addons/plugin.video.seren/lib/foo.py", line 5'
    sig = normalize_signature(s)
    assert "/home/user" not in sig
    assert "foo.py" in sig


def test_two_similar_tracebacks_cluster_same():
    from lib.prefilter import cluster_id_for
    a = 'File "/a/b.py", line 12, in x\nException at 0x7f8a1\nSimilar error'
    b = 'File "/a/b.py", line 99, in x\nException at 0xdeadbeef\nSimilar error'
    assert cluster_id_for(a) == cluster_id_for(b)


def test_is_benign_known_noise():
    from lib.prefilter import is_benign
    assert is_benign("NOTICE: Samba Initialize: Loading the network drivers...")
    assert is_benign("DEBUG: CDvdPlayer::ProcessAudioData done")


def test_is_benign_returns_false_for_real_errors():
    from lib.prefilter import is_benign
    assert not is_benign("ERROR: failed to load addon plugin.video.seren")
    assert not is_benign("CRITICAL: out of memory")
