"""Room-local -> world offset solving (`gbox.pso_room_offset`): the P6a proof gap.

Synthetic quadruples prove the subset match and the translation solve; the owned-image
test re-runs the real solve on the four room-10 doors when the disc is present.
"""
import itertools
import math
import os
import random
import struct

import pytest

from gbox import pso_room_offset as R, pso_setdata as S

DISC = r"D:\gBox\cache\436e0bb84d5337d1\Phantasy Star Online Episode I & II Plus (USA).gcz"
LOCAL_DISC = "/home/ehm_eckx/gBox_alt/gbox-cache/436e0bb84d5337d1/Phantasy Star Online Episode I & II Plus (USA).gcz"


def _rec(i, x, z, kind):
    words = [0] * 17
    words[S.OFF["kind"] // 4] = kind
    for name, val in (("x", x), ("y", 0.0), ("z", z)):
        words[S.OFF[name] // 4] = struct.unpack("<I", struct.pack("<f", float(val)))[0]
    rec = {"index": i, "raw": tuple(words), "kind": kind}
    rec.update(x=float(x), y=0.0, z=float(z))
    return rec


def _room_with_doors(offset, noise=0.0, seed=7):
    """28 records: four 'doors' are a translated, optionally noisy copy of ROOM10_DOORS."""
    rng = random.Random(seed)
    recs = [_rec(i, rng.uniform(-600, 100), rng.uniform(-2020, 40), 0x2000000 + i)
            for i in range(24)]
    for j, (name, (ox, oz)) in enumerate(R.ROOM10_DOORS.items()):
        x = ox - offset[0] + rng.uniform(-noise, noise)
        z = oz - offset[1] + rng.uniform(-noise, noise)
        recs.append(_rec(24 + j, x, z, 0x2000046 + j))
    return recs


def test_subset_match_finds_translated_doors_and_nothing_else():
    recs = _room_with_doors(offset=(228.13, 291.25))
    hits = R.match_anchor_subset(recs, R.ROOM10_DOORS)
    assert hits and hits[0]["indices"] == (24, 25, 26, 27)
    assert hits[0]["subset_error"] < 0.01
    assert len(hits) == 1  # a translated copy is unambiguous among random clutter


def test_solve_offset_recovers_the_translation_with_noise():
    true = (228.13, 291.25)
    recs = _room_with_doors(offset=true, noise=0.3)
    solved = R.solve_offset(recs, (24, 25, 26, 27), R.ROOM10_DOORS)
    assert solved is not None
    assert solved["offset"] == pytest.approx(true, abs=0.5)
    assert solved["max_deviation"] < 0.6
    # the assignment is unique: the second-best permutation is off by >100 units
    assert set(solved["names"].values()) == {24, 25, 26, 27}


def test_solve_offset_rejects_a_non_translation():
    recs = _room_with_doors(offset=(228.13, 291.25))
    recs[24]["x"] += 40.0  # one door no longer explained by any constant offset
    assert R.solve_offset(recs, (24, 25, 26, 27), R.ROOM10_DOORS) is None


def test_world_of_and_record_at_round_trip():
    off = (228.13, 291.25)
    recs = [_rec(0, -34.5, -384.5, 0x2000049), _rec(1, 0.0, 0.0, 1)]
    assert R.world_of(recs[0], off) == pytest.approx((193.63, -93.25))
    hit = R.record_at(recs, 194.0, -93.0, off, tolerance=2.0)
    assert hit is not None and hit["index"] == 0
    assert R.record_at(recs, 500.0, 500.0, off) is None


@pytest.mark.skipif(not (os.path.exists(DISC) or os.path.exists(LOCAL_DISC)),
                    reason="owned PSO image not on this host")
def test_real_disc_room10_offset():
    from gbox.gcdisc import GCDisc
    disc = GCDisc(DISC if os.path.exists(DISC) else LOCAL_DISC)
    out = R.room_offset(disc, "map_city00_00o.dat")
    # the hand-off's expected solve: records 17/18/20/21, one constant translation
    assert out["indices"] == [17, 18, 20, 21]
    assert out["kinds"] == [0x2000049, 0x2000046, 0x2000047, 0x2000048]
    assert out["offset"] == pytest.approx((228.13, 291.25), abs=0.1)
    assert out["max_deviation"] < 0.6
    # the Guild door's record lands on its observed world position
    from gbox import pso_map_write as W
    recs = S.records(W.read_set(disc, "map_city00_00o.dat")[0])
    g = R.world_of(recs[out["names"]["Guild"]], out["offset"])
    assert g == pytest.approx(R.ROOM10_DOORS["Guild"], abs=1.0)


@pytest.mark.skipif(not (os.path.exists(DISC) or os.path.exists(LOCAL_DISC)),
                    reason="owned PSO image not on this host")
def test_real_disc_layout_variants_share_the_records():
    from gbox.gcdisc import GCDisc
    from gbox import pso_map_write as W
    disc = GCDisc(DISC if os.path.exists(DISC) else LOCAL_DISC)
    for name in ("map_city00_00o_c1.dat", "map_city00_00o_d.dat"):
        hits = R.match_anchor_subset(S.records(W.read_set(disc, name)[0]), R.ROOM10_DOORS)
        assert hits and hits[0]["subset_error"] < 1.0, name
