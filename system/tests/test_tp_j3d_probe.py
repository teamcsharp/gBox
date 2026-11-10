import os
import struct
import pytest
from gbox import tp_j3d_probe as P

ISO = "/mnt/gbox/quickswap2/Emulation/_emulation/GC ISO/Legend of Zelda, The - Twilight Princess (USA).iso"


def _synthetic():
    """Handmade bmd3: 2 joints (root + child), 3 f32 positions + 1 pad vertex, per the documented layout."""
    inf = bytearray(0x20 + 8 * 4)
    inf[0:4] = b"INF1"
    struct.pack_into(">I", inf, 4, len(inf))
    struct.pack_into(">III", inf, 0x0C, 0, 3, 0x18)
    nodes = [(0x10, 0), (1, 0), (0x10, 1), (2, 0), (0, 0)]
    for k, (t, i) in enumerate(nodes):
        struct.pack_into(">HH", inf, 0x18 + 4 * k, t, i)
    inf = bytes(inf[:0x18 + 20]) + b"\0" * 4
    inf = inf + b"\0" * (-len(inf) % 32)
    inf = inf[:4] + struct.pack(">I", len(inf)) + inf[8:]
    # JNT1: header 0x18, entries 2*0x40, remap 2*2, name table
    ent = 0x18
    rem = ent + 0x80
    nt = rem + 4
    names = b"root\0kid\0"
    tbl = struct.pack(">HH", 2, 0) + struct.pack(">HH", 0, 8 + 4 + 4 * 0) + struct.pack(">HH", 0, 8 + 4 + 5 - 4 + 4 - 4)
    # name offsets relative to table start: strings begin after 4 + 2*4 = 12
    tbl = struct.pack(">HH", 2, 0) + struct.pack(">HH", 0, 12) + struct.pack(">HH", 0, 17) + names
    body = b"\0" * 0x18
    body += b"".join(struct.pack(">HBB3f3hH3ff6f", 0, 1, 0, 1, 1, 1, 0, 0, 0, 0, i, 0, 0, 1.0, 0, 0, 0, 0, 0, 0) for i in range(2))
    body += struct.pack(">HH", 0, 1) + tbl
    jnt = bytearray(b"JNT1" + b"\0" * 4 + struct.pack(">H", 2) + b"\0\0" + struct.pack(">III", ent, rem, nt) + body[0x18:])
    jnt += b"\0" * (-len(jnt) % 32)
    jnt[4:8] = struct.pack(">I", len(jnt))
    # VTX1
    arr = 0x40 + 16 * 2
    pos = b"".join(struct.pack(">3f", i, 2 * i, 3 * i) for i in range(3)) + b"\xff" * 12
    vtx = bytearray(b"VTX1" + b"\0\0\0\0" + struct.pack(">I", 0x40) + struct.pack(">13I", arr, *([0] * 12)))
    vtx += b"\0" * (0x40 - len(vtx))
    vtx += struct.pack(">IIIB3x", 9, 1, 4, 0) + struct.pack(">IIIB3x", 0xFF, 1, 0, 0) + pos
    vtx += b"\0" * (-len(vtx) % 32)
    vtx[4:8] = struct.pack(">I", len(vtx))
    chunks = [bytes(inf), bytes(vtx), bytes(jnt)]
    raw = b"J3D2bmd3" + struct.pack(">II", 0x20 + sum(map(len, chunks)), 3) + b"\0" * 16 + b"".join(chunks)
    return raw


def test_synthetic_skeleton_and_positions():
    raw = _synthetic()
    ch = P.chunk_table(raw)
    assert set(ch) == {b"INF1", b"VTX1", b"JNT1"}
    js = P.joints(raw, ch)
    assert [j["parent"] for j in js] == [-1, 0]
    assert P.vtx_positions(raw, ch) == [(0.0, 0.0, 0.0), (1.0, 2.0, 3.0), (2.0, 4.0, 6.0)]


def test_rejects_garbage():
    with pytest.raises(P.J3DProbeError):
        P.chunk_table(b"J3D2bmd3" + b"\0" * 40)


@pytest.mark.skipif(not os.path.exists(ISO), reason="owned disc not mounted")
def test_owned_link_body_model():
    from gbox.formats.lz import yaz0_decompress
    from gbox.formats.rarc import walk
    from gbox.gcdisc import GCDisc

    d = GCDisc(ISO)
    r = yaz0_decompress(d.read("res/Object/Kmdl.arc"))
    m = [r[o:o + s] for p, o, s in walk(r) if p == "bmwr/al.bmd"][0]
    S = P.summarize(m)
    assert S["joint_count"] == 35 and S["roots"] == [0]
    assert S["joint_names"][:5] == ["center", "backbone1", "backbone2", "neck", "head"]
    assert S["position_count"] == 1558
    assert max(abs(v) for v in S["pos_min"] + S["pos_max"]) < 200
