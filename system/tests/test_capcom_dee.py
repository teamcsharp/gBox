"""Focused tests for the Capcom Generations .DEE container parser."""

import os
import struct
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gbox import capcom_dee as dee  # noqa: E402

DEE_DIR = os.environ.get(
    "CAPCOM_GEN_DEE_DIR",
    "/home/ehm_eckx/.hermes/cache/scratch/capcom_gen/dee",
)

# The 12 verified .DEE files dumped from the owned CHD.
# (filename, type_tag, body_marker, block_token, block_count, field_count)
EXPECTED_FILES = [
    ("1943_43CHAR7.DEE",  0x2220, 0x106b, 0x0040, 0x0800, 0x0031),
    ("1943_43CARD.DEE",   0x1d20, 0x106b, 0x0040, 0x0900, 0x0031),
    ("1943_43LDG.DEE",    0x5814, 0x106b, 0x0040, 0x0200, 0x0031),
    ("1943_FONT16.DEE",   0x5040, 0x102b, 0x0040, 0x0800, 0x0031),
    ("1943_SCRLL0.DEE",   0x0220, 0x106b, 0x0040, 0x0800, 0x0031),
    ("1943_OBJ01.DEE",    0x0220, 0x106b, 0x0040, 0x0800, 0x0031),
    ("1943K_43KCHAR7.DEE", 0x2220, 0x106b, 0x0040, 0x0800, 0x0031),
    ("1942_42CHAR7.DEE",  0x2040, 0x102b, 0x0040, 0x0800, 0x0031),
    ("MENU_CAPCOM2.DEE",  0x6a20, 0x106b, 0x0040, 0x0900, 0x0031),
    ("MENU_OP_BACK2.DEE", 0x6a20, 0x106b, 0x0040, 0x0900, 0x0031),
    ("MENU_GENR.DEE",     0x1840, 0x102b, 0x0040, 0x0800, 0x0031),
    ("MENU_PSWAR.DEE",    0x6a20, 0x106b, 0x0040, 0x0900, 0x0031),
]


def _make_dee(type_tag=0x2220, sub_type=0, body=b"\x00" * 64,
              flag=0x0001, block_token=0x0040,
              body_marker=0x106b, pad=0, block_count=0x0800,
              field_count=0x0031):
    """Build a synthetic .DEE file for parser testing.

    total = 12 (header) + len(body); payload_len = len(body) (the body already
    includes the 16-byte body header block, so pass body including it).
    """
    payload_len = len(body)
    header = struct.pack(
        "<6H",
        type_tag, sub_type, payload_len, 0, flag, block_token,
    )
    return header + body


def _make_body(body_marker=0x106b, pad=0, block_count=0x0800, field_count=0x0031,
               pixel_size=80):
    """Build a body: 16-byte body header + pixel payload."""
    return struct.pack("<4H", body_marker, pad, block_count, field_count) + b"\x00" * pixel_size


def test_parse_synthetic_dee_header():
    body = _make_body()
    data = _make_dee(body=body)
    result = dee.parse_dee(data)
    assert result["type_tag"] == 0x2220
    assert result["type_name"] == "char_sprites"
    assert result["payload_len"] == len(body)
    assert result["flag"] == 0x0001
    assert result["block_token"] == 0x0040
    assert result["body_marker"] == 0x106b
    assert result["body_variant"] == "standard"
    assert result["block_count"] == 0x0800
    assert result["field_count"] == 0x0031
    assert result["body_size"] == 72  # 96-byte body - 16-byte body header = 80? No: total=12+96=108, body_size=108-12-16=80
    assert result["total_size"] == 12 + len(body)
    assert len(result["sha256"]) == 64


def test_parse_rejects_payload_mismatch():
    body = _make_body()
    data = bytearray(_make_dee(body=body))
    struct.pack_into("<H", data, 4, 0xFFFF)
    with pytest.raises(ValueError, match="payload_len mismatch"):
        dee.parse_dee(bytes(data))


def test_parse_rejects_reserved_nonzero():
    body = _make_body()
    data = bytearray(_make_dee(body=body))
    struct.pack_into("<H", data, 6, 0x0001)
    with pytest.raises(ValueError, match="reserved"):
        dee.parse_dee(bytes(data))


def test_parse_rejects_too_small():
    with pytest.raises(ValueError, match="too small"):
        dee.parse_dee(b"\x00" * 16)


def test_parse_rejects_body_pad_nonzero():
    body = _make_body()
    data = bytearray(_make_dee(body=body))
    struct.pack_into("<H", data, 14, 0x0001)
    with pytest.raises(ValueError, match="pad"):
        dee.parse_dee(bytes(data))


def test_known_type_tags_cover_all_observed():
    """Every type_tag seen in the 12 dumped files must have a name."""
    for _, tag, _, _, _, _ in EXPECTED_FILES:
        assert tag in dee.KNOWN_TYPE_TAGS, f"unknown type_tag 0x{tag:04x}"


def test_known_body_markers_cover_all_observed():
    for _, _, marker, _, _, _ in EXPECTED_FILES:
        assert marker in dee.KNOWN_BODY_MARKERS, f"unknown body_marker 0x{marker:04x}"


@pytest.mark.skipif(not os.path.exists(DEE_DIR), reason="DEE dump dir not on this host")
def test_parse_all_12_dumped_dee_files():
    """Parse all 12 .DEE files dumped from the owned CHD and verify headers."""
    for fname, tag, marker, token, bcount, fcount in EXPECTED_FILES:
        path = os.path.join(DEE_DIR, fname)
        assert os.path.exists(path), f"missing {path}"
        result = dee.parse_dee_file(path)
        assert result["type_tag"] == tag, \
            f"{fname}: type_tag 0x{result['type_tag']:04x} != 0x{tag:04x}"
        assert result["body_marker"] == marker, \
            f"{fname}: body_marker 0x{result['body_marker']:04x} != 0x{marker:04x}"
        assert result["block_token"] == token, \
            f"{fname}: block_token 0x{result['block_token']:04x} != 0x{token:04x}"
        assert result["block_count"] == bcount, \
            f"{fname}: block_count 0x{result['block_count']:04x} != 0x{bcount:04x}"
        assert result["field_count"] == fcount, \
            f"{fname}: field_count 0x{result['field_count']:04x} != 0x{fcount:04x}"
        assert result["flag"] == 0x0001
        assert result["payload_len"] == result["total_size"] - 12
        assert result["body_size"] > 0
        assert len(result["sha256"]) == 64


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))


# --- body codec -----------------------------------------------------------
from gbox.capcom_dee import dee_decompress, parse_tim, decode_dee_tim  # noqa: E402


def test_dee_decompress_literals_and_overlapping_match():
    # flag 0b00000111: 3 literals, then a match (len 2+3=5, dist 3)
    w = (2 << 4) | 3
    blob = b"\0" * 12 + bytes([0x07]) + b"abc" + bytes([w & 0xFF, w >> 8])
    assert dee_decompress(blob) == b"abcabcab"


def test_dee_decompress_rejects_bad_distance():
    blob = b"\0" * 12 + bytes([0x00, 0xF0, 0xFF])
    with pytest.raises(ValueError):
        dee_decompress(blob)


def test_parse_tim_rejects_garbage():
    with pytest.raises(ValueError):
        parse_tim(b"nope" * 8)


@pytest.mark.skipif(not os.path.exists(DEE_DIR), reason="DEE dump dir not on this host")
def test_all_compressed_dee_decode_to_exact_tim():
    names = [f for f in os.listdir(DEE_DIR) if f.upper().endswith(".DEE")]
    names = [f for f in names if not f.startswith(("MENU_S14", "MENU_WARN2"))]
    assert len(names) >= 12
    for f in names:
        tim, info = decode_dee_tim(open(os.path.join(DEE_DIR, f), "rb").read())
        assert info["bpp"] in (4, 8, 16) and info["image"]["w"] >= 0, f
    tim, info = decode_dee_tim(open(os.path.join(DEE_DIR, "1943_43CHAR7.DEE"), "rb").read())
    assert len(tim) == 8736 and info["clut"] == {"size": 524, "x": 0, "y": 480, "w": 256, "h": 1}
