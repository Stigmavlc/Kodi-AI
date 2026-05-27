"""Pure-Python QR encoder + PNG writer (stdlib zlib only).

Public API
----------
qr_png(text, *, module_pixel_size=8, ecc_level="M") -> bytes

Generates a scannable QR code encoding ``text`` as a PNG byte string.
NO external dependencies — pure stdlib (``zlib``, ``struct``). Algorithm
follows the public ISO/IEC 18004 QR standard:

* mode-8 byte segment (UTF-8)
* error correction levels L / M (default) / Q / H
* version 1..40 (auto-selected by content length and ecc level)
* Reed-Solomon over GF(256) with primitive polynomial 0x11D (x^8 + x^4 + x^3 + x^2 + 1)
* mask 0..7 with lowest-penalty selection per QR spec
* PNG is 1-bit grayscale: black modules + white quiet zone, scanlines compressed
  with stdlib zlib (Adler32 inside DEFLATE), each chunk wrapped with CRC32

The module is used by the Kodi setup wizard to render the setup_secret as
a scannable QR. Spec: §5.2, §7.2.
"""
from __future__ import annotations

import struct
import zlib

# ---------------------------------------------------------------------------
# 1. ISO/IEC 18004 capacity + ECC tables (versions 1..40, byte mode, L/M/Q/H).
# ---------------------------------------------------------------------------
#
# For each version, ``BYTE_CAPACITY[ecc][version-1]`` = maximum number of
# 8-bit-mode data bytes the symbol can carry (NOT counting mode indicator
# + character count indicator + terminator + padding). Pulled from the QR
# spec, Table 7. Versions 1..40 inclusive.
#
# Test sanity: version 1-M holds 14 bytes; version 5-Q holds 62 bytes; etc.

BYTE_CAPACITY = {
    "L": [
        17, 32, 53, 78, 106, 134, 154, 192, 230, 271,
        321, 367, 425, 458, 520, 586, 644, 718, 792, 858,
        929, 1003, 1091, 1171, 1273, 1367, 1465, 1528, 1628, 1732,
        1840, 1952, 2068, 2188, 2303, 2431, 2563, 2699, 2809, 2953,
    ],
    "M": [
        14, 26, 42, 62, 84, 106, 122, 152, 180, 213,
        251, 287, 331, 362, 412, 450, 504, 560, 624, 666,
        711, 779, 857, 911, 997, 1059, 1125, 1190, 1264, 1370,
        1452, 1538, 1628, 1722, 1809, 1911, 1989, 2099, 2213, 2331,
    ],
    "Q": [
        11, 20, 32, 46, 60, 74, 86, 108, 130, 151,
        177, 203, 241, 258, 292, 322, 364, 394, 442, 482,
        509, 565, 611, 661, 715, 751, 805, 868, 908, 982,
        1030, 1112, 1168, 1228, 1283, 1351, 1423, 1499, 1579, 1663,
    ],
    "H": [
        7, 14, 24, 34, 44, 58, 64, 84, 98, 119,
        137, 155, 177, 194, 220, 250, 280, 310, 338, 382,
        403, 439, 461, 511, 535, 593, 625, 658, 698, 742,
        790, 842, 898, 958, 983, 1051, 1093, 1139, 1219, 1273,
    ],
}

# Total bit capacity of a QR symbol (number of data + ecc codewords * 8 + remainder bits).
# Table 1 from the spec.
TOTAL_CODEWORDS = [
    26, 44, 70, 100, 134, 172, 196, 242, 292, 346,
    404, 466, 532, 581, 655, 733, 815, 901, 991, 1085,
    1156, 1258, 1364, 1474, 1588, 1706, 1828, 1921, 2051, 2185,
    2323, 2465, 2611, 2761, 2876, 3034, 3196, 3362, 3532, 3706,
]

# Number of remainder bits per version (Table 1).
REMAINDER_BITS = [
    0, 7, 7, 7, 7, 7, 0, 0, 0, 0,
    0, 0, 0, 3, 3, 3, 3, 3, 3, 3,
    4, 4, 4, 4, 4, 4, 4, 3, 3, 3,
    3, 3, 3, 3, 0, 0, 0, 0, 0, 0,
]

# Error correction characteristics: for each (version, ecc) we need
#   (num_ecc_codewords_per_block, num_blocks_group1, data_codewords_group1,
#    num_blocks_group2, data_codewords_group2)
# Source: ISO/IEC 18004 Table 9 (transcribed for versions 1..40, L/M/Q/H).
# Each row is for (ec_codewords_per_block, blocks_g1, k_g1, blocks_g2, k_g2).
# If a version has only one group, blocks_g2 == 0 and k_g2 == 0.
EC_TABLE = {
    "L": [
        (7, 1, 19, 0, 0),
        (10, 1, 34, 0, 0),
        (15, 1, 55, 0, 0),
        (20, 1, 80, 0, 0),
        (26, 1, 108, 0, 0),
        (18, 2, 68, 0, 0),
        (20, 2, 78, 0, 0),
        (24, 2, 97, 0, 0),
        (30, 2, 116, 0, 0),
        (18, 2, 68, 2, 69),
        (20, 4, 81, 0, 0),
        (24, 2, 92, 2, 93),
        (26, 4, 107, 0, 0),
        (30, 3, 115, 1, 116),
        (22, 5, 87, 1, 88),
        (24, 5, 98, 1, 99),
        (28, 1, 107, 5, 108),
        (30, 5, 120, 1, 121),
        (28, 3, 113, 4, 114),
        (28, 3, 107, 5, 108),
        (28, 4, 116, 4, 117),
        (28, 2, 111, 7, 112),
        (30, 4, 121, 5, 122),
        (30, 6, 117, 4, 118),
        (26, 8, 106, 4, 107),
        (28, 10, 114, 2, 115),
        (30, 8, 122, 4, 123),
        (30, 3, 117, 10, 118),
        (30, 7, 116, 7, 117),
        (30, 5, 115, 10, 116),
        (30, 13, 115, 3, 116),
        (30, 17, 115, 0, 0),
        (30, 17, 115, 1, 116),
        (30, 13, 115, 6, 116),
        (30, 12, 121, 7, 122),
        (30, 6, 121, 14, 122),
        (30, 17, 122, 4, 123),
        (30, 4, 122, 18, 123),
        (30, 20, 117, 4, 118),
        (30, 19, 118, 6, 119),
    ],
    "M": [
        (10, 1, 16, 0, 0),
        (16, 1, 28, 0, 0),
        (26, 1, 44, 0, 0),
        (18, 2, 32, 0, 0),
        (24, 2, 43, 0, 0),
        (16, 4, 27, 0, 0),
        (18, 4, 31, 0, 0),
        (22, 2, 38, 2, 39),
        (22, 3, 36, 2, 37),
        (26, 4, 43, 1, 44),
        (30, 1, 50, 4, 51),
        (22, 6, 36, 2, 37),
        (22, 8, 37, 1, 38),
        (24, 4, 40, 5, 41),
        (24, 5, 41, 5, 42),
        (28, 7, 45, 3, 46),
        (28, 10, 46, 1, 47),
        (26, 9, 43, 4, 44),
        (26, 3, 44, 11, 45),
        (26, 3, 41, 13, 42),
        (26, 17, 42, 0, 0),
        (28, 17, 46, 0, 0),
        (28, 4, 47, 14, 48),
        (28, 6, 45, 14, 46),
        (28, 8, 47, 13, 48),
        (28, 19, 46, 4, 47),
        (28, 22, 45, 3, 46),
        (28, 3, 45, 23, 46),
        (28, 21, 45, 7, 46),
        (28, 19, 47, 10, 48),
        (28, 2, 46, 29, 47),
        (28, 10, 46, 23, 47),
        (28, 14, 46, 21, 47),
        (28, 14, 46, 23, 47),
        (28, 12, 47, 26, 48),
        (28, 6, 47, 34, 48),
        (28, 29, 46, 14, 47),
        (28, 13, 46, 32, 47),
        (28, 40, 47, 7, 48),
        (28, 18, 47, 31, 48),
    ],
    "Q": [
        (13, 1, 13, 0, 0),
        (22, 1, 22, 0, 0),
        (18, 2, 17, 0, 0),
        (26, 2, 24, 0, 0),
        (18, 2, 15, 2, 16),
        (24, 4, 19, 0, 0),
        (18, 2, 14, 4, 15),
        (22, 4, 18, 2, 19),
        (20, 4, 16, 4, 17),
        (24, 6, 19, 2, 20),
        (28, 4, 22, 4, 23),
        (26, 4, 20, 6, 21),
        (24, 8, 20, 4, 21),
        (20, 11, 16, 5, 17),
        (30, 5, 24, 7, 25),
        (24, 15, 19, 2, 20),
        (28, 1, 22, 15, 23),
        (28, 17, 22, 1, 23),
        (26, 17, 21, 4, 22),
        (30, 15, 24, 5, 25),
        (28, 17, 22, 6, 23),
        (30, 7, 24, 16, 25),
        (30, 11, 24, 14, 25),
        (30, 11, 24, 16, 25),
        (30, 7, 24, 22, 25),
        (28, 28, 22, 6, 23),
        (30, 8, 23, 26, 24),
        (30, 4, 24, 31, 25),
        (30, 1, 23, 37, 24),
        (30, 15, 24, 25, 25),
        (30, 42, 24, 1, 25),
        (30, 10, 24, 35, 25),
        (30, 29, 24, 19, 25),
        (30, 44, 24, 7, 25),
        (30, 39, 24, 14, 25),
        (30, 46, 24, 10, 25),
        (30, 49, 24, 10, 25),
        (30, 48, 24, 14, 25),
        (30, 43, 24, 22, 25),
        (30, 34, 24, 34, 25),
    ],
    "H": [
        (17, 1, 9, 0, 0),
        (28, 1, 16, 0, 0),
        (22, 2, 13, 0, 0),
        (16, 4, 9, 0, 0),
        (22, 2, 11, 2, 12),
        (28, 4, 15, 0, 0),
        (26, 4, 13, 1, 14),
        (26, 4, 14, 2, 15),
        (24, 4, 12, 4, 13),
        (28, 6, 15, 2, 16),
        (24, 3, 12, 8, 13),
        (28, 7, 14, 4, 15),
        (22, 12, 11, 4, 12),
        (24, 11, 12, 5, 13),
        (24, 11, 12, 7, 13),
        (30, 3, 15, 13, 16),
        (28, 2, 14, 17, 15),
        (28, 2, 14, 19, 15),
        (26, 9, 13, 16, 14),
        (28, 15, 15, 10, 16),
        (30, 19, 16, 6, 17),
        (24, 34, 13, 0, 0),
        (30, 16, 15, 14, 16),
        (30, 30, 16, 2, 17),
        (30, 22, 15, 13, 16),
        (30, 33, 16, 4, 17),
        (30, 12, 15, 28, 16),
        (30, 11, 15, 31, 16),
        (30, 19, 15, 26, 16),
        (30, 23, 15, 25, 16),
        (30, 23, 15, 28, 16),
        (30, 19, 15, 35, 16),
        (30, 11, 15, 46, 16),
        (30, 59, 16, 1, 17),
        (30, 22, 15, 41, 16),
        (30, 2, 15, 64, 16),
        (30, 24, 15, 46, 16),
        (30, 42, 15, 32, 16),
        (30, 10, 15, 67, 16),
        (30, 20, 15, 61, 16),
    ],
}

# Alignment pattern centre coordinates per version (Table E.1 of ISO 18004).
# Version 1 has no alignment patterns.
ALIGNMENT_PATTERN_LOCATIONS = {
    1: [],
    2: [6, 18],
    3: [6, 22],
    4: [6, 26],
    5: [6, 30],
    6: [6, 34],
    7: [6, 22, 38],
    8: [6, 24, 42],
    9: [6, 26, 46],
    10: [6, 28, 50],
    11: [6, 30, 54],
    12: [6, 32, 58],
    13: [6, 34, 62],
    14: [6, 26, 46, 66],
    15: [6, 26, 48, 70],
    16: [6, 26, 50, 74],
    17: [6, 30, 54, 78],
    18: [6, 30, 56, 82],
    19: [6, 30, 58, 86],
    20: [6, 34, 62, 90],
    21: [6, 28, 50, 72, 94],
    22: [6, 26, 50, 74, 98],
    23: [6, 30, 54, 78, 102],
    24: [6, 28, 54, 80, 106],
    25: [6, 32, 58, 84, 110],
    26: [6, 30, 58, 86, 114],
    27: [6, 34, 62, 90, 118],
    28: [6, 26, 50, 74, 98, 122],
    29: [6, 30, 54, 78, 102, 126],
    30: [6, 26, 52, 78, 104, 130],
    31: [6, 30, 56, 82, 108, 134],
    32: [6, 34, 60, 86, 112, 138],
    33: [6, 30, 58, 86, 114, 142],
    34: [6, 34, 62, 90, 118, 146],
    35: [6, 30, 54, 78, 102, 126, 150],
    36: [6, 24, 50, 76, 102, 128, 154],
    37: [6, 28, 54, 80, 106, 132, 158],
    38: [6, 32, 58, 84, 110, 136, 162],
    39: [6, 26, 54, 82, 110, 138, 166],
    40: [6, 30, 58, 86, 114, 142, 170],
}

# Format information bits: pre-computed 15-bit strings for each (ecc, mask).
# Already include BCH(15,5) + XOR with the format mask 0x5412.
# Source: ISO/IEC 18004 Annex C.
ECC_LEVEL_BITS = {"L": 0b01, "M": 0b00, "Q": 0b11, "H": 0b10}
FORMAT_INFO_TABLE = {
    "L": [0x77C4, 0x72F3, 0x7DAA, 0x789D, 0x662F, 0x6318, 0x6C41, 0x6976],
    "M": [0x5412, 0x5125, 0x5E7C, 0x5B4B, 0x45F9, 0x40CE, 0x4F97, 0x4AA0],
    "Q": [0x355F, 0x3068, 0x3F31, 0x3A06, 0x24B4, 0x2183, 0x2EDA, 0x2BED],
    "H": [0x1689, 0x13BE, 0x1CE7, 0x19D0, 0x0762, 0x0255, 0x0D0C, 0x083B],
}

# Version information (for versions 7..40); 18-bit string with BCH(18,6).
VERSION_INFO_TABLE = {
    7: 0x07C94, 8: 0x085BC, 9: 0x09A99, 10: 0x0A4D3, 11: 0x0BBF6,
    12: 0x0C762, 13: 0x0D847, 14: 0x0E60D, 15: 0x0F928, 16: 0x10B78,
    17: 0x1145D, 18: 0x12A17, 19: 0x13532, 20: 0x149A6, 21: 0x15683,
    22: 0x168C9, 23: 0x177EC, 24: 0x18EC4, 25: 0x191E1, 26: 0x1AFAB,
    27: 0x1B08E, 28: 0x1CC1A, 29: 0x1D33F, 30: 0x1ED75, 31: 0x1F250,
    32: 0x209D5, 33: 0x216F0, 34: 0x228BA, 35: 0x2379F, 36: 0x24B0B,
    37: 0x2542E, 38: 0x26A64, 39: 0x27541, 40: 0x28C69,
}


# ---------------------------------------------------------------------------
# 2. Galois Field GF(256) arithmetic for Reed-Solomon.
# ---------------------------------------------------------------------------
#
# Primitive polynomial = 0x11D (x^8 + x^4 + x^3 + x^2 + 1), primitive element = 2.

def _build_gf_tables():
    exp = [0] * 512
    log = [0] * 256
    x = 1
    for i in range(255):
        exp[i] = x
        log[x] = i
        x <<= 1
        if x & 0x100:
            x ^= 0x11D
    # Duplicate so we can index exp[a + b] without modulo.
    for i in range(255, 512):
        exp[i] = exp[i - 255]
    return exp, log


_GF_EXP, _GF_LOG = _build_gf_tables()


def _gf_mul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return _GF_EXP[_GF_LOG[a] + _GF_LOG[b]]


def _rs_generator_poly(degree: int) -> list[int]:
    """Generator polynomial coefficients (highest power first) for RS(degree)."""
    poly = [1]
    for i in range(degree):
        # Multiply poly by (x - alpha^i).  alpha^i = _GF_EXP[i].
        new_poly = [0] * (len(poly) + 1)
        for j, c in enumerate(poly):
            new_poly[j] ^= c
            new_poly[j + 1] ^= _gf_mul(c, _GF_EXP[i])
        poly = new_poly
    return poly


def _rs_encode(data: list[int], ec_codewords: int) -> list[int]:
    """Return ``ec_codewords`` ECC bytes for ``data`` (highest-degree coeff first)."""
    gen = _rs_generator_poly(ec_codewords)
    # Polynomial division: result is the remainder.
    buffer = list(data) + [0] * ec_codewords
    for i in range(len(data)):
        lead = buffer[i]
        if lead == 0:
            continue
        for j, gc in enumerate(gen):
            buffer[i + j] ^= _gf_mul(gc, lead)
    return buffer[-ec_codewords:]


# ---------------------------------------------------------------------------
# 3. Version selection and bit-stream construction.
# ---------------------------------------------------------------------------

def _select_version(byte_len: int, ecc: str) -> int:
    """Return smallest version (1..40) whose byte capacity >= byte_len."""
    for v_idx, cap in enumerate(BYTE_CAPACITY[ecc]):
        if cap >= byte_len:
            return v_idx + 1
    raise ValueError(
        f"Input too large for QR ECC-{ecc}: {byte_len} bytes (max {BYTE_CAPACITY[ecc][-1]})"
    )


def _char_count_bits(version: int) -> int:
    """Number of bits in the byte-mode character count indicator for ``version``."""
    if 1 <= version <= 9:
        return 8
    return 16  # versions 10..40


def _encode_byte_segment(text: str, version: int, ecc: str) -> list[int]:
    """Build the full bit-stream (data + terminator + padding) as a list of 0/1.

    Output length equals the total number of data codewords for (version, ecc) * 8.
    """
    payload = text.encode("utf-8")
    total_data_codewords = sum(
        EC_TABLE[ecc][version - 1][1] * EC_TABLE[ecc][version - 1][2]
        + EC_TABLE[ecc][version - 1][3] * EC_TABLE[ecc][version - 1][4]
        for _ in (0,)
    )
    total_data_bits = total_data_codewords * 8

    bits: list[int] = []

    def push(value: int, length: int) -> None:
        for shift in range(length - 1, -1, -1):
            bits.append((value >> shift) & 1)

    # Mode indicator: 0100 (byte mode).
    push(0b0100, 4)
    # Character count indicator.
    push(len(payload), _char_count_bits(version))
    # Data.
    for b in payload:
        push(b, 8)
    # Terminator: up to 4 zero bits, but stop early if we hit capacity.
    terminator_len = min(4, total_data_bits - len(bits))
    push(0, terminator_len)
    # Pad to a multiple of 8 bits.
    if len(bits) % 8:
        push(0, 8 - (len(bits) % 8))
    # Fill remaining codewords with alternating pad bytes 0xEC, 0x11.
    pad_bytes = [0xEC, 0x11]
    i = 0
    while len(bits) < total_data_bits:
        push(pad_bytes[i % 2], 8)
        i += 1
    return bits


def _bits_to_codewords(bits: list[int]) -> list[int]:
    """Pack 0/1 bits MSB-first into bytes."""
    assert len(bits) % 8 == 0
    out = []
    for i in range(0, len(bits), 8):
        b = 0
        for j in range(8):
            b = (b << 1) | bits[i + j]
        out.append(b)
    return out


def _interleave_blocks(data_codewords: list[int], version: int, ecc: str) -> list[int]:
    """Split ``data_codewords`` into blocks, RS-encode each, then interleave.

    Returns the final codeword sequence to be placed in the matrix (data
    interleaved, followed by ECC interleaved). See ISO/IEC 18004 §8.6.
    """
    ec_per_block, b1, k1, b2, k2 = EC_TABLE[ecc][version - 1]

    # Split into blocks.
    blocks: list[list[int]] = []
    pos = 0
    for _ in range(b1):
        blocks.append(data_codewords[pos:pos + k1])
        pos += k1
    for _ in range(b2):
        blocks.append(data_codewords[pos:pos + k2])
        pos += k2
    assert pos == len(data_codewords), (pos, len(data_codewords))

    # RS-encode each block.
    ecc_blocks = [_rs_encode(blk, ec_per_block) for blk in blocks]

    # Interleave data: column-by-column.  Group-1 blocks are shorter, so we
    # take the i-th codeword from every block that has one.
    max_data_len = max(len(b) for b in blocks)
    interleaved: list[int] = []
    for i in range(max_data_len):
        for blk in blocks:
            if i < len(blk):
                interleaved.append(blk[i])
    # Interleave ECC: every ECC block is the same length.
    max_ecc_len = max(len(b) for b in ecc_blocks)
    for i in range(max_ecc_len):
        for blk in ecc_blocks:
            if i < len(blk):
                interleaved.append(blk[i])
    return interleaved


# ---------------------------------------------------------------------------
# 4. QR matrix construction.
# ---------------------------------------------------------------------------

# Module values:
#   0 = light (white), 1 = dark (black), None = not yet placed.
# Function-pattern modules are also tagged in a parallel ``reserved`` matrix
# so they don't get masked.

def _new_matrix(size: int) -> list[list[int | None]]:
    return [[None] * size for _ in range(size)]


def _place_finder(mat: list[list[int | None]], reserved: list[list[bool]], r: int, c: int) -> None:
    """Place a 7x7 finder pattern with its top-left corner at (r, c)."""
    pattern = [
        [1, 1, 1, 1, 1, 1, 1],
        [1, 0, 0, 0, 0, 0, 1],
        [1, 0, 1, 1, 1, 0, 1],
        [1, 0, 1, 1, 1, 0, 1],
        [1, 0, 1, 1, 1, 0, 1],
        [1, 0, 0, 0, 0, 0, 1],
        [1, 1, 1, 1, 1, 1, 1],
    ]
    for dr in range(7):
        for dc in range(7):
            mat[r + dr][c + dc] = pattern[dr][dc]
            reserved[r + dr][c + dc] = True


def _place_separators(mat: list[list[int | None]], reserved: list[list[bool]], size: int) -> None:
    """Place 1-module-wide white separators around each finder pattern."""
    # Top-left finder: separator on right column (col 7) and bottom row (row 7).
    for i in range(8):
        # right column of TL
        if i < 8 and 7 < size:
            mat[i][7] = 0
            reserved[i][7] = True
        # bottom row of TL
        if i < 8 and 7 < size:
            mat[7][i] = 0
            reserved[7][i] = True
    # Top-right finder (top-left corner at (0, size-7)): separator on its
    # bottom row (row 7) and left column (col size-8).
    for i in range(8):
        mat[7][size - 1 - i] = 0
        reserved[7][size - 1 - i] = True
        mat[i][size - 8] = 0
        reserved[i][size - 8] = True
    # Bottom-left finder (top-left corner at (size-7, 0)): separator on its
    # top row (row size-8) and right column (col 7).
    for i in range(8):
        mat[size - 8][i] = 0
        reserved[size - 8][i] = True
        mat[size - 1 - i][7] = 0
        reserved[size - 1 - i][7] = True


def _place_timing(mat: list[list[int | None]], reserved: list[list[bool]], size: int) -> None:
    """Timing pattern: row 6 and col 6, alternating dark/light starting at dark."""
    for i in range(8, size - 8):
        bit = 0 if (i % 2) else 1
        if mat[6][i] is None:
            mat[6][i] = bit
            reserved[6][i] = True
        if mat[i][6] is None:
            mat[i][6] = bit
            reserved[i][6] = True


def _place_alignment_patterns(
    mat: list[list[int | None]], reserved: list[list[bool]], version: int, size: int
) -> None:
    """Place 5x5 alignment patterns; skip ones that overlap a finder."""
    centres = ALIGNMENT_PATTERN_LOCATIONS[version]
    pattern = [
        [1, 1, 1, 1, 1],
        [1, 0, 0, 0, 1],
        [1, 0, 1, 0, 1],
        [1, 0, 0, 0, 1],
        [1, 1, 1, 1, 1],
    ]
    for cy in centres:
        for cx in centres:
            # Skip centres that overlap any finder pattern (TL, TR, BL).
            if (cy < 8 and cx < 8) or (cy < 8 and cx > size - 9) or (cy > size - 9 and cx < 8):
                continue
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    mat[cy + dr][cx + dc] = pattern[dr + 2][dc + 2]
                    reserved[cy + dr][cx + dc] = True


def _reserve_format_areas(reserved: list[list[bool]], size: int) -> None:
    """Reserve the modules where format info will be written (filled later)."""
    # Around top-left finder: cols 0..8 of row 8 and rows 0..8 of col 8.
    for i in range(9):
        reserved[8][i] = True
        reserved[i][8] = True
    # Top-right: row 8, cols size-8..size-1.
    for i in range(8):
        reserved[8][size - 1 - i] = True
    # Bottom-left: col 8, rows size-7..size-1.  And the always-dark module
    # at row size-8, col 8.
    for i in range(7):
        reserved[size - 1 - i][8] = True
    reserved[size - 8][8] = True


def _reserve_version_areas(reserved: list[list[bool]], size: int) -> None:
    """Reserve the two version-info regions used for versions >= 7."""
    # 6x3 above bottom-left finder.
    for r in range(6):
        for c in range(size - 11, size - 8):
            reserved[r][c] = True
    # 3x6 left of top-right finder.
    for r in range(size - 11, size - 8):
        for c in range(6):
            reserved[r][c] = True


def _place_format_bits(mat: list[list[int | None]], ecc: str, mask: int, size: int) -> None:
    """Write the 15-bit format string into the two format-info regions."""
    bits = FORMAT_INFO_TABLE[ecc][mask]
    # bits[14] is MSB, bits[0] is LSB; we iterate i = 0..14 from MSB to LSB.
    # Convention: write bit (i) of "string" to a specific module.  We use
    # the standard placement described in §8.9 of ISO/IEC 18004.
    fmt = [(bits >> (14 - i)) & 1 for i in range(15)]

    # Region around top-left finder.
    # Bits 0..5 -> col 8, rows 0..5.
    for i in range(6):
        mat[i][8] = fmt[i]
    # Bit 6 -> col 8, row 7 (skip row 6 which is timing).
    mat[7][8] = fmt[6]
    # Bit 7 -> col 8, row 8.
    mat[8][8] = fmt[7]
    # Bit 8 -> row 8, col 7.
    mat[8][7] = fmt[8]
    # Bits 9..14 -> row 8, cols 5,4,3,2,1,0.
    for i in range(6):
        mat[8][5 - i] = fmt[9 + i]

    # Bottom-left + top-right region.
    # Bits 0..6 -> col 8, rows size-1..size-7 (top to bottom from size-1).
    for i in range(7):
        mat[size - 1 - i][8] = fmt[i]
    # Bits 7..14 -> row 8, cols size-8..size-1.
    for i in range(8):
        mat[8][size - 8 + i] = fmt[7 + i]
    # Always-dark module.
    mat[size - 8][8] = 1


def _place_version_bits(mat: list[list[int | None]], version: int, size: int) -> None:
    """Write the 18-bit version info string (for versions >= 7)."""
    bits = VERSION_INFO_TABLE[version]
    # The 18 bits map row-by-row into a 6x3 region above the bottom-left
    # finder, and a 3x6 region left of the top-right finder.
    for i in range(18):
        bit = (bits >> i) & 1  # bit 0 is LSB
        # Bottom-left region: 3 cols wide, 6 rows tall.
        # i = 3*r + c (c = 0..2, r = 0..5).
        r = i // 3
        c = i % 3
        mat[size - 11 + c][r] = bit
        mat[r][size - 11 + c] = bit


# ---------------------------------------------------------------------------
# 5. Data placement (zigzag from bottom-right).
# ---------------------------------------------------------------------------

def _place_data(
    mat: list[list[int | None]], reserved: list[list[bool]], codewords: list[int], size: int,
    remainder_bits: int,
) -> None:
    """Fill remaining modules with the codeword bit stream in zigzag order."""
    total_bits = len(codewords) * 8 + remainder_bits
    bit_idx = 0

    def next_bit() -> int:
        nonlocal bit_idx
        if bit_idx >= len(codewords) * 8:
            # Remainder bits: 0.
            bit_idx += 1
            return 0
        b = (codewords[bit_idx // 8] >> (7 - (bit_idx % 8))) & 1
        bit_idx += 1
        return b

    col = size - 1
    going_up = True
    while col > 0:
        if col == 6:  # skip the timing column
            col -= 1
        # Two columns at a time: col and col-1.
        rows = range(size - 1, -1, -1) if going_up else range(size)
        for r in rows:
            for dc in (0, 1):
                c = col - dc
                if not reserved[r][c] and mat[r][c] is None:
                    if bit_idx < total_bits:
                        mat[r][c] = next_bit()
                    else:
                        mat[r][c] = 0
        col -= 2
        going_up = not going_up


# ---------------------------------------------------------------------------
# 6. Mask patterns + penalty scoring.
# ---------------------------------------------------------------------------

def _mask_fn(mask: int):
    """Return f(row, col) -> bool (True = invert) for the given mask 0..7."""
    if mask == 0:
        return lambda r, c: (r + c) % 2 == 0
    if mask == 1:
        return lambda r, c: r % 2 == 0
    if mask == 2:
        return lambda r, c: c % 3 == 0
    if mask == 3:
        return lambda r, c: (r + c) % 3 == 0
    if mask == 4:
        return lambda r, c: (r // 2 + c // 3) % 2 == 0
    if mask == 5:
        return lambda r, c: (r * c) % 2 + (r * c) % 3 == 0
    if mask == 6:
        return lambda r, c: ((r * c) % 2 + (r * c) % 3) % 2 == 0
    if mask == 7:
        return lambda r, c: ((r + c) % 2 + (r * c) % 3) % 2 == 0
    raise ValueError(mask)


def _apply_mask(
    mat: list[list[int | None]], reserved: list[list[bool]], mask: int, size: int,
) -> list[list[int]]:
    """Return a copy of ``mat`` with the mask XORed into all non-reserved modules."""
    fn = _mask_fn(mask)
    out = [[mat[r][c] for c in range(size)] for r in range(size)]
    for r in range(size):
        for c in range(size):
            if not reserved[r][c]:
                if fn(r, c):
                    out[r][c] ^= 1
    return out


def _penalty(mat: list[list[int]], size: int) -> int:
    """Compute the standard QR mask penalty (smaller = better)."""
    p1 = p2 = p3 = p4 = 0

    # N1: runs of >= 5 same-color modules per row + per column.
    for r in range(size):
        run_color = mat[r][0]
        run_len = 1
        for c in range(1, size):
            if mat[r][c] == run_color:
                run_len += 1
            else:
                if run_len >= 5:
                    p1 += 3 + (run_len - 5)
                run_color = mat[r][c]
                run_len = 1
        if run_len >= 5:
            p1 += 3 + (run_len - 5)
    for c in range(size):
        run_color = mat[0][c]
        run_len = 1
        for r in range(1, size):
            if mat[r][c] == run_color:
                run_len += 1
            else:
                if run_len >= 5:
                    p1 += 3 + (run_len - 5)
                run_color = mat[r][c]
                run_len = 1
        if run_len >= 5:
            p1 += 3 + (run_len - 5)

    # N2: 2x2 blocks of same color.
    for r in range(size - 1):
        for c in range(size - 1):
            v = mat[r][c]
            if mat[r][c + 1] == v and mat[r + 1][c] == v and mat[r + 1][c + 1] == v:
                p2 += 3

    # N3: finder-like patterns of 1011101 with 4 light modules adjacent.
    patt_a = [1, 0, 1, 1, 1, 0, 1, 0, 0, 0, 0]
    patt_b = [0, 0, 0, 0, 1, 0, 1, 1, 1, 0, 1]
    for r in range(size):
        for c in range(size - 10):
            seg = [mat[r][c + i] for i in range(11)]
            if seg == patt_a or seg == patt_b:
                p3 += 40
    for c in range(size):
        for r in range(size - 10):
            seg = [mat[r + i][c] for i in range(11)]
            if seg == patt_a or seg == patt_b:
                p3 += 40

    # N4: dark-module proportion deviation from 50%.
    total = size * size
    dark = sum(sum(row) for row in mat)
    pct = (dark * 100) // total
    # Closer to 50% = lower penalty.  10 * |k|, where k = floor(|pct-50|/5).
    p4 = 10 * (abs(pct - 50) // 5)

    return p1 + p2 + p3 + p4


# ---------------------------------------------------------------------------
# 7. Top-level QR construction.
# ---------------------------------------------------------------------------

def _build_qr_matrix(text: str, ecc: str) -> list[list[int]]:
    """Return the final size x size dark/light matrix for ``text``."""
    if ecc not in ("L", "M", "Q", "H"):
        raise ValueError(f"ecc_level must be L/M/Q/H, got {ecc!r}")
    payload = text.encode("utf-8")
    # First-pass version: assume header is short.
    version = _select_version(len(payload), ecc)
    # If the chosen version's character-count is 16-bit but it just barely
    # fits at 8-bit width, _select_version is still correct because
    # BYTE_CAPACITY already encodes the right header size per version.
    # (BYTE_CAPACITY tracks data-payload bytes, not raw bits, so no further
    # adjustment is needed.)

    size = 17 + 4 * version

    bits = _encode_byte_segment(text, version, ecc)
    data_codewords = _bits_to_codewords(bits)
    final_codewords = _interleave_blocks(data_codewords, version, ecc)

    mat: list[list[int | None]] = _new_matrix(size)
    reserved: list[list[bool]] = [[False] * size for _ in range(size)]

    # Function patterns.
    _place_finder(mat, reserved, 0, 0)
    _place_finder(mat, reserved, 0, size - 7)
    _place_finder(mat, reserved, size - 7, 0)
    _place_separators(mat, reserved, size)
    _place_alignment_patterns(mat, reserved, version, size)
    _place_timing(mat, reserved, size)

    _reserve_format_areas(reserved, size)
    if version >= 7:
        _reserve_version_areas(reserved, size)

    # Always-dark module (already covered by reserve, but ensure value).
    mat[size - 8][8] = 1

    # Place data + ECC codewords.
    _place_data(mat, reserved, final_codewords, size, REMAINDER_BITS[version - 1])

    # Replace any None left (shouldn't happen, but be safe) with 0.
    for r in range(size):
        for c in range(size):
            if mat[r][c] is None:
                mat[r][c] = 0

    # Evaluate all 8 masks, pick the one with lowest penalty.
    best_mask = 0
    best_penalty = None
    best_masked = None
    for m in range(8):
        masked = _apply_mask(mat, reserved, m, size)
        # Format bits + version bits MUST be written into the masked matrix
        # (they're not affected by the mask themselves).
        _place_format_bits(masked, ecc, m, size)
        if version >= 7:
            _place_version_bits(masked, version, size)
        pen = _penalty(masked, size)
        if best_penalty is None or pen < best_penalty:
            best_penalty = pen
            best_mask = m
            best_masked = masked

    assert best_masked is not None
    return best_masked


# ---------------------------------------------------------------------------
# 8. PNG writer (stdlib zlib).
# ---------------------------------------------------------------------------

def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    """Build a single PNG chunk: length, type, data, CRC32(type+data)."""
    length = struct.pack(">I", len(data))
    crc = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
    return length + chunk_type + data + struct.pack(">I", crc)


def _matrix_to_png(matrix: list[list[int]], module_pixel_size: int, quiet_zone: int = 4) -> bytes:
    """Convert a dark/light matrix into an 8-bit grayscale PNG byte string.

    We use 8-bit grayscale (bit-depth 8, color-type 0) so the format is the
    simplest possible (1 byte per pixel) — this keeps the IDAT scanline
    construction trivial while staying well within stdlib zlib's reach.
    """
    n = len(matrix)
    # Final image is (n + 2*quiet_zone) modules square, each module
    # ``module_pixel_size`` pixels.
    modules_per_side = n + 2 * quiet_zone
    width = height = modules_per_side * module_pixel_size

    # Build raw scanlines: each row prefixed with filter byte 0x00.
    # 0 = light = 0xFF, 1 = dark = 0x00.
    # Pre-compute one full module-row (in pixel-bytes) so we don't recompute
    # per pixel row.
    light = 0xFF
    dark = 0x00

    raw = bytearray()
    # quiet-zone rows above
    quiet_row = bytearray([0]) + bytearray([light] * width)
    # The next loop writes one *pixel* row.  To avoid per-pixel-per-row
    # cost, we build each module-row as bytes once and repeat it
    # module_pixel_size times.
    for _ in range(quiet_zone * module_pixel_size):
        raw.extend(quiet_row)

    for r in range(n):
        # Build the module-row's pixel bytes once.
        pixel_row = bytearray()
        # Quiet-zone left
        pixel_row.extend(bytes([light]) * (quiet_zone * module_pixel_size))
        for c in range(n):
            color = dark if matrix[r][c] else light
            pixel_row.extend(bytes([color]) * module_pixel_size)
        # Quiet-zone right
        pixel_row.extend(bytes([light]) * (quiet_zone * module_pixel_size))
        # Prefix with filter byte (0 = none).
        full_row = bytearray([0]) + pixel_row
        for _ in range(module_pixel_size):
            raw.extend(full_row)

    # quiet-zone rows below
    for _ in range(quiet_zone * module_pixel_size):
        raw.extend(quiet_row)

    compressed = zlib.compress(bytes(raw), 9)

    # Assemble PNG.
    out = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    #   width, height, bit-depth=8, color-type=0 (grayscale),
    #   compression=0 (deflate), filter=0, interlace=0.
    out += _png_chunk(b"IHDR", ihdr)
    out += _png_chunk(b"IDAT", compressed)
    out += _png_chunk(b"IEND", b"")
    return out


# ---------------------------------------------------------------------------
# 9. Public API.
# ---------------------------------------------------------------------------

def qr_png(text: str, *, module_pixel_size: int = 8, ecc_level: str = "M") -> bytes:
    """Encode ``text`` as a QR code and return a scannable PNG (bytes).

    Parameters
    ----------
    text:
        UTF-8 text to encode (mode-8 byte segment).
    module_pixel_size:
        Side length, in pixels, of each QR module (default 8).
    ecc_level:
        Error-correction level: "L", "M" (default), "Q", or "H".

    Returns
    -------
    bytes
        Complete PNG image (signature + IHDR + IDAT + IEND, each chunk's CRC
        valid).
    """
    if not isinstance(text, str):
        raise TypeError("text must be a str")
    if module_pixel_size < 1:
        raise ValueError("module_pixel_size must be >= 1")
    ecc = ecc_level.upper()
    if ecc not in ("L", "M", "Q", "H"):
        raise ValueError(f"ecc_level must be L/M/Q/H (got {ecc_level!r})")
    matrix = _build_qr_matrix(text, ecc)
    return _matrix_to_png(matrix, module_pixel_size)
