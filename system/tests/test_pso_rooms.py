"""CP8 (GameCube form): a room's footprint and origin read from its `r.rel` opening four points."""
import pathlib
import struct

import pytest

from gbox import pso_rooms as R

DISC = pathlib.Path(r"D:\gBox\cache\mods\436e0bb84d5337d1\pso_city_npc_moved"
                    r"\Phantasy Star Online Episode I & II Plus (USA).iso")


def test_the_quad_gives_an_axis_aligned_footprint():
    quad = R.room_quad(struct.pack(">12f", -100, 0, -150, -100, 0, 150, 100, 0, -150, 100, 0, 150))
    assert quad["origin"] == (0.0, 0.0, 0.0)
    assert quad["size"] == (200.0, 0.0, 300.0)
    assert quad["flat"] is True


def test_a_sloped_quad_is_data_not_an_error():
    """12 of 141 real rooms slope (boss05 spans y 1.23..7.0), so the reader records it instead of refusing."""
    sloped = struct.pack(">12f", 0, 0, 0, 10, 5, 0, 10, 9, 10, 0, 4, 10)
    quad = R.room_quad(sloped)
    assert quad["flat"] is False and quad["slope"] == (0, 9)
    assert quad["size"][2] == 10.0


def test_a_footprint_with_no_area_is_refused():
    flat_line = struct.pack(">12f", 0, 0, 0, 0, 0, 10, 0, 0, 10, 0, 0, 0)       # x never changes
    with pytest.raises(R.RoomError, match="no footprint"):
        R.room_quad(flat_line)


def test_a_truncated_file_is_refused():
    with pytest.raises(R.RoomError, match="smaller"):
        R.room_quad(b"\x00" * 8)


def test_the_real_rooms_have_measured_origins_and_sizes():
    from gbox import gcdisc
    if not DISC.is_file():
        pytest.skip("the disc is not on this machine")
    d = gcdisc.GCDisc(str(DISC))
    names = sorted(n for n in d.files if n.startswith("Scene/map_") and n.endswith(R.REL_SUFFIX))
    assert len(names) == 141
    q00 = R.room_quad(d.read("Scene/map_aancient01_00r.rel"))
    assert q00["origin"] == (0.0, 0.0, 0.0) and q00["size"] == (200.0, 0.0, 300.0)
    q04 = R.room_quad(d.read("Scene/map_aancient01_04r.rel"))
    assert q04["origin"] == (162.5, 0.0, 75.0) and q04["size"] == (25.0, 0.0, 40.0)
    listed = R.rooms(names, d.read)
    assert len(listed) == 141                              # every GC r.rel carries a footprint
    assert all(room["size"][0] > 0 and room["size"][2] > 0 for room in listed)
    sloped = [n for n in names if not R.room_quad(d.read(n))["flat"]]
    assert len(sloped) == 12                               # measured: 12 rooms are not horizontal


def _disc():
    from gbox import gcdisc
    if not DISC.is_file():
        pytest.skip("the disc is not on this machine")
    return gcdisc.GCDisc(str(DISC))


def test_the_rooms_of_an_area_nest_only_where_measured_and_select_its_placements():
    """CP8's second half, with the nesting measured: 5 room rectangles, only room 03 sits inside room 00.

    The area's placement set shares the rooms' coordinate space (an offset search finds no better translation than zero),
    so the join is point-in-rectangle: of `map_ancient01_00_00o.dat`'s 234 records, **126 fall inside exactly one room**,
    **0 inside two** (no record lands in the 03-in-00 overlap) and 108 inside none.
    """
    from gbox import pso_map_write as W, pso_setdata as P
    disc = _disc()

    room_files = sorted(n for n in disc.files
                        if n.startswith("Scene/map_aancient01_") and n.endswith(R.REL_SUFFIX))
    assert len(room_files) == 5
    quads = {n.rsplit("_", 1)[-1]: R.room_quad(disc.read(n)) for n in room_files}

    def inside(a, b):
        tol = 1e-3
        return (a["min"][0] >= b["min"][0] - tol and a["max"][0] <= b["max"][0] + tol
                and a["min"][2] >= b["min"][2] - tol and a["max"][2] <= b["max"][2] + tol)

    nested = [(a, b) for a in quads for b in quads if a != b and inside(quads[a], quads[b])]
    assert nested == [("03r.rel", "00r.rel")]          # exactly one nesting, measured

    data, _where = W.read_set(disc, "map_ancient01_00_00o.dat")
    points = [(rec["x"], rec["z"]) for rec in P.records(data)]
    counts = [sum(1 for q in quads.values() if R.contains(q, x, z)) for x, z in points]
    assert counts.count(2) == 0                        # nothing lands in the 03-in-00 overlap
    assert counts.count(1) == 126
    assert counts.count(0) == 108


