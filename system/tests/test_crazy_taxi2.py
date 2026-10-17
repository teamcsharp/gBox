"""gbox.crazy_taxi2: the Crazy Taxi 2 (DC) POL*.BIN object walker (request #1482). Synthetic files built here; the
owned-disc test reads the QuickSwap2 CDI (GBOX_CT2_CDI, else the Spark mount) and skips without it."""
import hashlib
import os
import struct
from pathlib import Path

import pytest

from gbox import crazy_taxi2 as c2

CDI = os.environ.get("GBOX_CT2_CDI", "/mnt/gbox/quickswap2/Emulation/_emulation/_dc iso/Crazy Taxi 2.cdi")


def _exists(p) -> bool:
    try:
        return Path(p).is_file()
    except OSError:
        return False


def _vert(x, y, z):
    return struct.pack("<8f", x, y, z, 0.0, 1.0, 0.0, 0.5, -0.5)


def _mesh(strips: bytes, tex=2) -> bytes:
    h = bytearray(c2.MESH_HEADER)
    struct.pack_into("<4I", h, 0, 0x800000AC, 0x83000000, 0x20082463, 0x08000000)
    struct.pack_into("<4f", h, 0x10, 0.0, 0.0, 0.0, 1.0)
    struct.pack_into("<I", h, 0x20, tex)
    struct.pack_into("<I", h, 0x4C, len(strips))
    return bytes(h) + strips


def _ref(entry_pos: int, target: int) -> bytes:
    """A reference entry at `entry_pos` (offset inside the strip data) to the full vertex at `target`."""
    return struct.pack("<Ii", 0x5FFFFE60, target - (entry_pos + 8))


def _model() -> bytes:
    """Slot 0 empty; slot 1: a 4-vertex strip + a 1-triangle list that reuses two strip vertices by reference."""
    empty = struct.pack("<II4f", c2.EMPTY, 3, 0, 0, 0, 0) + struct.pack("<II", 0, 0)
    base = len(empty) + 0x18 + c2.MESH_HEADER                     # file offset of the first strip header
    s = struct.pack("<Ii", 0x72, 4)
    v0 = base + len(s)
    s += _vert(0, 0, 0) + _vert(1, 0, 0) + _vert(0, 1, 0) + _vert(1, 1, 0)
    s += struct.pack("<Ii", 0x6A, 1)
    s += _ref(base + len(s), v0) + _vert(0, 0, 1)
    s += _ref(base + len(s), v0 + 3 * 32)
    obj = struct.pack("<II4f", 1, 1, 0.5, 0.5, 0.0, 1.5) + _mesh(s) + struct.pack("<II", 0, 7)
    return empty + obj


def test_walk_decodes_strips_triangle_lists_and_references():
    objs = c2.walk(_model())
    assert len(objs) == 2 and objs[0].empty and objs[0].flags == (c2.EMPTY, 3)
    ob = objs[1]
    assert not ob.empty and ob.centre == (0.5, 0.5, 0.0) and ob.radius == 1.5 and ob.entries == 7
    (m,) = ob.meshes
    assert m.texture == 2 and m.refs == 2 and len(m.pos) == 5
    assert m.tris == [(0, 1, 2), (2, 1, 3), (0, 4, 3)]
    assert m.uv[0] == (0.5, -0.5) and m.nrm[4] == (0.0, 1.0, 0.0)
    obj = c2.to_obj(objs, "x")
    assert obj.count("\nv ") + obj.startswith("v ") == 5 and obj.count("\nf ") == 3 and "o x_01" in obj


def test_walk_rejects_broken_layouts():
    good = _model()
    with pytest.raises(ValueError, match="trailing"):
        c2.walk(good + b"\0" * 8)
    bad = bytearray(good)
    struct.pack_into("<I", bad, len(bad) - 4, 6)                  # terminator count disagrees with the meshes
    with pytest.raises(ValueError, match="terminator"):
        c2.walk(bytes(bad))
    bad = bytearray(good)
    i = bad.index(struct.pack("<I", 0x5FFFFE60))
    struct.pack_into("<i", bad, i + 4, struct.unpack_from("<i", bad, i + 4)[0] + 4)   # reference into a vertex's middle
    with pytest.raises(ValueError, match="not a vertex"):
        c2.walk(bytes(bad))
    with pytest.raises(ValueError):
        c2.walk(good[:-12])


def test_kinds_and_driver_names():
    assert c2.kind_of("POLPP2A.BIN") == "driver" and c2.kind_of("POLPPL0.BIN") == "pedestrians"
    assert c2.kind_of("POLPPTST.BIN") == "test driver" and c2.kind_of("POLPSG0.BIN") == "passengers"
    assert c2.kind_of("POLPC1A1.BIN") == "cab" and c2.kind_of("POLDC0.BIN") == "city"
    row = c2.summary("POLPP2AH.BIN", _model())
    assert (row["driver"], row["detail"], row["slots"], row["drawn"], row["triangles"]) == ("Slash", "high", 2, 1, 3)
    assert list(c2.DRIVERS.values()) == ["Axel", "B.D. Joe", "Gena", "Gus", "Slash", "Iceman", "Cinnamon", "Hot-D"]


@pytest.mark.skipif(not _exists(CDI), reason="owned Crazy Taxi 2 CDI not present")
def test_owned_disc_pol_files_walk_to_the_end():
    from gbox.gdrom import CDIRom
    disc = CDIRom(CDI)
    try:
        assert disc.read("BINS/IP.BIN")[0x40:0x48] == c2.PRODUCT.encode()
        for name, sha in c2.FILES_SHA256.items():
            assert hashlib.sha256(disc.read(name)).hexdigest() == sha, name
        pols = sorted(n for n in disc.files if n.startswith("POL"))
        assert len(pols) == 35
        axel = c2.summary("POLPP2A.BIN", disc.read("POLPP2A.BIN"))
        assert (axel["slots"], axel["drawn"], axel["triangles"]) == (47, 21, 845)
        psg = c2.summary("POLPSG0.BIN", disc.read("POLPSG0.BIN"))
        assert (psg["slots"], psg["drawn"], psg["triangles"]) == (1200, 731, 19113)
        drivers = [n for n in pols if c2.kind_of(n) == "driver"]
        assert len(drivers) == 16
        for n in drivers:                                         # every player file parses; parts sit near their joint
            objs = c2.walk(disc.read(n))
            assert sum(not o.empty for o in objs) >= 15
            assert all(max(abs(c) for c in o.centre) < 4.0 for o in objs if not o.empty), n
    finally:
        disc.close()
