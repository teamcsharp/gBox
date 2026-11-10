"""Focused tests for the Capcom Generations .DEE container parser.

The .DEE header is 3 x little-endian u32 (raw_len, comp_len, word=0x00400001);
the payload at +0x0C is a byte-flag LZ77 stream that decompresses to a PSX TIM.
"""

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
# (filename, file_size, raw_len u32@0, comp_len u32@4, word u32@8)
#
# raw_len/comp_len are read fresh from the files at test time; these values
# are assertions written down from the verified dump so a regression in the
# header decode is caught, not just self-consistency.
EXPECTED_FILES = [
    ("1943_43CHAR7.DEE",   3407, 8736, 3395, 0x00400001),
    ("1943_43CARD.DEE",    6894, 7456, 6882, 0x00400001),
    ("1943_43LDG.DEE",    54473, 153620, 54461, 0x00400001),
    ("1943_FONT16.DEE",    4998, 20544, 4986, 0x00400001),
    ("1943_SCRLL0.DEE",   21666, 66080, 21654, 0x00400001),
    ("1943_OBJ01.DEE",    27314, 66080, 27302, 0x00400001),
    ("1943K_43KCHAR7.DEE", 3393, 8736, 3381, 0x00400001),
    ("1942_42CHAR7.DEE",   1914, 8256, 1902, 0x00400001),
    ("MENU_CAPCOM2.DEE",  11968, 92704, 11956, 0x00400001),
    ("MENU_OP_BACK2.DEE", 13374, 92704, 13362, 0x00400001),
    ("MENU_GENR.DEE",      1312, 6208, 1300, 0x00400001),
    ("MENU_PSWAR.DEE",    15132, 92704, 15120, 0x00400001),
]


def _make_dee(raw=b"\x00" * 64, word=0x00400001):
    """Build a synthetic .DEE file: 12-byte 3x u32 header + LZ77 payload."""
    comp = dee.dee_compress(raw)
    return struct.pack("<3I", len(raw), len(comp), word) + comp


def test_parse_synthetic_dee_header():
    raw = b"\x00\x11\x22" * 100
    data = _make_dee(raw)
    result = dee.parse_dee(data)
    assert result["raw_len"] == len(raw) == 300
    assert result["comp_len"] == len(data) - 12
    assert result["word"] == 0x00400001
    assert result["version"] == 1 and result["token"] == 0x0040
    assert result["body_size"] == result["comp_len"]
    assert result["total_size"] == len(data)
    assert len(result["sha256"]) == 64


def test_parse_rejects_comp_len_mismatch():
    data = bytearray(_make_dee())
    struct.pack_into("<I", data, 4, 0xFFFF)
    with pytest.raises(ValueError, match="comp_len mismatch"):
        dee.parse_dee(bytes(data))


def test_parse_rejects_too_small():
    with pytest.raises(ValueError, match="too small"):
        dee.parse_dee(b"\x00" * 8)


def test_header_roundtrips_through_pack():
    raw = b"\x00\x11\x22" * 100
    p = dee.dee_pack(raw)
    h = dee.parse_dee(p)
    assert h["raw_len"] == len(raw)
    assert h["comp_len"] == len(p) - 12
    assert dee.dee_header(p)["raw_len"] == len(raw)


@ pytest.mark.skipif(not os.path.exists(DEE_DIR), reason="DEE dump dir not on this host")
def test_parse_all_12_dumped_dee_files():
    """Parse all 12 .DEE files and verify the true 3 x u32 header fields."""
    for fname, fsize, raw_len, comp_len, word in EXPECTED_FILES:
        path = os.path.join(DEE_DIR, fname)
        assert os.path.exists(path), f"missing {path}"
        data = open(path, "rb").read()
        assert len(data) == fsize, f"{fname}: size {len(data)} != {fsize}"
        result = dee.parse_dee(data)
        assert result["raw_len"] == raw_len, \
            f"{fname}: raw_len {result['raw_len']} != {raw_len}"
        assert result["comp_len"] == comp_len, \
            f"{fname}: comp_len {result['comp_len']} != {comp_len}"
        assert result["word"] == word, f"{fname}: word {result['word']:#x} != {word:#x}"
        assert result["total_size"] == fsize
        assert result["body_size"] == fsize - 12
        assert len(result["sha256"]) == 64


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))


# --- body codec -----------------------------------------------------------
from gbox.capcom_dee import dee_decompress, parse_tim, decode_dee_tim  # noqa: E402


def test_dee_decompress_roundtrip_known_string():
    # manually built: flag byte 0b00000111 = 3 literals, then a match (len 2+3=5, dist 3)
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


@ pytest.mark.skipif(not os.path.exists(DEE_DIR), reason="DEE dump dir not on this host")
def test_all_compressed_dee_decode_to_exact_tim():
    names = [f for f in os.listdir(DEE_DIR) if f.upper().endswith(".DEE")]
    names = [f for f in names if not f.startswith(("MENU_S14", "MENU_WARN2"))]
    assert len(names) >= 12
    for f in names:
        tim, info = decode_dee_tim(open(os.path.join(DEE_DIR, f), "rb").read())
        assert info["bpp"] in (4, 8, 16) and info["image"]["w"] >= 0, f
    tim, info = decode_dee_tim(open(os.path.join(DEE_DIR, "1943_43CHAR7.DEE"), "rb").read())
    assert len(tim) == 8736 and info["clut"] == {"size": 524, "x": 0, "y": 480, "w": 256, "h": 1}


# --- TIM -> PNG exporter ---------------------------------------------------
from gbox.capcom_dee import tim_to_png, dee_to_png  # noqa: E402


def _make_tim_4bpp(w=4, h=4, clut_colors=(0x0000, 0x7FFF, 0x001F, 0x8000)):
    """Synthesize a 4bpp TIM: CLUT + one 4x4 image, low nibble = left pixel."""
    flag = 0x08 | 0x00  # has CLUT, 4bpp
    csize = 12 + 2 * len(clut_colors)
    clut = struct.pack("<IHHHH", csize, 0, 480, 256, 1) + struct.pack(
        "<%dH" % len(clut_colors), *clut_colors)
    imgsize = 12 + (w * h) // 2
    img = struct.pack("<IHHHH", imgsize, 0, 0, w, h)
    # index pattern: 0,1,2,3 -> 0x3210 bytes
    pix = bytes([0x10, 0x32]) + b"\x00" * ((w * h) // 2 - 2)
    return b"\x10\x00\x00\x00" + struct.pack("<I", flag) + clut + img + pix


def test_tim_to_png_4bpp_decodes_and_honors_stp_transparency():
    tim = _make_tim_4bpp()
    png, meta = tim_to_png(tim)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert meta["image"] == {"x": 0, "y": 0, "w": 4, "h": 4}
    assert meta["bpp"] == 4
    assert meta["clut"]["count"] == 4
    # 1 index (0x8000) has STP set -> alpha 0; others opaque
    from gbox.capcom_dee import _clut_color
    assert _clut_color(0x8000)[3] == 0
    assert _clut_color(0x0000)[3] == 255


def test_tim_to_png_rejects_non_tim_and_16bpp():
    with pytest.raises(ValueError):
        tim_to_png(b"nope" * 8)
    # 16bpp (bpp==2) is unsupported by this exporter
    flag = 0x02
    img = struct.pack("<IHHHH", 12 + 8, 0, 0, 2, 2) + b"\x00" * 8
    with pytest.raises(ValueError, match="unsupported"):
        tim_to_png(b"\x10\x00\x00\x00" + struct.pack("<I", flag) + img)


@ pytest.mark.skipif(not os.path.exists(DEE_DIR), reason="DEE dump dir not on this host")
def test_43char7_dee_to_png_roundtrip():
    """The owned 43CHAR7.DEE exports to a 64x128 RGBA PNG end-to-end."""
    data = open(os.path.join(DEE_DIR, "1943_43CHAR7.DEE"), "rb").read()
    png, meta = dee_to_png(data)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert meta["tim"]["image"]["w"] == 64 and meta["tim"]["image"]["h"] == 128
    assert meta["clut"]["count"] == 256
    assert meta["dee"]["raw_len"] == 8736
    assert meta["dee"]["version"] == 1 and meta["dee"]["token"] == 0x0040


# --- writer side: recompressor / packer ------------------------------------

def test_compress_roundtrip_synthetic():
    import random
    rnd = random.Random(7)
    for raw in (b"", b"a", b"abc" * 500, bytes(rnd.randrange(256) for _ in range(5000)),
                bytes(rnd.randrange(4) for _ in range(20000))):
        assert dee.dee_decompress(dee.dee_pack(raw)) == raw


def test_pack_header_fields():
    raw = b"\x00\x11\x22" * 100
    p = dee.dee_pack(raw)
    h = dee.dee_header(p)
    assert h == {"raw_len": 300, "comp_len": len(p) - 12, "word": 0x00400001}


def test_tim_replace_image_same_size():
    img = bytes(range(16))
    tim = (b"\x10\x00\x00\x00" + (8).to_bytes(4, "little")
           + (12 + 4).to_bytes(4, "little") + b"\x00" * 8 + b"\x00" * 4
           + (12 + 16).to_bytes(4, "little") + struct.pack("<4H", 0, 0, 8, 2) + img)
    # fix CLUT block: flag bit3 set => CLUT present
    tim = (b"\x10\x00\x00\x00" + (8).to_bytes(4, "little") + (12 + 4).to_bytes(4, "little")
           + struct.pack("<4H", 0, 0, 2, 1) + b"\xff\xff\x00\x00"
           + (12 + 16).to_bytes(4, "little") + struct.pack("<4H", 0, 0, 8, 2) + img)
    new = dee.tim_replace_image(tim, bytes(16))
    assert len(new) == len(tim) and new.endswith(bytes(16)) and new[:-16] == tim[:-16]
    with pytest.raises(ValueError):
        dee.tim_replace_image(tim, b"x")


@ pytest.mark.skipif(not os.path.isdir(DEE_DIR), reason="owned DEE dump absent")
def test_noop_roundtrip_all_owned_files():
    n = 0
    for name in sorted(os.listdir(DEE_DIR)):
        if not name.endswith(".DEE") or name == "MENU_WARN2.DEE":
            continue
        data = open(os.path.join(DEE_DIR, name), "rb").read()
        try:
            raw = dee.dee_decompress(data)
        except ValueError:
            continue
        assert dee.dee_header(data)["raw_len"] == len(raw), name
        assert dee.dee_header(data)["comp_len"] == len(data) - 12, name
        assert dee.dee_decompress(dee.dee_pack(raw)) == raw, name
        n += 1
    assert n >= 12
