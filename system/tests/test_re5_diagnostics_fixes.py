"""RE5 Mercenaries fixes from the 2026-10-26 per-round diagnostics (docs/evidence/mercs-diagnostics-2026-10-26.md): the
laser sight found past the 64th FX unit (and never another unit's fields), the First Aid Spray no gun, the laserless
close-threat blast, heals before the killing blow, every hit a round-map event and a lesson, every round audited."""
import math

import pytest

from gbox.mercs import ballistics as Bal
from gbox.mercs import impact_lessons as IL
from gbox.mercs.round_audit import RoundAudit
from gbox.mercs.round_map import RoundTrace
from gbox.mercs.titles import re5_combat as C, re5_ps3 as R, re5_weapons as W
from tests.test_re5_combat import PL, FakeMem, snap, world
from tests.test_re5_laserless_fire import scene

SU, FIRST, OTHER_VT = 0x30900000, 0x31000000, 0x015B0000


def fx_line(n_before, with_laser=True):
    """sUnit's FX line: n_before other effect units (blood, flashes ...) ahead of the uLaserSight, or none at all."""
    m = FakeMem()
    m.put(R.S_UNIT, ">I", SU)
    m.put(SU + R.UNIT_LINES + R.LINE_STRIDE * R.FX_LINE + R.LINE_FIRST, ">I", FIRST)
    addr = FIRST
    for _ in range(n_before):
        m.put(addr, ">I", OTHER_VT)
        m.put(addr + R.LASER_FROM, ">3f", 1.0, 2.0, 3.0)               # never to be read as the ray
        m.put(addr + R.LASER_AT, ">3f", 4.0, 5.0, 6.0)
        m.put(addr + R.UNIT_NEXT, ">I", addr + 0x400)
        addr += 0x400
    if with_laser:
        m.put(addr, ">I", R.LASER_VT)
        m.put(addr + R.LASER_FROM, ">3f", 0.0, 149.0, 46.0)
        m.put(addr + R.LASER_AT, ">3f", 0.0, 110.0, 1000.0)
    m.put(addr + R.UNIT_NEXT, ">I", 0)
    return m


def test_the_laser_is_found_far_down_a_busy_fx_line():
    """The walk stopped at the 64th unit: in a round whose FX line had grown, the laser was never found ("laserless" with
    a laser gun: 16:36 Missile Area 1 hit in 18 shots, "no ray at the trigger" 17)."""
    m = fx_line(200)
    ray = R.laser(m)
    assert ray == {"from": (0.0, 149.0, 46.0), "at": (0.0, 110.0, 1000.0)}


def test_a_walk_that_ends_without_the_laser_never_returns_another_units_fields(monkeypatch):
    """The old walk cached the unit it stopped on - not a laser - and read its fields as the ray (garbage aims). Now: no
    ray; and the failed walk is not repeated every tick (LASER_RESCAN_S)."""
    clock = [100.0]
    monkeypatch.setattr(R.time, "monotonic", lambda: clock[0])
    m = fx_line(R.LASER_WALK_MAX + 5, with_laser=False)
    assert R.laser(m) is None
    reads = []
    rd = m.rd
    m.rd = lambda a, n: reads.append(a) or rd(a, n)
    clock[0] += R.LASER_RESCAN_S / 2
    assert R.laser(m) is None and reads == []                           # inside the rescan interval: no walk
    clock[0] += R.LASER_RESCAN_S
    assert R.laser(m) is None and len(reads) > R.LASER_WALK_MAX          # walked again, still no laser


def test_a_first_aid_spray_in_hand_is_no_gun_and_its_use_is_no_shot(tmp_path):
    """The spray is {id 0x304, type 3, item 4}: read as item 4 it was the Ithaca M37 and its use a missed "shot" (85 shot
    rows as 0x4 today, 6 of 45 hits)."""
    m = world(rounds=1)
    m.put(PL + C.P_INV + 3 * C.INV_SLOT + C.INV_ID, ">I", 0x0304)        # the spray in hand
    combat = C.Combat(m, {}, learn_dir=tmp_path, lessons=lambda e: None)
    s = snap(m)
    assert combat._in_hand(s, PL) == (None, None) and combat.item_in_hand   # from RAM
    s["inventory"] = [{"slot": 3, "id": 0x304, "type": 3, "item": 4, "rounds": 1, "hand": True}]
    assert combat._in_hand(s, PL) == (None, None) and combat.item_in_hand   # from the snapshot
    combat.observe(s, 1.0)
    used = dict(s, inventory=[dict(s["inventory"][0], rounds=0)])
    combat.observe(used, 1.1)
    assert combat.stats["shots"] == 0
    s["inventory"] = [{"slot": 3, "id": 0x112, "type": 1, "item": 0x12, "rounds": 9, "hand": True}]
    assert combat._in_hand(s, PL) == (0x12, 9) and not combat.item_in_hand


def test_a_laserless_gun_blasts_a_close_threat_instead_of_lowering_to_turn(tmp_path):
    """Operator 2026-10-26: "the laserless path must fire while turning toward a target within ~3 m instead of lowering
    the gun". Inside LASERLESS_BLAST_R and LASERLESS_BLAST_CONE: the gun stays up, the trigger down, the aim correcting."""
    memory, state = scene(0x1A)
    a = math.radians(50)
    state["enemies"][0]["pos"] = (250.0 * math.sin(a), 0.0, 250.0 * math.cos(a))
    combat = C.Combat(memory, {}, learn_dir=tmp_path, lessons=lambda e: None)
    keys = combat.tick(dict(state), state["player"], state["enemies"][0], 1.0)["hold"]
    assert {"l1", "r1"} <= keys and keys & {"rleft", "rright"}
    assert combat.stats["fire_gate"] == C.BLAST_GATE_LASERLESS and "lower weapon" not in combat.stats["combat"]
    assert combat.stats["laserless_blasts"] == 1


def test_a_laserless_gun_still_turns_gun_down_for_one_far_off_its_heading(tmp_path):
    memory, state = scene(0x1A)
    a = math.radians(80)                                                 # outside the cone: the body turn is faster
    state["enemies"][0]["pos"] = (250.0 * math.sin(a), 0.0, 250.0 * math.cos(a))
    combat = C.Combat(memory, {}, learn_dir=tmp_path, lessons=lambda e: None)
    keys = combat.tick(dict(state), state["player"], state["enemies"][0], 1.0)["hold"]
    assert "r1" not in keys and "lower weapon" in combat.stats["combat"]


def test_a_gun_up_two_seconds_without_a_ray_is_laserless_and_a_ray_resets_it(tmp_path):
    combat = C.Combat(world(), {}, learn_dir=tmp_path)
    for k in range(50):
        combat._note_ray(0x12, False, True, k * 0.05)                    # 2.45 s up, no ray
    assert combat.laserless_now(0x12)
    combat._note_ray(0x12, True, True, 2.5)
    assert not combat.laserless_now(0x12) and combat.laserless_now(0x0F)   # the bow: always
    for k in range(50):
        combat._note_ray(0x12, False, False, 3.0 + k * 0.05)             # the gun down: not counted
    assert not combat.laserless_now(0x12)


def test_a_laserless_gun_gives_way_to_a_laser_gun_at_close_range_and_the_bow_keeps_its_range():
    bow = {"player": {"pos": (0.0, 0.0, 0.0)}, "enemies": [], "inventory": [
        {"slot": 0, "id": 0x10F, "item": 0x0F, "type": 1, "rounds": 5, "grid": 3, "hand": True},
        {"slot": 1, "id": 0x11A, "item": 0x1A, "type": 1, "rounds": 5, "grid": 1, "hand": False}]}
    assert W.best_quick_slot(bow, {"pos": (0.0, 0.0, 1000.0), "hp_max": 800}) is None    # the bow at 10 m
    assert W.best_quick_slot(bow, {"pos": (0.0, 0.0, 500.0), "hp_max": 800})["item"] == 0x1A   # at 5 m: a laser gun
    hand = {"player": {"pos": (0.0, 0.0, 0.0)}, "enemies": [], "inventory": [
        {"slot": 0, "id": 0x112, "item": 0x12, "type": 1, "rounds": 9, "grid": 3, "hand": True},
        {"slot": 1, "id": 0x102, "item": 0x02, "type": 1, "rounds": 9, "grid": 1, "hand": False}]}
    near = {"pos": (0.0, 0.0, 500.0), "hp_max": 800}
    assert W.best_quick_slot(hand, near) is None                          # two handguns: no reason to switch
    assert W.best_quick_slot(hand, near, laserless=True)["item"] == 0x02  # ... unless the one in hand shows no ray


def test_heals_start_before_the_killing_blow_and_the_stage_learns_its_heaviest_hit(tmp_path):
    """23 of today's 30 deaths came with a heal deferred, 14 from 1-3 HP: under HEAL_CRITICAL (now 25 %, one ordinary
    hit) the heal starts with Majini near; a stage whose hits are heavier raises its own threshold (impact_lessons)."""
    bot = R.Bot(learn_dir=tmp_path)
    bot.stats["stage"] = "Prison"
    p = {"ptr": 1, "pos": (0.0, 0.0, 0.0), "rot": 0.0, "hp": 300, "hp_max": 1000}
    near = {"ptr": 2, "slot": 0, "pos": (0.0, 0.0, 300.0), "hp": 800, "hp_max": 800}
    s = {"player": p, "enemies": [near]}
    assert not bot._heal_safe(p, s, 300, 1000) and "4 m at 30%" in bot.stats["heal_deferred"]
    assert bot._heal_safe(p, s, 220, 1000)                                # 22 %: heal now
    assert bot._heal_safe(p, {"player": p, "enemies": [dict(near, pos=(0.0, 0.0, 450.0))]}, 300, 1000)   # 4.5 m: room
    bot._trace = RoundTrace(None, "BLUS30491", "Prison", "r1", 400.0)
    boss = {"ptr": 9, "slot": 1, "pos": (0.0, 0.0, 400.0), "hp": 4000, "hp_max": 4000}
    bot._impact_watch({"player": dict(p, hp=1000), "enemies": [boss]})
    bot._impact_watch({"player": dict(p, hp=580), "enemies": [boss]})   # a 420 HP blow
    assert bot._heal_critical() == IL.HEAL_CRITICAL_MAX
    assert bot._heal_safe(p, s, 300, 1000)                                # this stage heals at 30 % now


def test_every_hit_he_takes_is_a_round_map_event_and_a_lesson(tmp_path):
    bot = R.Bot(learn_dir=tmp_path)
    bot.stats.update(stage="Village", phase="clear_nearby", combat="swinging round to him (gun down): +120 deg",
                     fire_gate="no line: hold fire", weapon="uWp1a 5/5")
    bot._trace = RoundTrace(None, "BLUS30491", "Village", "r1", 400.0)
    p = {"ptr": 1, "pos": (0.0, 0.0, 0.0), "rot": 0.0, "hp": 1000, "hp_max": 1000}
    behind = {"ptr": 2, "slot": 0, "pos": (0.0, 0.0, -120.0), "hp": 800, "hp_max": 800}
    side = {"ptr": 3, "slot": 1, "pos": (300.0, 0.0, 0.0), "hp": 800, "hp_max": 800}
    s = {"player": p, "enemies": [behind, side]}
    bot._impact_watch(s)                                                  # the baseline
    bot._impact_watch(dict(s, player=dict(p, hp=840)))
    ev = bot._trace.events[-1]
    assert ev["kind"] == "hit" and ev["loss"] == 160 and ev["attack"] == "melee" and ev["dist"] == 120
    assert ev["facing"] == "behind" and ev["crowd_4m"] == 2 and ev["doing"].startswith("clear_nearby: swinging")
    assert ev["gate"] == "no line: hold fire" and ev["weapon"] == "uWp1a 5/5" and ev["boss"] is False
    assert bot.impacts.summary("Village")["melee"]["behind"] == 1 and bot.stats["impacts"] == 1
    bot._impact_watch(dict(s, player=dict(p, hp=1000)))                  # a heal is no hit
    bot._impact_watch(dict(s, player=dict(p, ptr=7, hp=500)))            # a new player: a new baseline, no hit
    assert sum(e["kind"] == "hit" for e in bot._trace.events) == 1


def test_a_round_blind_without_its_laser_is_flagged_by_the_audit():
    trace = RoundTrace(None, "BLUS30491", "Prison", "r1", 400.0)
    audit, stats = RoundAudit("BLUS30491"), {"character": "Chris (Warrior)", "player_damage_events": 3}
    audit.start(stats)
    for k in range(60):
        fb = "laserless gun camera direction; no projectile ray" if k % 4 else "ray direction"
        trace.add(k * 0.25, k * 50.0, 0.0, 0.0, {"phase": "clear_nearby", "aim_feedback": fb, "weapon": "uWp1d 30/30"})
    trace.auditor = lambda summary, tr: audit.finish(summary, tr, stats)
    stats["player_damage_events"] = 5
    a = trace.finish()["audit"]
    assert any(p.startswith("no laser ray for 75% of the gun-up time (uWp1d") for p in a["problems"])
    assert a["metrics"]["laserless_share"] == 0.75 and a["metrics"]["hits_taken"] == 2 and a["verdict"] == "problems"


def test_both_close_threat_blasts_stay_out_of_the_calibration(tmp_path):
    cal = Bal.Calibration(tmp_path)
    rec = {"result": "miss", "dist": 200, "character": "x", "wid": 0x12, "gate": C.BLAST_GATE_LASERLESS}
    cal.observe(rec)
    assert not cal.dirty and Bal.blasted(rec) and Bal.blasted({"gate": Bal.BLAST_GATE})
    cal.observe(dict(rec, gate="line to him"))
    assert cal.dirty
