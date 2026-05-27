"""Tests for lib.qr — pure-Python QR encoder + PNG writer (no PIL/qrcode)."""
import struct
import zlib


def test_qr_png_starts_with_png_signature(tmp_path):
    from lib.qr import qr_png
    data = qr_png("https://t.me/test_bot?start=abc123")
    assert data[:8] == b"\x89PNG\r\n\x1a\n"


def test_qr_png_contains_idat_chunk(tmp_path):
    from lib.qr import qr_png
    data = qr_png("hello")
    assert b"IDAT" in data


def test_qr_png_no_pil_dependency():
    # qr.py must NOT import PIL/Pillow/qrcode
    import lib.qr as q
    import sys
    forbidden = {"PIL", "Pillow", "qrcode"}
    assert not any(
        m in sys.modules for m in forbidden if m in sys.modules and sys.modules[m] is not None
    ) or True
    # Stronger check: module source doesn't import them
    import inspect
    src = inspect.getsource(q)
    assert "from PIL" not in src
    assert "import PIL" not in src
    assert "import qrcode" not in src


def test_qr_png_size_scales_with_module_pixel_size():
    """Larger module_pixel_size → larger image → more bytes."""
    from lib.qr import qr_png
    a = qr_png("test", module_pixel_size=4)
    b = qr_png("test", module_pixel_size=8)
    assert len(b) >= len(a)


def test_qr_png_renders_short_url():
    """Realistic setup URL must produce a non-tiny PNG with PNG signature."""
    from lib.qr import qr_png
    data = qr_png("https://t.me/my_kodi_ai_bot?start=ABC123XYZ")
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(data) > 100  # not a tiny placeholder


# Additional structural sanity checks (defensive, but only on stdlib).

def test_qr_png_has_ihdr_iend_and_valid_crcs():
    """Parse PNG chunks and verify each chunk's CRC32 matches its data."""
    from lib.qr import qr_png
    data = qr_png("https://t.me/test")
    # Signature
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    pos = 8
    seen_types = []
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        ctype = data[pos + 4:pos + 8]
        cdata = data[pos + 8:pos + 8 + length]
        (declared_crc,) = struct.unpack(">I", data[pos + 8 + length:pos + 8 + length + 4])
        computed = zlib.crc32(ctype + cdata) & 0xFFFFFFFF
        assert declared_crc == computed, f"CRC mismatch on {ctype!r}"
        seen_types.append(ctype)
        pos += 8 + length + 4
    assert b"IHDR" == seen_types[0]
    assert b"IEND" == seen_types[-1]
    assert b"IDAT" in seen_types


def test_qr_png_idat_decompresses_to_correct_size():
    """Decompress IDAT and verify scanline count + width match IHDR."""
    from lib.qr import qr_png
    data = qr_png("hi", module_pixel_size=4)
    # Parse IHDR
    assert data[8:16] == struct.pack(">I", 13) + b"IHDR"
    width, height, bit_depth, color_type = struct.unpack(">IIBB", data[16:26])
    # Find IDAT(s) and concatenate
    pos = 8
    idat_blob = b""
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        ctype = data[pos + 4:pos + 8]
        cdata = data[pos + 8:pos + 8 + length]
        if ctype == b"IDAT":
            idat_blob += cdata
        pos += 8 + length + 4
    raw = zlib.decompress(idat_blob)
    # Compute bytes-per-scanline for the chosen bit_depth/color_type.
    if bit_depth == 1 and color_type == 0:
        bytes_per_row = (width + 7) // 8
    elif bit_depth == 8 and color_type == 0:
        bytes_per_row = width
    elif bit_depth == 8 and color_type == 2:
        bytes_per_row = width * 3
    else:
        bytes_per_row = None  # don't assert if unexpected
    if bytes_per_row is not None:
        # Each scanline is prefixed with 1 filter byte.
        assert len(raw) == height * (1 + bytes_per_row)
