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
