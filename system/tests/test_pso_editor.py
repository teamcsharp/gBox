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


def test_the_measured_lobby_offset_maps_records_onto_world_positions():
    """The four door records, mapped with (+228,+291), are exactly the four door entities the game reports."""
    local = {"Guild": (-43.0, -118.0), "Shop": (-393.0, -143.5), "Warp": (26.0, -266.0), "Med": (-34.5, -384.5)}
    world = {"Guild": (185.0, 173.0), "Shop": (-165.0, 147.5), "Warp": (254.0, 25.0), "Med": (193.5, -93.5)}
    for name, (lx, lz) in local.items():
        got = E.world_position({"x": lx, "z": lz}, "map_city00_00o.dat")
        wx, wz = world[name]
        assert abs(got[0] - wx) < 0.01 and abs(got[1] - wz) < 0.01, f"{name}: {got} != {world[name]}"


def test_an_unmeasured_set_has_no_world_position():
    assert E.world_position({"x": 1.0, "z": 2.0}, "map_forest01_00o.dat") is None
    assert E.offset_of("map_city00_00o.dat") == (228.0, 291.0)


def test_the_door_class_indices_come_from_the_match():
    assert E.door_name(0x02000047) == "Guild"
    assert E.door_name(0x02000048) == "Warp"
    assert E.door_name(0x02000049) == "Med"
    assert E.door_name(0x02000046) == "Shop"
    assert E.door_name(0x02000040) is None


def test_the_cli_parses_the_documented_commands():
    ap = E.build_parser()
    a = ap.parse_args(["disc.gcz", "sets", "--kind", "object"])
    assert a.cmd == "sets" and a.kind == "object" and a.disc == "disc.gcz"
    b = ap.parse_args(["disc.gcz", "list", "map_city00_00o.dat", "--world", "--limit", "5"])
    assert (b.cmd, b.set, b.world, b.limit) == ("list", "map_city00_00o.dat", True, 5)
    c = ap.parse_args(["disc.gcz", "move", "map_city00_00o.dat", "20", "7", "-118", "-118"])
    assert (c.index, c.x, c.y, c.z) == (20, 7.0, -118.0, -118.0)
    d = ap.parse_args(["disc.gcz", "build", "pso_edit"])
    assert d.cmd == "build" and d.game_id == "436e0bb84d5337d1"


def test_the_cli_requires_a_command():
    ap = E.build_parser()
    with pytest.raises(SystemExit):
        ap.parse_args(["disc.gcz"])


def test_the_map_draws_doors_spawns_and_the_pedestal():
    recs = [
        {"index": 0, "kind": 0x02000048, "class_index": 72, "x": 26.0, "z": -266.0},    # Warp
        {"index": 1, "kind": 0x02000047, "class_index": 71, "x": -43.0, "z": -118.0},   # Guild
        {"index": 2, "kind": 0x02000000, "class_index": 0, "x": 1.0, "z": -37.0},       # spawn
        {"index": 3, "kind": 0x02000057, "class_index": 87, "x": 0.0, "z": 0.0},        # pedestal
    ]
    text = E.ascii_map(recs, "map_city00_00o.dat", cols=20, rows=8)
    assert "W" in text and "G" in text and "*" in text and "T" in text
    assert text.count("\n") == 8
    assert "('*' spawn" in text


def test_the_map_marks_the_player_and_handles_an_empty_set():
    text = E.ascii_map([{"index": 0, "kind": 0x02000000, "class_index": 0, "x": 1.0, "z": -37.0}],
                       "map_city00_00o.dat", cols=10, rows=4, marks={"player": (229.0, 254.0)})
    assert "P" in text and "*" in text
    assert E.ascii_map([], "map_city00_00o.dat") == "(no records in map_city00_00o.dat)"


def test_every_door_renders_as_its_own_mark_not_a_fallback():
    """A case mismatch in the mark table once drew the Warp door as a generic 'D'; each door must own its letter."""
    kinds = {"Warp": 0x02000048, "Guild": 0x02000047, "Shop": 0x02000046, "Med": 0x02000049}
    marks = {"Warp": "W", "Guild": "G", "Shop": "S", "Med": "M"}
    for name, kind in kinds.items():
        rec = {"index": 0, "kind": kind, "class_index": 70, "x": 0.0, "z": 0.0}
        text = E.ascii_map([rec], "map_city00_00o.dat", cols=4, rows=2)
        assert marks[name] in text, f"{name} did not render as {marks[name]}: {text!r}"
        assert "D" not in text


# ---- a floor id resolves to its area's sets ---------------------------------------------------------------------------------

def test_a_floor_resolves_to_the_sets_of_its_area():
    found = [{"name": n, "kind": "object", "where": "loose"} for n in (
        "map_city00d.dat", "map_city00_00o.dat", "map_forest01_00o.dat", "map_forest01d.dat",
        "map_forest02_01o.dat", "map_cave01_00o.dat", "map_lobby_01d.dat")]
    assert [r["name"] for r in E.sets_for_floor(found, 0)] == ["map_city00d.dat", "map_city00_00o.dat"]
    assert [r["name"] for r in E.sets_for_floor(found, 1)] == ["map_forest01_00o.dat", "map_forest01d.dat"]
    assert [r["name"] for r in E.sets_for_floor(found, 3)] == ["map_cave01_00o.dat"]
    assert E.sets_for_floor(found, 99) == []                     # outside the 36-floor table
    # episode 2's first floors are the a-prefixed areas
    found2 = [{"name": "map_aforest01_00o.dat", "kind": "object", "where": "loose"}]
    assert [r["name"] for r in E.sets_for_floor(found2, 1, episode2=True)] == ["map_aforest01_00o.dat"]
    assert E.sets_for_floor(found2, 1) == []


def test_a_floor_filter_does_not_match_a_longer_area_name():
    # floor 1 is forest01; forest010 and forest011 are not its sets
    found = [{"name": n, "kind": "object", "where": "loose"} for n in
             ("map_forest01_00o.dat", "map_forest010x.dat")]
    assert [r["name"] for r in E.sets_for_floor(found, 1)] == ["map_forest01_00o.dat"]
