"""gbox.pso_editor: the editorial layer over the map writer -- listing, edit normalisation, preview."""
import struct
from pathlib import Path

import pytest

from gbox import pso_editor as E

DISC = Path(r"D:\gBox\cache\436e0bb84d5337d1\Phantasy Star Online Episode I & II Plus (USA).gcz")


def test_discovery_keeps_only_set_looking_files():
    class Disc:
        files = {"map_forest01_00d.dat": 1, "notes.txt": 2, "map_forest01_00o.dat": 3, "other.dat": 4}

    found = E.sets(Disc())
    names = [s["name"] for s in found if s["where"] == "loose"]
    assert names == ["map_forest01_00d.dat", "map_forest01_00o.dat"]
    assert E.kind_of("map_forest01_00o.dat") == "object"
    assert E.kind_of("map_forest01_00e.dat") == "enemy"
    assert E.kind_of("map_forest01_00.evt") == "event"
    assert E.kind_of("plCbdy00.nj") is None


def test_an_edit_is_normalised_into_a_writer_op():
    op = E.edit("move", "map_forest01_00o.dat", index=7, x=1.0, y=2.0, z=3.0)
    assert op == {"op": "move", "set": "map_forest01_00o.dat", "index": 7, "x": 1.0, "y": 2.0, "z": 3.0}


def test_an_edit_missing_a_field_names_it():
    with pytest.raises(E.EditError, match="missing 'index'"):
        E.edit("move", "map_forest01_00o.dat", x=1.0, y=2.0, z=3.0)
    with pytest.raises(E.EditError, match="missing 'dz'"):
        E.edit("nearest", "map_forest01_00o.dat", x=1.0, z=2.0, dx=3.0)


def test_an_unknown_edit_is_refused_with_the_known_ones():
    with pytest.raises(E.EditError, match="known: move, nearest, add, delete"):
        E.edit("rotate", "map_forest01_00o.dat", index=0)


def test_an_empty_edit_list_is_refused():
    with pytest.raises(E.EditError, match="no edits"):
        E.edits()


def test_edits_returns_the_list_unchanged_for_the_writer():
    one = E.edit("delete", "map_forest01_00o.dat", index=3)
    assert E.edits(one) == [one]


def _set_bytes(records):
    """A minimal set file: one 68-byte record per entry, kind in word 0 and x/y/z as f32 at 16/20/24."""
    out = bytearray()
    for kind, (x, y, z) in records:
        words = [0] * 17
        words[0] = kind
        words[4] = struct.unpack("<I", struct.pack("<f", x))[0]
        words[5] = struct.unpack("<I", struct.pack("<f", y))[0]
        words[6] = struct.unpack("<I", struct.pack("<f", z))[0]
        out += struct.pack("<17I", *words)
    return bytes(out)


def test_placements_reports_index_kind_and_position():
    class Disc:
        files = {"map_forest01_00o.dat": 1}

        def read(self, name):
            return _set_bytes([(2, (10.0, 1.0, -3.0)), (5, (20.0, 2.0, -4.0))])

    out = E.placements(Disc(), "map_forest01_00o.dat")
    assert out["count"] == 2
    first, second = out["records"]
    assert first["index"] == 0 and first["kind"] == 2 and first["class"] == "object"
    assert (first["x"], first["y"], first["z"]) == (10.0, 1.0, -3.0)
    assert second["class"] == "door" and second["x"] == 20.0


@pytest.mark.skipif(not DISC.is_file(), reason="the disc is not on this machine")
def test_the_real_disc_exposes_hundreds_of_sets_and_lists_one():
    from gbox import gcdisc

    d = gcdisc.GCDisc(str(DISC))
    found = E.sets(d)
    assert len(found) > 100
    pl = E.placements(d, found[0]["name"])
    assert pl["count"] > 0
    assert all(set(r) >= {"index", "kind", "class", "x", "y", "z"} for r in pl["records"])
