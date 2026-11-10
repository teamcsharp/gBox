"""gbox.pso_map_write: the placement edits and the build/verify contract (no disc, no emulator).

A synthetic disc stub with one loose set file and one GSL archive carrying a set entry proves every op
path; the real-disc test is skipped when the owned image is not on the host.
"""
import os
import struct

import pytest

from gbox import pso_map_write as W
from gbox import pso_setdata as S

DISC = r"D:\gBox\cache\436e0bb84d5337d1\Phantasy Star Online Episode I & II Plus (USA).gcz"


def setblob(n=3, x0=0.0):
    out = b""
    for i in range(n):
        out += struct.pack("<17I", 0x20000 | (8 + i), 0x1000 + i, 0x2000 + i, 1,
                           *struct.unpack("<3I", struct.pack("<3f", x0 + i, 5.0, 7.0)),
                           0, 0, 0, 0, 0x3F800000, 0x3F800000, 0, 0, 0, 0)
    return out


def gsl(entries: dict[str, bytes]) -> bytes:
    """A GSL archive: 0x30-byte table then 0x800-aligned blobs."""
    names = list(entries)
    head = bytearray(len(names) * 0x30)
    body, start = bytearray(), ((len(names) * 0x30) + 0x7FF) // 0x800 * 0x800
    for i, n in enumerate(names):
        blob = entries[n]
        pos = start + len(body)
        head[i * 0x30:i * 0x30 + len(n)] = n.encode()
        struct.pack_into(">II", head, i * 0x30 + 0x20, pos // 0x800, len(blob))
        body += blob + bytes((-len(blob)) % 0x800)
    return bytes(head) + bytes(start - len(head)) + bytes(body)


class Disc:
    def __init__(self, blobs):
        self.blobs = blobs
        self.files = {n: (i * 0x100000, len(b)) for i, (n, b) in enumerate(blobs.items())}

    def read(self, name):
        return self.blobs[name]


def disc():
    return Disc({
        "gsl_set_object.gsl": gsl({"map_forest01_00o.dat": setblob(4),
                                    "map_forest02_00o.dat": setblob(2, 50.0)}),
        "map_forest01d.dat": setblob(3),
    })


# ------------------------------------------------------------------------------------------------ edits

def test_move_patch_is_twelve_bytes_and_nothing_else():
    data = setblob(3)
    change = W.set_placement_change(data, 1, 10.0, 11.0, 12.0)
    assert list(change) == ["patch"] and len(change["patch"]) == 1
    p = change["patch"][0]
    assert p["offset"] == S.RECORD_SIZE + S.OFF["x"]
    assert p["hex"] == struct.pack("<3f", 10.0, 11.0, 12.0).hex()
    out = data[:p["offset"]] + bytes.fromhex(p["hex"]) + data[p["offset"] + 12:]
    assert len(out) == len(data)
    recs = S.records(out)
    assert (recs[1]["x"], recs[1]["y"], recs[1]["z"]) == (10.0, 11.0, 12.0)
    assert recs[0]["raw"] == S.records(data)[0]["raw"] and recs[2]["raw"] == S.records(data)[2]["raw"]


def test_move_rejects_bad_coordinates_index_and_no_ops():
    data = setblob(2)
    with pytest.raises(W.MapEditError):
        W.set_placement_change(data, 9, 1.0, 1.0, 1.0)
    with pytest.raises(W.MapEditError):
        W.set_placement_change(data, 0, float("nan"), 1.0, 1.0)
    with pytest.raises(W.MapEditError):
        W.set_placement_change(data, 0, 0.0, 5.0, 7.0)          # already there
    with pytest.raises(W.MapEditError):
        W.ops_to_changes(disc(), [])


def test_add_and_delete_change_the_record_count_only():
    data = setblob(2)
    added = W.add_placement_change(data, 0x91, 1.0, 2.0, 3.0)["bytes"]
    assert len(added) == len(data) + S.RECORD_SIZE
    assert len(S.records(added)) == 3 and S.kind_class(S.records(added)[2]["kind"]) == 0x91
    deleted = W.delete_placement_change(data, 0)["bytes"]
    assert len(S.records(deleted)) == 1
    assert S.records(deleted)[0]["set_id"] == S.records(data)[1]["set_id"]


# ------------------------------------------------------------------------------------------------ locations

def test_read_set_finds_a_loose_file_and_an_archive_entry():
    d = disc()
    loose, where = W.read_set(d, "map_forest01d.dat")
    assert where == {"kind": "file", "path": "map_forest01d.dat"} and len(S.records(loose)) == 3
    blob, where = W.read_set(d, "map_forest01_00o.dat")
    assert where["kind"] == "gsl" and where["archive"] == "gsl_set_object.gsl"
    assert where["offset"] > 0 and len(S.records(blob)) == 4
    with pytest.raises(W.MapEditError):
        W.read_set(d, "nope.dat")


def test_ops_to_changes_patches_a_loose_file_and_an_archive_in_place():
    d = disc()
    changes, expect = W.ops_to_changes(d, [{"op": "move", "set": "map_forest01d.dat",
                                            "index": 0, "x": -5.0, "y": 6.0, "z": 7.0}])
    assert list(changes) == ["map_forest01d.dat"] and "patch" in changes["map_forest01d.dat"]
    assert expect[0]["was"] == [0.0, 5.0, 7.0]

    changes, expect = W.ops_to_changes(d, [{"op": "move", "set": "map_forest01_00o.dat",
                                            "index": 2, "x": 40.0, "y": 5.0, "z": 7.0}])
    assert list(changes) == ["gsl_set_object.gsl"], changes
    entry_off = W.set_archive_files(d, "object")["map_forest01_00o.dat"][1]
    assert changes["gsl_set_object.gsl"]["patch"][0]["offset"] == entry_off + 2 * S.RECORD_SIZE + S.OFF["x"]
    assert "bytes" not in changes["gsl_set_object.gsl"]          # in place, the table cannot shift


def test_nearest_moves_the_closest_placement_by_a_delta():
    d = disc()
    changes, expect = W.ops_to_changes(d, [{"op": "nearest", "set": "map_forest01_00o.dat",
                                            "x": 2.0, "z": 7.0, "dx": 25.0}])
    # record 2 is at x=2.0, so it moves to 27.0 with y and z kept
    p = changes["gsl_set_object.gsl"]["patch"][0]
    assert struct.unpack("<3f", bytes.fromhex(p["hex"])) == (27.0, 5.0, 7.0)
    assert expect[0]["index"] == 2


def test_ops_to_changes_rebuilds_an_archive_when_a_record_is_added():
    d = disc()
    changes, expect = W.ops_to_changes(d, [{"op": "add", "set": "map_forest01_00o.dat",
                                            "kind": 0x20008, "x": 1.0, "y": 2.0, "z": 3.0}])
    assert "bytes" in changes["gsl_set_object.gsl"]
    from gbox.pso_gc import gsl_entries
    after = gsl_entries(bytes(changes["gsl_set_object.gsl"]["bytes"]))
    ent = {n: (o, s) for n, o, s in after}["map_forest01_00o.dat"]
    assert ent[1] == len(setblob(4)) + S.RECORD_SIZE
    assert len(S.records(bytes(changes["gsl_set_object.gsl"]["bytes"])[
        ent[0]:ent[0] + ent[1]])) == 5


# ------------------------------------------------------------------------------------------------ kind field

def test_kind_splits_into_flags_and_class_index():
    assert S.kind_class(0x20088) == 0x88 and S.kind_flags(0x20088) == 0x20000
    assert S.kind_class(0x8000008) == 8 and S.kind_flags(0x8000008) == 0x8000000
    assert S.kind_class(0x92) == 0x92 and S.kind_flags(0x92) == 0
    rep = S.kind_report(S.records(setblob(3)))
    assert rep["flags"] == {0x20000: 3} and rep["classes"] == {8: 1, 9: 1, 10: 1}


@pytest.mark.skipif(not os.path.exists(DISC), reason="owned PSO image not on this host")
def test_real_disc_object_sets_are_68_byte_records_with_a_byte_class():
    """The kind census that proves the flags|class split, on the real archive."""
    from gbox.pso_gc import open_disc
    from gbox.pso_gc import gsl_entries
    disc_ = open_disc(DISC)
    try:
        data = disc_.read("gsl_set_object.gsl")
        flags, classes, total = set(), set(), 0
        for name, off, size in gsl_entries(data):
            recs = S.records(data[off:off + size])
            total += len(recs)
            for r in recs:
                flags.add(S.kind_flags(r["kind"]))
                classes.add(S.kind_class(r["kind"]))
        assert total > 22_000
        assert len(flags) == 12 and max(flags) <= 0x8000200
        assert len(classes) > 100 and max(classes) <= 0xFF
        assert all(f & 0xFF == 0 for f in flags)
    finally:
        disc_.f.close()
