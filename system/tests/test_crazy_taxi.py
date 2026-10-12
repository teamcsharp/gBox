import hashlib
import struct
from pathlib import Path

import pytest

from gbox import crazy_taxi as ct

ISO = Path("/home/ehm_eckx/gbox-cache/modbase/bc02bb68790ce2e7/Crazy Taxi (USA).iso")

CUBE = [(x, y, z) for z in (-1, 1) for y in (-1, 1) for x in (-1, 1)]
FACES = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]


def _cube_shp() -> bytes:
    """A minimal .shp laid out like the disc's loose ct/cube0.shp (radius sqrt3, scale radius/512, s16 +-18918)."""
    radius = 3 ** 0.5
    b = bytearray(0x2A0)
    struct.pack_into(">ff", b, 0, 1.0, radius)
    struct.pack_into(">3f", b, 0x2C, *(radius / 512,) * 3)
    struct.pack_into(">I", b, 0xCC, 0x120)            # POS
    struct.pack_into(">I", b, 0xDC, 0x160)            # TEX0
    struct.pack_into(">4I", b, 0x110, 0x180, 0x120, 0x1C0, 0x260)
    for i, v in enumerate(CUBE):
        struct.pack_into(">3h", b, 0x120 + 6 * i, *(c * 18918 for c in v))
    for i, uv in enumerate([(1, 1), (254, 1), (254, 254), (1, 254)]):
        struct.pack_into(">2h", b, 0x160 + 4 * i, *uv)
    struct.pack_into(">I", b, 0x180, 0x38)
    struct.pack_into(">II", b, 0x1A4, 0x1C0, 0xA0)
    dl = bytearray(b"\x90" + struct.pack(">H", 36))
    for a, bb, c, d in FACES:
        for p, t in ((a, 0), (bb, 1), (c, 2), (a, 0), (c, 2), (d, 3)):
            dl += struct.pack(">HH", p, t)
    b[0x1C0:0x1C0 + len(dl)] = dl
    b[0x260:0x269] = b"white.tex"
    return bytes(b)


def test_cube_shape_decodes_like_the_disc_oracle():
    s = ct.read_shape(_cube_shp(), "cube0")
    assert s.lists == [(0x1C0, 0xA0)]
    assert len(s.tris) == 12
    assert s.frac() == 6
    pts = s.positions()
    assert all(abs(abs(c) - 1.0) < 1e-3 for p in pts[:8] for c in p)
    assert s.uv[2] == (254 / 256, 254 / 256)
    assert s.textures == ["white.tex"]
    obj = ct.to_obj(s)
    assert obj.count("\nf ") == 12 and obj.count("\nv ") == len(s.pos)


def test_strip_and_fan_primitives():
    corner = lambda i: struct.pack(">H", i)
    strip = b"\x98" + struct.pack(">H", 4) + b"".join(corner(i) for i in range(4))
    fan = b"\xa0" + struct.pack(">H", 4) + b"".join(corner(i) for i in range(4))
    t = ct.decode_dl(strip + b"\0\0" + fan, ["pos"])
    as_idx = [tuple(c["pos"] for c in tri) for tri in t]
    assert as_idx == [(0, 1, 2), (2, 1, 3), (0, 1, 2), (0, 2, 3)]
    with pytest.raises(ValueError):
        ct.decode_dl(b"\x55\x00\x01", ["pos"])


def test_bank_round_trip_and_size_check():
    blobs = [("a.shp", b"\1" * 0x20), ("MP_YH_plyrA_atama.shp", _cube_shp())]
    data = ct.write_bank(blobs)
    entries = ct.read_bank(data)
    assert [(n, s) for n, _, s in entries] == [(n, len(b)) for n, b in blobs]
    assert ct.write_bank([(n, data[o:o + s]) for n, o, s in entries]) == data
    with pytest.raises(ValueError):
        ct.read_bank(data + b"\0" * 0x20)
    assert ct.driver_parts(entries, "A") == {"atama": entries[1][1:]}


@pytest.mark.skipif(not ISO.exists(), reason="owned Crazy Taxi GC disc not present")
def test_owned_disc_driver_inventory():
    from gbox.gcdisc import GCDisc
    disc = GCDisc(ISO)
    assert disc.game_id == ct.DISC_ID
    bank = disc.read(ct.BANK)
    assert hashlib.sha256(bank).hexdigest().startswith("a5171e43e8458a2e")
    entries = ct.read_bank(bank)
    assert len(entries) == 1586
    # main.dol's shape enum (0x80190a9c) gives MP_YH_plyrA_koshi id 0x48a; its bank position is 26 lower.
    assert [n for n, _, _ in entries].index("MP_YH_plyrA_koshi.shp") == 0x48A - 26
    assert ct.write_bank([(n, bank[o:o + s]) for n, o, s in entries]) == bank
    inv = ct.inventory(bank)
    assert set(inv["drivers"]) == {"axel", "bd_joe", "gena", "gus"}
    for d in inv["drivers"].values():
        assert set(d["parts"]) == set(ct.PARTS)
    assert inv["drivers"]["axel"]["tris"] == 389
    head = inv["drivers"]["axel"]["parts"]["atama"]
    assert (head["verts"], head["tris"]) == (64, 73)
    o, s = ct.driver_parts(entries, "A")["atama"]
    assert ct.read_shape(bank[o:o + s]).frac() == 8
