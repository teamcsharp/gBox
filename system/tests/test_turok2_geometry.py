"""Turok 2 native geometry reader tests (synthetic + owned ROM)."""
import os
import struct
from pathlib import Path

import pytest

from gbox import turok2_geometry as t2g
from gbox import turok_inventory as ti

ROM = Path(os.environ.get(
    "GBOX_TUROK2_ROM",
    Path.home() / "gBox_alt/gbox-cache" / "96c6d766ba6202ca" / "rom.z64"))
ROM_SHA256 = "6c8ec2083adeb6eb7bc0aad865384f77a8f89a98ff21b74a630dd85e8256ebf8"


def _cart():
    if not ROM.exists():
        pytest.skip("owned Turok 2 ROM not present")
    return t2g.Cart(ROM.read_bytes())


def test_parse_vertex_part_synthetic():
    rec = struct.pack(">3hH2h2H", 10, -20, 30, 7, 64, 128, 0, 0)
    assert len(rec) == 16
    part = t2g.parse_vertex_part(struct.pack(">II", 16, 1) + rec)
    assert part.stride == 16
    assert part.count == 1
    assert part.positions == [(10, -20, 30)]
    assert part.flags == [7]
    assert part.uvs == [(64, 128)]
    lo, hi = part.bbox()
    assert lo == (10, -20, 30) and hi == (10, -20, 30)


def test_parse_vertex_part_rejects_overrun():
    with pytest.raises(t2g.Turok2FormatError):
        t2g.parse_vertex_part(struct.pack(">II", 16, 99))


def test_owned_rom_graphic_object_census():
    cart = _cart()
    assert cart.object_count == 2705
    parts = cart.parts(0)
    assert set(parts) == {"object_info", "geometry", "anims", "static_events"}
    assert parts["geometry"][:3] == b"RNC"


def test_owned_rom_geometry_block_shapes():
    cart = _cart()
    g0 = cart.geometry(0)
    g77 = cart.geometry(77)
    assert len(g0.blocks) == 3 and not g0.is_skinned
    assert len(g77.blocks) == 6 and g77.is_skinned
    assert len(cart.texture_header(0)) == 8
    assert len(cart.texture_header(77)) == 8


def test_owned_rom_vertex_parts():
    cart = _cart()
    p0 = cart.node_parts(0)
    assert len(p0) == 1
    assert (p0[0].stride, p0[0].count) == (16, 42)
    p77 = cart.node_parts(77)
    assert len(p77) == 15
    assert [(p.stride, p.count) for p in p77[:4]] == [(16, 520), (16, 35), (16, 24), (16, 24)]
    lo, hi = p0[0].bbox()
    assert lo[0] <= hi[0] and lo[1] <= hi[1] and lo[2] <= hi[2]
    for p in p77:
        assert p.stride == 16
