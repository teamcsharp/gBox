"""RE4 Mercenaries threats from RAM (gbox.re4_threats): attacking Ganados, thrown weapons, shots scored by health."""
import json
import math
import struct
from pathlib import Path

import pytest

from gbox import re4_threats as T

STRIDE = 0xDE0
FIXTURES = Path(__file__).parent / "fixtures" / "re4_threats.json"


class RecordedMem:
    """One recorded moment of a live round (tests/fixtures/re4_threats.json, cut from a recording on the Spark): the
    globals snapshot() reads, the EmMgr table with Leon and the slots of interest (every other slot empty), and the
    motion event tables those slots point at."""

    def __init__(self, case, sample):
        self.regions = [(int(a, 16), bytes.fromhex(h)) for a, h in sample["regions"].items()]
        table = bytearray(case["count"] * case["stride"])
        for k, h in sample["slots"].items():
            o = int(k) * case["stride"]
            table[o:o + case["stride"]] = bytes.fromhex(h)
        self.regions.append((case["base"], bytes(table)))
        self.regions += [(int(a, 16), bytes.fromhex(h)) for a, h in sample["evtabs"].items()]

    def rd(self, a, n):
        for base, b in self.regions:
            if base <= a and a + n <= base + len(b):
                return b[a - base:a - base + n]
        return bytes(n)


def recorded():
    return json.loads(FIXTURES.read_text())["cases"] if FIXTURES.is_file() else []


@pytest.mark.parametrize("case", recorded(), ids=lambda c: c["name"])
def test_recorded_rounds_rank_the_threat_the_game_was_running(case):
    from gbox import re4_merc_bot as B
    tr, out = None, []
    for sample in case["samples"]:
        m = RecordedMem(case, sample)
        tr = tr or T.Tracker(m)
        tr.m = m
        out = tr.update(B.snapshot(m), sample["t"])
    want = case["expect"]
    top = out[0] if out else None
    assert top is not None and top.kind == want["kind"], [(t.slot, t.kind, round(t.eta, 2)) for t in out[:4]]
    if "slot" in want:
        assert top.slot == want["slot"]
    if "eta" in want:
        assert abs(top.eta - want["eta"]) <= want.get("eta_tol", 0.1)
    for k in want.get("absent", []):
        assert k not in [t.slot for t in out]


def slot(r=(1, 0, 0, 0), ev=0, frame=0.0, frames=60, speed=1.0, em_id=0x16, pos=(0.0, 0.0, 0.0), flags=0x601):
    b = bytearray(STRIDE)
    struct.pack_into(">I", b, 0, flags)
    struct.pack_into(">3f", b, 0x94, *pos)
    b[T.EM_ROUTINE:T.EM_ROUTINE + 4] = bytes(r)
    b[T.EM_ID] = em_id
    struct.pack_into(">I", b, T.EM_EVENTS, ev)
    struct.pack_into(">fHxxf", b, T.EM_FRAME, frame, frames, speed)
    return b


def test_em_fields_reads_the_routine_and_the_motion_events():
    d = bytes(slot()) + bytes(slot(r=(1, 0x26, 1, 0), ev=T.EV_HIT | T.EV_SWING, frame=12.5, frames=40))
    e = T.em_fields(d, STRIDE)
    assert e["r"] == (1, 0x26, 1, 0) and e["ev"] == 0x21 and e["frame"] == 12.5 and e["frames"] == 40


def test_thrown_weapons_are_their_own_em_slots():
    d = bytes(slot()) + bytes(slot(em_id=T.THROWN_ID, pos=(10.0, 1200.0, 30.0))) + bytes(slot(em_id=0x16))
    out = T.thrown(d, 3, STRIDE)
    assert [t["slot"] for t in out] == [1] and out[0]["pos"] == (10.0, 1200.0, 30.0)
    done = bytes(slot()) + bytes(slot(em_id=T.THROWN_ID, r=(2, 0, 0, 0)))      # landed / broken: not in the air
    assert T.thrown(done, 2, STRIDE) == []


def ganado(k, pos, r=(1, 0, 0, 0), hp=1000, ev=0):
    return {"slot": k, "pos": pos, "hp": hp, "hp_max": 1000, "r": r, "ev": ev, "frame": 0.0, "frames": 60, "fspeed": 1.0}


def snap(enemies, thrown=(), leon=(0.0, 0.0, 0.0), rot=0.0):
    return {"player": {"pos": leon, "rot": rot, "pitch": 0.0, "r": (0, 0, 0, 0)}, "enemies": list(enemies),
            "thrown": list(thrown)}


def test_an_attacking_ganado_comes_before_a_nearer_one_that_only_walks():
    tr = T.Tracker()
    s = snap([ganado(1, (0.0, 0.0, 500.0)), ganado(2, (900.0, 0.0, 0.0), r=(1, 0x26, 0, 0))])
    out = tr.update(s, 0.0)
    assert out[0].slot == 2 and out[0].kind == "swing" and out[1].kind == "near"


def test_the_attack_closest_to_landing_is_first_and_hit_frames_are_now():
    tr = T.Tracker()
    tr.update(snap([ganado(1, (0.0, 0.0, 600.0), r=(1, 0x26, 0, 0))]), 0.0)
    s = snap([ganado(1, (0.0, 0.0, 600.0), r=(1, 0x26, 1, 0)), ganado(2, (400.0, 0.0, 0.0), r=(1, 0x29, 0, 0))])
    out = tr.update(s, 0.5)                          # slot 1 started 0.5 s ago, slot 2 just now
    assert [t.slot for t in out[:2]] == [1, 2] and out[0].eta < out[1].eta
    s["enemies"][1]["ev"] = T.EV_HIT                 # slot 2's hit frames are on
    assert tr.update(s, 0.55)[0].slot == 2 and tr.update(s, 0.6)[0].eta == 0.0


def test_dying_ganados_are_not_targets():
    tr = T.Tracker()
    out = tr.update(snap([ganado(1, (0.0, 0.0, 300.0), r=(3, 0, 0, 0)), ganado(2, (0.0, 0.0, 400.0), hp=0),
                          ganado(3, (0.0, 0.0, 2000.0))]), 0.0)
    assert [t.slot for t in out] == [3]
    assert T.dying({"hp": -5}) and T.dying({"hp": 10, "r": (0xFF, 0, 0, 0)}) and not T.dying({"hp": 10, "r": (2, 1, 0, 0)})


def test_a_kill_during_his_attack_is_an_attack_prevented():
    tr = T.Tracker()
    tr.update(snap([ganado(1, (0.0, 0.0, 600.0), r=(1, 0x27, 0, 0))]), 0.0)
    tr.update(snap([ganado(1, (0.0, 0.0, 600.0), r=(3, 1, 0, 0), hp=0)]), 0.3)
    assert tr.stats["attacks_seen"] == 1 and tr.stats["prevented"] == 1


def test_a_thrown_weapon_flying_at_leon_is_a_threat_one_flying_past_is_not():
    tr = T.Tracker()
    axe = {"slot": 9, "pos": (0.0, 1400.0, 3000.0), "r": (1, 0, 0, 0)}
    tr.update(snap([], [axe]), 0.0)
    axe2 = dict(axe, pos=(0.0, 1400.0, 2700.0))              # 3000 units/s straight at him
    out = tr.update(snap([], [axe2]), 0.1)
    assert out and out[0].kind == "thrown" and 0.7 < out[0].eta < 1.0
    assert out[0].pos[2] < 2700.0                            # aimed where it will be at the shot
    past = {"slot": 10, "pos": (3000.0, 1400.0, 3000.0), "r": (1, 0, 0, 0)}
    tr2 = T.Tracker()
    tr2.update(snap([], [past]), 0.0)
    assert tr2.update(snap([], [dict(past, pos=(3000.0, 1400.0, 2700.0))]), 0.1) == []   # 3000 to his side


def test_shots_are_scored_by_any_ganado_losing_health():
    sh = T.Shots()
    en = [ganado(1, (0, 0, 900)), ganado(2, (0, 0, 1800))]
    sh.update(en, 0.0)
    assert sh.press(0.1) and not sh.press(0.5)               # the gun's own rate: one shot per 35 frames
    en[1] = dict(en[1], hp=-200, r=(3, 0, 0, 0))              # the one behind died: the Hand Cannon went through
    sh.update(en, 0.2)
    assert sh.stats["hits"] == 1 and sh.stats["kills"] == 1
    assert sh.press(1.4)
    sh.update(en, 1.5)
    sh.update(en, 2.0)                                        # nothing fell within HIT_S: a miss
    assert sh.stats["misses"] == 1 and sh.stats["accuracy"] == 0.5
