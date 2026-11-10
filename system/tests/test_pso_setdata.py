"""Area set data (`map_*d.dat`): the 68-byte placement records, decoded and written back.

No disc needed: the records are synthetic, and one test re-runs the whole round trip on the owned
image when it is present.
"""
import struct

import pytest

from gbox import pso_setdata as S

# One Forest 1 record, verbatim off the owned disc (map_forest01d.dat record 0): kind 0x17,
# set id 0x107AF, world position (483.12, 16.19, 813.58), scales 1.0.
WORDS = [0x17, 0x000107AF, 0x00004874, 1,
         0x43F18F9C, 0x41818F5D, 0x444B64E8,
         0, 0x1700, 0,
         0x42240005, 0x3F800001, 0x3F800002,
         9, 0, 0, 0x8CFABA20]


def record(i=0, **over):
    words = list(WORDS)
    rec = {"index": i, "raw": tuple(words)}
    for name, off in S.OFF.items():
        v = words[off // 4]
        rec[name] = struct.unpack("<f", struct.pack("<I", v))[0] if name in S.FLOAT_FIELDS else v
    rec.update(over)
    return rec


def blob(n=2):
    raw = struct.pack("<17I", *WORDS)
    return raw * n


def test_record_size_and_count():
    assert S.RECORD_SIZE == 0x44
    assert S.record_count(blob(3)) == 3
    assert S.record_count(b"") == 0
    with pytest.raises(S.SetDataError):
        S.record_count(b"\0" * 69)


def test_records_decode_named_fields():
    recs = S.records(blob(2))
    assert len(recs) == 2
    r = recs[0]
    assert r["kind"] == 0x17 and r["set_id"] == 0x000107AF and r["amount"] == 1
    assert r["x"] == pytest.approx(483.12198, abs=1e-3)
    assert r["y"] == pytest.approx(16.194671, abs=1e-3)
    assert r["z"] == pytest.approx(813.5771, abs=1e-3)
    assert r["scale_x"] == pytest.approx(1.0) and r["stamp"] == 0x8CFABA20


def test_build_is_byte_identical_and_lossless():
    data = blob(4)
    assert S.build(S.records(data)) == data


def test_move_changes_only_the_position_triplet():
    data = blob(2)
    out = S.build([S.move(S.records(data)[0], 12.5, -3.0, 44.25), S.records(data)[1]])
    assert out[:0x10] == data[:0x10]                       # id fields untouched
    assert out[0x10:0x1C] == struct.pack("<3f", 12.5, -3.0, 44.25)
    assert out[0x1C:0x44] == data[0x1C:0x44]               # everything else byte for byte
    assert out[0x44:] == data[0x44:]                       # record 2 untouched
    assert S.records(out)[0]["x"] == pytest.approx(12.5)


def test_patch_applies_field_changes_by_index():
    data = blob(3)
    out = S.patch(data, {1: {"kind": 0x1E}, 2: {"amount": 7}})
    recs = S.records(out)
    assert recs[1]["kind"] == 0x1E and recs[2]["amount"] == 7
    assert recs[0]["raw"] == S.records(data)[0]["raw"]
    with pytest.raises(S.SetDataError):
        S.patch(data, {9: {"kind": 1}})


def test_patch_rejects_a_non_u32():
    with pytest.raises(S.SetDataError):
        S.patch(blob(1), {0: {"kind": -1}})


def test_kinds_bounds_and_nearest():
    data = blob(2)
    recs = S.records(data)
    assert S.kinds(recs) == {0x17: 2}
    b = S.bounds(recs)
    assert b["min_x"] == b["max_x"] == pytest.approx(483.12198, abs=1e-3)
    near = S.nearest(recs, 0.0, 0.0)
    assert near is not None and near["index"] in (0, 1)
    assert S.nearest(recs, 0.0, 0.0, kinds_ok={0x99}) is None


DISC = r"D:\gBox\cache\436e0bb84d5337d1\Phantasy Star Online Episode I & II Plus (USA).gcz"


@pytest.mark.skipif(not __import__("os").path.exists(DISC), reason="owned PSO image not on this host")
def test_real_disc_sets_round_trip():
    """Every map_*.dat that is a set file round-trips byte for byte (141 files, 18,785 records)."""
    from gbox.gcdisc import GCDisc
    disc = GCDisc(DISC)
    sets = [n for n in disc.files if n.startswith("map_") and n.endswith(".dat")]
    assert len(sets) >= 140
    ok = 0
    for name in sorted(sets):
        data = disc.read(name)
        try:
            recs = S.records(data)
        except S.SetDataError:
            continue                                        # the *e.dat event tables, another format
        assert S.build(recs) == data, name
        ok += 1
    assert ok >= 141
