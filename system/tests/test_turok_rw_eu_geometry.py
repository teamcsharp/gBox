"""Bounded Europe GraphicObject 174 geometry probe (structure facts only)."""
import struct

import pytest

from gbox import turok_rw_eu_geometry as g
from tests.test_turok_rw_eu_inventory import SOURCE, _rom


def _iset(blocks):
    n = len(blocks)
    off = 4 + 4 * (n + 1)
    hdr, body = [struct.pack(">I", n)], b""
    for b in blocks:
        hdr.append(struct.pack(">I", off + len(body)))
        body += b
    hdr.append(struct.pack(">I", off + len(body)))
    return b"".join(hdr) + body


def _synthetic():
    verts = struct.pack(">II", 16, 2) + struct.pack(">3hH2h4s", 1, 2, 3, 0, 0, 0, b"\0" * 4) \
        + struct.pack(">3hH2h4s", -4, 5, 6, 0, 0, 0, b"\0" * 4)
    head = struct.pack(">IIIII", 7, 9, 0x01330600, 0x808080FF, 0xFFFFFFFF) + struct.pack(">HH", 32, 16)
    sec = _iset([head, struct.pack(">3H", 1, 2, 3)])
    skel = struct.pack(">II", 0x70, 1) + b"\0" * 0x70
    empty = struct.pack(">II", 0, 0)
    return _iset([verts, empty, _iset([sec]), empty, struct.pack(">II", 0, 8), skel])


def test_synthetic_part_roundtrip_fields():
    p = g.parse_part(_synthetic())
    assert p["n_vertices"] == 2 and p["bbox"] == [(-4, 1), (2, 5), (3, 6)]
    s = p["sections"][0]
    assert (s["u32_unknown"], s["texset"], s["stream_words"]) == (7, 9, 3)
    assert (s["mult_u"], s["mult_v"]) == (32, 16)


def test_rejects_dinosaur_hunter_two_block_geometry():
    with pytest.raises(ValueError):
        g.parse_part(_iset([b"\0" * 8, b"\0" * 8]))


@pytest.mark.skipif(not SOURCE.exists(), reason="owned Europe ROM not mounted")
def test_europe_object174_probe():
    r = g.probe(_rom())
    assert r["geometry_sha1"] == "b2dab07a5212f7377a8557a23aa6bfb960bef93e"
    assert r["n_parts"] == 37
    assert r["large"] == list(range(16)) and r["small"] == list(range(16, 37))
    assert len(r["block5_distinct"]) == 1
    assert {p["block5_record"] for p in r["parts"]} == {(0x70, 22)}
    assert all(p["block_sizes"][1] == 8 for p in r["parts"])
    assert sum(len(p["sections"]) for p in r["parts"][:16]) == 116
    assert all(len(p["sections"]) == 1 for p in r["parts"][16:])
    for p in r["parts"]:  # interleaved vertices stay in a sane model range
        assert all(-1000 < lo and hi < 1000 for lo, hi in p["bbox"])
