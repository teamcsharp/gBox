"""Gate-model (pure) tests: a room's forward affordances classify into the right
approach ORDER and walk-through target. See system/docs/pso-progression.md."""
from gbox import pso_coop_gates as G


def _gate(cls, x, z, room=10):
    return {"class": cls, "x": float(x), "z": float(z), "room": room, "kind": "gate"}


def test_switches_sort_before_doors_each_nearest_first():
    ents = [_gate("TObjDoor", -100, 0), _gate("TObjDoorKey", -50, 0),
            _gate("TLazerFenceSw", -200, 0), _gate("TOBarrierEnergy01", -300, 0)]
    rows = G.forward_candidates(ents, 10, 0, 0)
    assert [r[4] for r in rows] == ["switch", "switch", "door", "door"]
    assert [r[3]["class"] for r in rows] == [
        "TObjDoorKey", "TLazerFenceSw", "TObjDoor", "TOBarrierEnergy01"]


def test_a_cooled_affordance_is_skipped_and_other_rooms_are_the_fallback():
    ents = [_gate("TObjDoorKey", -50, 0, room=10), _gate("TObjDoor", 10, 0, room=11)]
    cooled = {("TObjDoorKey", -50.0, 0.0): 100.0}
    rows = G.forward_candidates(ents, 10, 0, 0, cooldown=cooled, now=0.0)
    # room 10's only affordance is cooled -> fall back to the whole floor (room 11 door)
    assert len(rows) == 1 and rows[0][3]["class"] == "TObjDoor" and rows[0][4] == "door"


def test_non_gate_classes_and_warps_are_not_forward_affordances():
    ents = [_gate("TObjAreaWarpForest", 5, 0), _gate("TObjContainerItem", 6, 0),
            _gate("TObjEneMoja", 7, 0)]
    assert G.forward_candidates(ents, 10, 0, 0) == []


def test_through_point_overshoots_just_past_the_gate_along_the_approach():
    px, pz, gx, gz = 0.0, 0.0, 10.0, 0.0
    bx, bz = G.through_point(px, pz, gx, gz, overshoot=16.0)
    assert bx > gx and abs(bz) < 1e-6                     # beyond the gate, same bearing
    assert abs((bx - gx) - 16.0) < 1e-6
    assert G.through_point(5, 5, 5, 5) == (5, 5)          # degenerate: no direction, no overshoot
