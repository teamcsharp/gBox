"""The area catalogue: grouping a disc's FST into areas, and the zone/episode attribution.

A synthetic FST proves the grouping; the real image (when present) proves the totals the research
doc quotes.
"""
import os
import struct

import pytest

from gbox import pso_areas as A

DISC = r"D:\gBox\cache\436e0bb84d5337d1\Phantasy Star Online Episode I & II Plus (USA).gcz"


class FakeDisc:
    """A GCDisc-shaped stub: `.files` is `{name: (offset, size)}`, `.read` serves a byte map."""

    def __init__(self, blobs):
        self.blobs = blobs
        self.files = {n: (i * 0x1000, len(b)) for i, (n, b) in enumerate(blobs.items())}
        self.game_id = "GPOE8P"
        self.title = "PHANTASY STAR ONLINE EPISODE I&II"

    def read(self, name):
        return self.blobs[name]


def coll(cx=0.0, cz=0.0):
    """A one-triangle collision REL in the GC layout `psomap.collision` reads."""
    V = [(cx, 0.0, cz), (cx + 10.0, 0.0, cz), (cx, 0.0, cz + 10.0)]
    vb = b"".join(struct.pack(">3f", *v) for v in V)
    fb = struct.pack(">4H", 0, 1, 2, 1) + struct.pack(">3f", 0.0, 1.0, 0.0) + b"\0" * 16
    mesh = struct.pack(">4I", 3, 0, 1, len(vb))
    mesh_off = len(vb) + len(fb)
    table_off = mesh_off + 16
    table = struct.pack(">I4fI", mesh_off, 0, 0, 0, 100, 0) + b"\0" * 0x18
    body = vb + fb + mesh + table
    root_off = len(body)
    body += struct.pack(">I", table_off)
    relocs = len(body)
    return body + struct.pack(">5I", relocs, 0, 0, 0, root_off) + b"\0" * 12


def setfile(n=3, x0=0.0):
    out = b""
    for i in range(n):
        out += struct.pack("<17I", 0x17, i, i, 1,
                           *struct.unpack("<3I", struct.pack("<3f", x0 + i, 1.0, 2.0)),
                           0, 0, 0, 0, 0x3F800000, 0x3F800000, 0, 0, 0, 0)
    return out


def disc():
    return FakeDisc({
        "Scene/map_forest01c.rel": coll(),
        "Scene/map_forest01n.rel": b"\0" * 32,
        "Scene/map_forest01r.rel": b"\0" * 32,
        "Scene/map_forest01s.GVM": b"GVMH" + b"\0" * 28,
        "Scene/map_forest01.GVM": b"GVMH" + b"\0" * 28,
        "Scene/map_cave01_00c.rel": coll(50.0, 50.0),
        "Scene/map_cave01_01c.rel": coll(90.0, 50.0),
        "Scene/map_lobby_green_be00c.rel": coll(1.0, 1.0),
        "Scene/map_forest01bm.bin": b"\0" * 8,
        "map_forest01d.dat": setfile(3),
        "map_forest01ad.dat": setfile(2, 10.0),
        "map_forest01_00d.dat": setfile(1),
        "map_ruins01_00_jm.evt": b"\0" * 20,
        "PlAbdy00.nj": b"NJCM" + b"\0" * 8,
    })


def test_scene_index_groups_roles_and_variants_in_order():
    idx = A.scene_index(disc().files)
    assert set(idx["forest01"]) == {"c", "n", "r", "s.GVM", "GVM", "bm.bin"}
    assert idx["cave01"]["c"] == ["Scene/map_cave01_00c.rel", "Scene/map_cave01_01c.rel"]
    assert "PlAbdy00.nj" not in idx                               # not a Scene file


def test_set_and_event_files():
    d = disc()
    assert A.set_files(d.files)["forest01"] == {"d": ["map_forest01_00d.dat", "map_forest01d.dat"],
                                               "ad": ["map_forest01ad.dat"]}
    # `map_forest01_00d.dat` and `map_forest01d.dat` share area `forest01`; both are kept
    events = A.event_files(d.files)
    assert events.get("ruins01") == ["map_ruins01_00_jm.evt"]


def test_zone_and_episode_attribution():
    assert A.episode_of("forest01") == 1 and A.zone_of("forest01") == "Forest"
    assert A.episode_of("ancient03") == 1 and A.zone_of("ancient03") == "Ruins"
    assert A.episode_of("ruins01") == 2 and A.zone_of("ruins01") == "VR Temple"
    assert A.episode_of("space02") == 2 and A.zone_of("space02") == "VR Spaceship"
    assert A.episode_of("jungle04") == 2
    assert A.episode_of("aforest02") == 1 and "alternate" in A.zone_of("aforest02")
    assert A.episode_of("nonsense") is None and A.zone_of("nonsense") is None


def test_area_table_is_the_executable_order():
    assert A.LIST_AREA_TABLE[:4] == ("city", "forest01", "forest02", "cave01")
    assert A.DOL_AREA_TABLE_OFFSET == 0x431C04
    assert "jungle07" in A.LIST_AREA_TABLE


def test_catalogue_totals_on_a_synthetic_disc():
    cat = A.catalogue(disc())
    areas = cat["areas"]
    assert set(areas) == {"forest01", "cave01", "lobby_green_be00", "ruins01"}
    assert areas["forest01"]["totals"]["triangles"] == 1
    assert areas["forest01"]["totals"]["placements"] == 6          # 3 + 2 + 1
    assert areas["forest01"]["totals"]["layouts"] == 1
    assert areas["cave01"]["totals"]["layouts"] == 2
    assert areas["forest01"]["episode"] == 1
    assert cat["decode_failures"] == []
    assert cat["totals"]["areas"] == 4


def test_markdown_renders_without_a_disc():
    md = A.to_markdown(A.catalogue(disc()))
    assert md.startswith("# PSO Episode I & II")
    assert "| `forest01` | 1 | Forest |" in md
    assert "`Scene/map_forest01c.rel`" in md


@pytest.mark.skipif(not os.path.exists(DISC), reason="owned PSO image not on this host")
def test_real_disc_areas_are_all_decoded():
    """Every Ep1/Ep2 field area has collision and a placement set, and nothing fails to decode."""
    from gbox.gcdisc import GCDisc
    cat = A.catalogue(GCDisc(DISC), hash_all=False)
    assert cat["decode_failures"] == []
    assert cat["totals"]["areas"] >= 70
    assert cat["totals"]["triangles"] > 700_000
    assert cat["totals"]["placements"] > 18_000
    for area in ("forest01", "forest02", "cave01", "cave02", "cave03", "machine01", "machine02",
                 "ancient01", "ancient02", "ancient03", "jungle01", "seabed01", "space01", "ruins01"):
        a = cat["areas"][area]
        assert a["collision"], area
        assert a["totals"]["placements"] > 0, area
