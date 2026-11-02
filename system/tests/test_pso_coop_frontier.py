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


# --- Verified native stage-flag array (reverse-engineered from 0x80229220) ----

def test_stage_flag_locus_is_msb_first_32_bytes_per_group():
    # Forest 1 = group/floor 1; group base = 0x80515CC8 + 32 = 0x80515CE8.
    assert G.stage_flag_locus(1, 6) == (0x80515CE8, 0x02)      # byte 0, bit 0x80>>6
    assert G.stage_flag_locus(1, 7) == (0x80515CE8, 0x01)      # byte 0, bit 0x80>>7
    assert G.stage_flag_locus(1, 10) == (0x80515CE9, 0x20)     # byte 1, bit 0x80>>2
    assert G.stage_flag_locus(0, 0) == (0x80515CC8, 0x80)      # town group, item 0, MSB
    assert G.stage_flag_locus(1, 256) is None                  # item out of range
    assert G.stage_flag_locus(18, 0) is None                   # group out of range (floors 0..17)


def test_forward_gate_flag_indices_takes_room_switches_and_barriers():
    ents = [{"class": "TObjDoorKey", "room": 10, "flag_index": 7},
            {"class": "TObjDoorKey", "room": 10, "flag_index": 6},
            {"class": "TObjDoorKey", "room": 99, "flag_index": 3},        # other room: ignored
            {"class": "TOBarrierEnergy01", "room": 11, "flag_index": 10},
            {"class": "TObjContainerItem", "room": 10, "flag_index": 5}]  # not a gate: ignored
    assert G.forward_gate_flag_indices(ents, 10) == [6, 7, 10]


def test_recalled_forward_flags_validates_floor_and_range():
    from gbox.pso_knowledge import KnowledgeStore, recalled_forward_flags
    s = KnowledgeStore()
    s.remember("fp1", gate="forced_flags", floor=1, forward_flags=[6, 7, 10])
    assert recalled_forward_flags(s, "fp1", 1) == [6, 7, 10]
    assert recalled_forward_flags(s, "fp1", 2) is None          # floor (flag group) mismatch -> no recall
    assert recalled_forward_flags(s, "unknown", 1) is None      # stale/unknown fingerprint -> fresh
    s.remember("bad", gate="forced_flags", floor=1, forward_flags=[6, 999])
    assert recalled_forward_flags(s, "bad", 1) is None          # out-of-range flag -> reject
