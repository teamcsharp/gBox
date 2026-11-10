"""Tests for gbox.pd_mesh (Perfect Dark display-list -> triangle reader)."""
import os
import struct
from pathlib import Path

import pytest

from gbox import pd_mesh


def _fixture():
    """vtx array of 4 verts @0x00 (12B each), DL @0x40: VTX, TRI4(1 tri), TRI1, ENDDL."""
    b = bytearray(0x100)
    pts = [(0, 0, 0), (10, 0, 0), (0, 10, 0), (10, 10, 5)]
    for i, p in enumerate(pts):
        struct.pack_into(">3hH2h", b, i * 12, *p, i * 4, 32 * i, 64)
    dl = [
        (0x04 << 24 | 3 << 20 | 0 << 16 | 48, 0x04000000),
        (0xB1000000 | 0x0000, 0x00000000),                        # all zero: padding only
        (0xB1000000 | (0 << 12), (0x12 << 24)),                   # tri (0,1,2)
        (0xBF << 24, (2 * 1) << 16 | (2 * 3) << 8 | 2 * 2),       # tri (1,3,2)
        (0xB8 << 24, 0),
    ]
    for i, (w0, w1) in enumerate(dl):
        struct.pack_into(">II", b, 0x40 + i * 8, w0, w1)
    return bytes(b)


def test_decode_fixture():
    m = pd_mesh.decode_dl(_fixture(), 0x40, 0, 4)
    assert len(m.vertices) == 4 and m.vertices[3] == (10, 10, 5)
    assert m.triangles == [(0, 1, 2), (1, 3, 2)]
    assert m.uvs[1] == (1.0, 2.0) and m.colour_offsets[2] == 8
    assert m.skipped == 0
    assert "f 1/1 2/2 3/3" in pd_mesh.to_obj([m])


def test_bad_vtx_length_rejected():
    b = bytearray(_fixture())
    struct.pack_into(">I", b, 0x40, 0x04 << 24 | 3 << 20 | 40)
    with pytest.raises(ValueError):
        pd_mesh.decode_dl(bytes(b), 0x40, 0, 4)


def test_missing_enddl_rejected():
    with pytest.raises(ValueError):
        pd_mesh.decode_dl(bytes(0x100), 0x40, 0, 4, max_cmds=8)


def _rom():
    p = os.environ.get("PD_ROM")
    if not p or not Path(p).exists():
        pytest.skip("PD_ROM not set")
    from gbox import n64_rom
    return n64_rom.read(Path(p))


def test_owned_rom_cdark_combat_meshes():
    ms = pd_mesh.decode_model(_cdark())
    assert len(ms) == 15
    assert sorted(len(m.vertices) for m in ms)[0] == 36 and max(len(m.vertices) for m in ms) == 369
    assert sum(len(m.triangles) for m in ms) == 601 and all(m.skipped == 0 for m in ms)
    for m in ms:  # every loaded vertex is referenced exactly once (triangle soup)
        assert sorted(i for t in m.triangles for i in t) == list(range(len(m.vertices)))
    st = pd_mesh.edge_stats(ms[0])
    assert 20 < st["mean"] < 200


def _cdark():
    from gbox import pd_inventory as inv
    rom = _rom()
    f = next(x for x in inv.inventory(rom)["files"] if x["name"] == "Cdark_combatZ")
    blob = rom[f["offset"]:f["end"]]
    return inv.unzip_pd(blob)[0] if f["zipped"] else blob


def test_owned_rom_all_chr_decode():
    from gbox import pd_inventory as inv, pd_model
    rom = _rom()
    n = tris = skipped = 0
    for f in inv.inventory(rom)["files"]:
        if f["kind"] != "chr":
            continue
        blob = rom[f["offset"]:f["end"]]
        data = inv.unzip_pd(blob)[0] if f["zipped"] else blob
        for m in pd_mesh.decode_model(data, pd_model.parse(data)):
            tris += len(m.triangles)
            skipped += m.skipped
        n += 1
    assert n == 148 and tris == 65268
    assert skipped == 302  # TRI4/TRI1 refs to unloaded slots: documented unknown (G_VTX carry-over)
