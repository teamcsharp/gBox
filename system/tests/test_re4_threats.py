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
    d = bytes(slot()) + bytes(slot(em_id=T.THROWN_ID, r=(1, 6, 0, 0), pos=(10.0, 1200.0, 30.0))) + bytes(slot(em_id=0x16))
    out = T.thrown(d, 3, STRIDE)
    assert [t["slot"] for t in out] == [1] and out[0]["pos"] == (10.0, 1200.0, 30.0)
    for r in ((1, 0, 1, 0), (1, 3, 0, 0), (2, 0, 0, 0)):                    # in his hand, on the ground, broken
        assert T.thrown(bytes(slot()) + bytes(slot(em_id=T.THROWN_ID, r=r)), 2, STRIDE) == []


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


def test_a_ganado_with_boss_health_is_the_stage_boss_a_chainsaw_man_in_the_village_and_the_waterworld():
    # the disc's enemy set lists (profiles/gamedata/re4_r400_navmap.json / re4_r404_navmap.json): Dr. Salvador 6500 against
    # 1200-1800 for the Village crowd, the Waterworld's sisters 3500 / 5000 against 400-1000 - the em id / type bytes are
    # the crowd's own (0x16 types 0xb / 0xc; 0x20 type 0x16), so the full health is what names a boss
    assert T.boss({"hp_max": 6500}, 0x400) == "chainsaw" and T.boss({"hp_max": 3500}, 0x404) == "chainsaw"
    assert T.boss({"hp_max": 5000}, 0x402) == "boss" and T.boss({"hp_max": 4000}, 0x403) == "boss"   # Garrador, J.J.
    assert T.boss({"hp_max": 1800}, 0x400) == "" and T.boss({"hp_max": None}, 0x400) == "" and T.boss({}, 0x400) == ""
    assert T.boss({"hp_max": 6500}, None) == "chainsaw"                     # an unknown stage: the lethal reading
    assert T.BOSS_HP > 1800 and T.BOSS_HP <= 3500                           # between the strongest Ganado and the weakest boss


def test_a_boss_on_his_feet_is_a_threat_before_he_swings_and_every_boss_seen_is_kept():
    tr = T.Tracker()
    salvador = dict(ganado(2, (0.0, 0.0, 4000.0)), hp=6500, hp_max=6500, id=0x16, type=0xb)
    s = snap([ganado(1, (0.0, 0.0, 2500.0)), salvador])
    s["room"] = 0x400
    out = tr.update(s, 0.0)
    assert out[0].slot == 2 and out[0].kind == "chainsaw" and out[0].boss == "chainsaw" and out[0].lethal
    assert abs(out[0].eta - (T.CHAINSAW_SWING_S + 2500.0 / T.CLOSE_SPEED)) < 0.01   # closes to his reach, then the saw
    assert out[1].kind == "near" and not out[1].boss
    assert tr.stats["bosses_seen"] == 1 and list(tr.bosses.values())[0] == {"slot": 2, "id": 0x16, "type": 0xb, "hp_max": 6500,
                                                                           "kind": "chainsaw", "room": 0x400, "at": 0.0}
    s["enemies"][1] = dict(salvador, pos=(0.0, 0.0, 1000.0), r=(1, 0x26, 1, 0))   # mid-swing in reach: the swing's own
    t = next(x for x in tr.update(s, 0.1) if x.slot == 2)                        # timing, still a boss
    assert t.kind == "swing" and t.boss == "chainsaw" and t.lethal
    s["enemies"][1] = dict(salvador, r=(2, 1, 0, 0))                        # knocked down: not coming, still flagged
    t = next(x for x in tr.update(s, 0.2) if x.slot == 2)
    assert t.kind == "down" and t.boss == "chainsaw"
    s["room"] = 0x402                                                       # the Castle: a Garrador, no eta of his own
    t = next(x for x in tr.update(dict(s, enemies=[salvador]), 0.3) if x.slot == 2)
    assert t.kind == "boss" and t.boss == "boss" and not t.lethal and t.eta == math.inf
    assert tr.stats["bosses_seen"] == 1                                     # the same slot / id / type / health: once


def test_the_attack_landing_when_leon_is_hit_is_remembered_for_the_death_cause():
    tr = T.Tracker()
    s = snap([ganado(1, (0.0, 0.0, 700.0), r=(1, 0x26, 1, 0), ev=T.EV_HIT), ganado(2, (0.0, 0.0, 3000.0))])
    tr.update(s, 0.0)
    assert tr.last_hit is None
    tr.update(dict(s, player=dict(s["player"], r=(1, 0, 1, 0))), 0.1)      # Leon's routine 1: hit
    h = tr.last_hit
    assert h["slot"] == 1 and h["kind"] == "swing" and h["dist"] == 700 and h["hp_max"] == 1000 and h["eta"] == 0.0
    assert not h["boss"] and h["at"] == 0.1 and tr.stats["landed"] == 0     # (landed is counted when the swing ends)
    assert T.hit_record(tr.update(dict(s, player=dict(s["player"], r=(1, 0, 1, 0))), 0.2)[0], 0.2)["slot"] == 1


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
