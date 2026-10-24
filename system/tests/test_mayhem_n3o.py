import hashlib
import os
import struct
from pathlib import Path

import pytest

from gbox import mayhem_n3o as N

SRC_SHA = "f89bb1e5b450b2aa88464367c320a9d57f308f0899c391e8f50ba765b9bcfaa5"


def _synthetic():
    # 1 part, 3 vertices, one TRI1 display list
    vtx = struct.pack(">hhhHhhBBBB", 0, 0, 0, 0, 0, 0, 1, 2, 3, 4) + struct.pack(">hhhHhhBBBB", 10, 0, 0, 0, 0, 0, 1, 2, 3, 4) \
        + struct.pack(">hhhHhhBBBB", 0, 10, 0, 0, 0, 0, 1, 2, 3, 4)
    dl = struct.pack(">II", 0x01003006, 0x02000000) + struct.pack(">II", 0x05000204, 0) \
        + struct.pack(">II", 0xDF000000, 0)
    hdr = struct.pack(">HH7I", N.MAGIC, 1, 0, 0, 0x48, 3, 0, 0x48 + 48 + len(dl), 0)
    part = b"p1".ljust(8, b"\0") + struct.pack(">7I", 0, 0x13, 0, 0x48 + 48, 0, len(dl), 0)
    return hdr + part + b"\0\0\0\0" + vtx + dl


def test_synthetic_roundtrip():
    d = _synthetic()
    m = N.parse(d)
    assert m["nparts"] == 1 and m["vtx_count"] == 3 and N.contiguous(m)
    assert len(N.vertices(d, m)) == 3
    assert N.triangles(d, m["parts"][0], m)[0] == (0, 1, 2)
    assert "f 1 2 3" in N.to_obj(d)


def test_bad_magic():
    with pytest.raises(ValueError):
        N.parse(b"\0" * 64)


def test_owned_rom_all_models():
    p = os.environ.get("GBOX_MAYHEM_EU_SOURCE") or str(Path.home() / "gbox-cache" / "9cb579d94b6d2167" / "source.zip")
    p = Path(p)
    if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() != SRC_SHA:
        pytest.skip("owned WCW Mayhem (Europe) zip not cached")
    from gbox import mayhem_inventory as M, n64_rom
    rom = n64_rom.read(p)
    rows = M.walk(rom)
    n = tris = 0
    for r in rows:
        if r["ext"] != "n3o":
            continue
        b = M.member(rom, rows, r["name"], r["archive"])
        m = N.parse(b)
        n += 1
        assert N.contiguous(m), r["name"]
        for part in m["parts"]:
            for t in N.triangles(b, part, m):
                tris += 1
                assert None not in t and max(t) < m["vtx_count"]
    assert n == 176 and tris == 63265
    st = N.parse(M.member(rom, rows, "ST_n64.n3o"))
    assert [q["name"] for q in st["parts"]][:3] == ["STbarmn", "STbootsn", "STchestn"] and st["vtx_count"] == 0x348
