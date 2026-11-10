"""gbox.pso_offset: solving a set's local -> world offset, checked against the value round 49 proved."""
from pathlib import Path

import pytest

from gbox import pso_offset as O

DISC = Path(r"D:\gBox\cache\436e0bb84d5337d1\Phantasy Star Online Episode I & II Plus (USA).gcz")


def recs(*points):
    return [{"x": x, "z": z} for x, z in points]


def ents(*points):
    return [{"x": x, "z": z} for x, z in points]


def test_an_exact_translation_is_found_and_scores_every_record():
    r = recs((0.0, 0.0), (10.0, 5.0), (-20.0, 7.0))
    e = ents((228.0, 291.0), (238.0, 296.0), (208.0, 298.0))
    got = O.solve(r, e)
    assert got["offset"] == (228.0, 291.0)
    assert (got["matched"], got["total"], got["fraction"]) == (3, 3, 1.0)


def test_a_partial_match_still_solves_the_common_translation():
    """Real sets have records with no entity (cameras, spawns); the plurality must still win."""
    r = recs((0.0, 0.0), (10.0, 5.0), (-20.0, 7.0), (500.0, 500.0))
    e = ents((228.0, 291.0), (238.0, 296.0), (208.0, 298.0))
    got = O.solve(r, e)
    assert got["offset"] == (228.0, 291.0)
    assert got["matched"] == 3 and got["fraction"] == 0.75


def test_a_useless_offset_raises_rather_than_returning_a_number():
    r = recs((0.0, 0.0), (10.0, 5.0), (-20.0, 7.0), (900.0, 900.0))
    e = ents((1e6, 1e6), (2e6, 2e6))
    with pytest.raises(O.OffsetError, match="matched only"):
        O.solve(r, e, min_fraction=0.9)


def test_empty_input_is_refused():
    with pytest.raises(O.OffsetError, match="at least one record"):
        O.solve([], ents((0.0, 0.0)))


@pytest.mark.skipif(not DISC.is_file(), reason="the disc is not on this machine")
def test_the_city_set_solves_to_the_offset_round_49_proved():
    """The self-check: run the solver blind on city00 against the lobby's live entities and see if it rediscovers
    (+228,+291) -- the constant that was measured from the spawn points and then confirmed by a door moving in game."""
    from gbox import gcdisc, pso_editor as E

    d = gcdisc.GCDisc(str(DISC))
    pl = E.placements(d, "map_city00_00o.dat")
    # the entity positions that round 46/49 matched: four doors, two spawns, four objects
    known = [(193.5, -93.5), (-165.0, 147.5), (185.0, 173.0), (254.0, 25.0),
             (229.0, 254.0), (231.0, 267.0), (360.0, 26.0), (0.0, -60.0), (0.0, -1730.0), (308.0, 211.0)]
    got = O.solve(pl["records"], ents(*known), tolerance=0.5)
    # the solver reads the record's own float, so it lands within a hundredth of the round number rather than exactly on it
    assert abs(got["offset"][0] - 228.0) < 0.05 and abs(got["offset"][1] - 291.0) < 0.05, got["offset"]
    assert got["matched"] >= 10
