"""Tests for gbox.sf64_gfx (F3DEX1 walker + Arwing OBJ export)."""
import os
import struct

import pytest

from gbox import sf64_gfx as gfx
from gbox import sf64_inventory as inv

ROM = os.environ.get("SF64_ROM") or os.path.expanduser(
    "~/gbox-cache/59a2755566b669ed/rom.z64")
needs_rom = pytest.mark.skipif(not os.path.exists(ROM), reason="owned ROM not cached")


def test_synthetic_dl_vtx_tri():
    seg = bytearray(0x100)
    vt = struct.pack(">hhhHhhBBBB", 1, 2, 3, 0, 32, 64, 255, 0, 0, 255)
    seg[0x80:0x80 + 48] = vt * 3
    cmds = [
        (0x04 << 24 | (0 << 16) | (3 << 10) | (16 * 3 - 1), 0x03000080),
        (0xBF << 24, (0 << 16) | (2 << 8) | 4),
        (0xB8 << 24, 0),
    ]
    for i, (a, b) in enumerate(cmds):
        seg[i * 8:i * 8 + 8] = struct.pack(">II", a, b)
    m = gfx.mesh_from_dl(bytes(seg), 0)
    assert len(m["faces"]) == 1 and m["unknown"] == {}
    assert m["verts"][0]["pos"] == (1, 2, 3) and m["verts"][0]["uv"] == (1.0, 2.0)


@needs_rom
def test_arwing_export(tmp_path):
    rom = inv.load_rom(ROM)
    res = gfx.export_arwing_obj(rom, str(tmp_path / "a.obj"))
    assert res["limbs"] == 18
    dls = {m["dl"]: m for m in res["meshes"]}
    for off in (0x9B60, 0x15D80, 0x16660):  # body, right wing, left wing
        assert off in dls and dls[off]["faces"] > 0
    assert all(not m["unknown_ops"] for m in res["meshes"])
    xs = [float(l.split()[1]) for l in open(tmp_path / "a.obj") if l.startswith("v ")]
    assert abs(min(xs) + max(xs)) < 1.0  # left/right symmetric rest pose
