import hashlib
import os
import struct
from pathlib import Path

import pytest

from gbox import mayhem_ntl as N

SRC_SHA = "f89bb1e5b450b2aa88464367c320a9d57f308f0899c391e8f50ba765b9bcfaa5"


def _synthetic():
    # 1 part, 4x4 CI4 texture
    nparts, magic = 1, N.MAGIC
    name = b"GXsides\0".ljust(16, b"\xcd")
    w, h = 4, 4
    pal = struct.pack(">16H", *([0xFFFF] + [0x0001] * 15))  # white + 15 black-ish
    tail = b"\x01\x02\x03\x04"
    data_offset = N.HEADER_SIZE + N.PART_STRIDE
    idx = bytes([0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88])  # 16 texels / 2
    part = name + struct.pack(">HHIII", w, h, data_offset, 0, 0x04CD00FF)
    return struct.pack(">HH", nparts, magic) + part + pal + tail + idx


def test_synthetic_roundtrip():
    d = _synthetic()
    m = N.parse(d)
    assert m["nparts"] == 1 and m["magic"] == N.MAGIC
    p = m["parts"][0]
    assert (p["width"], p["height"]) == (4, 4)
    assert p["tex_flags"] == 0x04CD00FF
    assert p["name"] == "GXsides"
    pal = N.palette(d, p)
    assert pal[0] == (255, 255, 255, 255)
    # CI4 index byte 0x11 -> texel 0 and 1 both palette[1]
    out = N.decode(d, p)
    assert out[0:8] == bytes(pal[1]) * 2
    png = N.to_png(d, p)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_bad_magic():
    with pytest.raises(ValueError):
        N.parse(b"\0" * 64)


def test_owned_rom_all_textures():
    p = os.environ.get("GBOX_MAYHEM_EU_SOURCE") or str(Path.home() / "gbox-cache" / "9cb579d94b6d2167" / "source.zip")
    p = Path(p)
    if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() != SRC_SHA:
        pytest.skip("owned WCW Mayhem (Europe) zip not cached")
    from gbox import mayhem_inventory as M, n64_rom
    rom = n64_rom.read(p)
    rows = M.walk(rom)
    n = main = 0
    for r in rows:
        if r["ext"] != "ntl":
            continue
        b = M.member(rom, rows, r["name"], r["archive"])
        m = N.parse(b)
        n += 1
        if m["magic"] == N.MAGIC:
            main += 1
        for part in m["parts"]:
            assert part["data_offset"] >= N.HEADER_SIZE + m["nparts"] * N.PART_STRIDE, r["name"]
            need = part["width"] * part["height"] // 2 + N.TEXTURE_PREFIX
            assert part["data_offset"] + need <= len(b), (r["name"], part["name"])
            png = N.to_png(b, part)
            assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert n == 955 and main == 954  # 954 mainstream 0x294E + 1 test.ntl variant (0x2A4E)
    # spot-check a wrestler texture with known part names/dims
    go = N.parse(M.member(rom, rows, "GO_n64.ntl"))
    assert go["nparts"] == 8
    assert [q["name"] for q in go["parts"]] == ["GOheadN", "GOarmbn", "GOlegfn", "GOlegrn",
                                                "gottarmN", "GOarmtn", "GObootN", "GOchestN"]
    assert (go["parts"][0]["width"], go["parts"][0]["height"]) == (64, 64)
    assert (go["parts"][1]["width"], go["parts"][1]["height"]) == (32, 85)
