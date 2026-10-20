"""NFL Blitz 2001 (USA) DC inventory: SBM/MDL/GENSEQ parsers on synthetic data plus the real disc."""
import os
import struct
from pathlib import Path

import pytest

from gbox import blitz2001_inventory as B

GDI = Path(os.environ.get("GBOX_BLITZ2001_GDI", Path.home() / "gBox_alt/gbox-cache/dc/b0d6166c71562f78/disc.gdi"))


def _sbm(nv=4, bones=((0, 2), (1, 2))):
    strips = [(0xE000, 0), (0xE000, 16), (0xF000, 32)]
    soff = 0x40 + 16 * nv
    boff = soff + 16 * len(strips) if bones else 0
    h = [1 if bones else 0, nv, len(strips), 1, 0x40, soff, 0, 0, 0, 0, boff, 0, 0, 0, 0, 0]
    d = bytearray(struct.pack("<16I", *h))
    for i in range(nv):
        d += struct.pack("<4f", i, 0, 0, 1.0)
    for pcw, vi in strips:
        d += struct.pack("<HHIff", pcw, vi, 0xFFFFFFFF, 0.0, 0.0)
    if bones:
        first = 0
        for k, (b, n) in enumerate(bones):
            flag = 0x80000000 if k == len(bones) - 1 else 0
            d += struct.pack("<4I", b | flag, n, 16 * len(bones) + 2 * first, 0)
            first += n
        d += struct.pack(f"<{nv}H", *range(nv))
    return bytes(d)


def test_sbm_skinned_and_rigid():
    r = B.sbm(_sbm())
    assert r["verts"] == 4 and r["strips"] == 1 and r["strip_vertices"] == 3
    assert [(b["bone"], b["count"], b["first"]) for b in r["bones"]] == [(0, 2, 0), (1, 2, 2)]
    assert B.sbm(_sbm(bones=()))["bones"] is None


def test_sbm_rejects_bad_tables():
    with pytest.raises(ValueError):
        B.sbm(_sbm(bones=((0, 3), (1, 2))))           # runs exceed the vertex count / overlap
    bad = bytearray(_sbm())
    struct.pack_into("<HH", bad, 0x40 + 16 * 4, 0xE000, 16 * 9)  # vertex index past n_verts
    with pytest.raises(ValueError):
        B.sbm(bytes(bad))


def test_genseq_packed_raw_and_tail_pad():
    n = 3
    offs, body = [], b""
    first = 16 * n
    for frames, packed in ((2, True), (3, False), (1, True)):
        offs.append((frames, first + len(body)))
        body += bytes(B.ANI_PACKED_HEAD + B.ANI_PACKED_FRAME * frames if packed else B.ANI_RAW_FRAME * frames)
    body += bytes(4)                                   # tail pad on the last sequence
    tab = b""
    for i, (frames, off) in enumerate(offs):
        tab += struct.pack("<4I", B.ANI_TAG if i == 0 else 1, frames, 15, off)
    r = B.genseq(tab + body)
    assert (r["sequences"], r["packed"], r["raw"], r["frames"]) == (3, 2, 1, 6)
    with pytest.raises(ValueError):
        B.genseq(tab + body[:-40])


def test_file_room_uses_next_lba():
    room = B.file_room({"A": (100, 10), "B": (103, 5000), "C": (110, 1)})
    assert room == {"A": 3 * 2048, "B": 7 * 2048, "C": 2048}


@pytest.mark.skipif(not GDI.exists(), reason="unpacked NFL Blitz 2001 disc not cached")
def test_real_disc_inventory():
    m = B.build(GDI)
    assert m["ip"]["product"] == "T9712N" and m["ip"]["version"] == "V1.001"
    assert m["first_read"]["sha256"].startswith("342a9a097c387800")
    assert m["first_read"]["refs"]["sbm"] == ["FOOTBALL.SBM", "PLAYERB.SBM", "PLAYERM.SBM", "PLAYERS.SBM"]
    bodies = {b["name"]: b for b in m["characters"]["bodies"]}
    for n in ("PLAYERS.SBM", "PLAYERM.SBM", "PLAYERB.SBM"):
        b = bodies[n]
        assert (b["verts"], b["strip_records"], b["strips"], len(b["bones"])) == (564, 1314, 129, 15)
        assert b["skinned_verts"] == 558 and b["size"] <= b["room"]
    a = m["characters"]["animations"]
    assert (a["sequences"], a["packed"], a["raw"], a["frames"]) == (307, 272, 35, 31086)
    head = next(x for x in m["characters"]["models"] if x["name"] == "MDL_HEAD.MDL")
    assert head["count"] == 3 and head["verts"] == 254
    assert m["characters"]["league"]["players_field"] == 925
    assert len(m["characters"]["team_packs"]) == 72
