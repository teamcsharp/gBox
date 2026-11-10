"""The universal Mercenaries fight (gbox.mercs.core.combat; operator 2026-11-10: "I want the same aimbot I am critiquing
in RE4 to improve across 5 and 6 despite their differences"): the five shared components on their own, each title's
profile, and what each title gained through them (RE4: who hurt him, the body profiles, the not-in-control detector,
the idle guard; RE5: the not-in-control detector, the boss / dangerous band; RE6: all of them) - and the flags that
put each title back as it was."""
import math
import types

import pytest

from gbox.mercs.core import combat as C
from gbox.mercs.titles import re4_switch as R4
from gbox.mercs.titles import re5_switch as R5
from gbox.mercs.titles import re6_switch as R6

P = C.TitleProfile(title="test")


# --- (a) bodies ------------------------------------------------------------------------------------------------------
def test_a_class_has_its_own_body_by_row_or_by_kind_and_the_rest_stand():
    t = C.BodyTable(default=C.HUMAN, classes={"dogcls": "dog", "own": C.Body(90.0, 60.0, 10.0, 80.0, 40.0)})
    assert t.body({"class": "dogcls"}) is C.KIND_BODIES["dog"] and t.low({"class": "dogcls"})
    assert t.body({"class": "own"}).chest == 60.0
    assert t.body({"class": "uEm10"}) is C.HUMAN and not t.low({"class": "uEm10"})
    assert t.body(None) is C.HUMAN and t.body({"class": ["unhashable"]}) is C.HUMAN


def test_the_hit_tests_take_the_body():
    foot = (0.0, 0.0, 200.0)
    crawler = C.KIND_BODIES["crawler"]
    assert C.dot_on((0.0, 10.0, 200.0), foot, crawler) == "body" and C.dot_on((0.0, 45.0, 200.0), foot, crawler) == "head"
    assert C.dot_on((0.0, 10.0, 200.0), foot) is None, "a man's body: the dot at his ankles is under the hit zone"
    assert C.dot_on((0.0, 160.0, 200.0), foot) == "head"
    origin = (0.0, 140.0, 0.0)
    past = (0.0, 30.0 - 110.0 * 0.3, 260.0)                             # down through his back and on
    assert C.through(origin, past, foot, crawler) and not C.through(origin, (0.0, 140.0, 400.0), foot, crawler)
    assert C.line_hits(origin, (0.0, 120.0, 100.0), foot, 500.0)        # down the line into a man's chest
    assert C.segment_hits(origin, (0.0, 110.0, 200.0), foot) and not C.segment_hits(origin, (0.0, 140.0, 50.0), foot)
    assert C.half_angle(C.HUMAN, 1000.0) == pytest.approx(math.atan2(36.0, 1000.0))
    assert C.scaled(C.HUMAN, 10.0).r == 360.0 and C.scaled(C.HUMAN, 1.0) is C.HUMAN


def test_re5s_low_bodies_are_the_universal_kinds_through_the_shared_table(monkeypatch):
    assert R5.LOW_BODIES["uEm32"] is C.KIND_BODIES["crawler"] and R5.LOW_BODIES["uEm0b"] is C.KIND_BODIES["dog"]
    assert R5.Body is C.Body and R5.body({"class": "uEm32"}) is C.KIND_BODIES["crawler"]
    assert R5.body({"class": "uEm10"}) is R5.HUMAN, "a standing Majini: the same object the guards compare against"
    monkeypatch.setattr(R5, "UNIVERSAL_CORE", False)
    assert R5.body({"class": "uEm32"}) is C.KIND_BODIES["crawler"], "the rollback reads the same table"


def test_re6_aims_and_hit_tests_a_low_class_at_its_own_height(monkeypatch):
    low = {"ptr": 1, "pos": (0.0, 0.0, 300.0), "class": "uEm6000"}
    man = {"ptr": 2, "pos": (0.0, 0.0, 300.0), "class": "uEm5200"}
    me = (0.0, 0.0, 0.0)
    assert R6.aim_point(man, me)[1] == R6.CHEST_H and R6.aim_point(low, me)[1] == R6.CHEST_H, "no row: a man's"
    monkeypatch.setattr(R6, "BODY_CLASSES", {"uEm6000": "crawler"})
    assert R6.aim_point(low, me)[1] == C.KIND_BODIES["crawler"].chest and R6.aim_point(man, me)[1] == R6.CHEST_H
    origin, flank = (0.0, 140.0, 0.0), (50.0, 20.0, 300.0)                 # low, half a metre to his side
    assert R6.segment_hits(origin, flank, low["pos"], R6.body(low))
    assert not R6.segment_hits(origin, flank, man["pos"], R6.body(man)), "a man is 36 cm wide, a crawler 60"
    monkeypatch.setattr(R6, "UNIVERSAL_CORE", False)
    assert R6.aim_point(low, me)[1] == R6.CHEST_H, "the rollback: every zombie's chest"


def test_re6s_shared_hit_tests_answer_as_its_own_did_for_a_standing_zombie(monkeypatch):
    foot, origin = (40.0, 0.0, 600.0), (0.0, 150.0, 0.0)
    pts = [(x, y, z) for x in (0.0, 30.0, 40.0, 70.0) for y in (20.0, 40.0, 100.0, 160.0, 175.0) for z in (560.0, 600.0)]
    new = [(R6.dot_on(d, foot), R6.segment_hits(origin, d, foot)) for d in pts]
    monkeypatch.setattr(R6, "UNIVERSAL_CORE", False)
    assert new == [(R6.dot_on(d, foot), R6.segment_hits(origin, d, foot)) for d in pts]


def test_re4s_shot_tolerance_is_the_target_classs_own_width(monkeypatch):
    err = math.radians(4.0)
    pos = (1000.0 * math.sin(err) * R4.MM_PER_CM, 0.0, 1000.0 * math.cos(err) * R4.MM_PER_CM)   # 10 m, 4 deg off
    snap = {"player": {"pos": (0.0, 0.0, 0.0), "rot": 0.0, "hp": 1000, "ptr": 1},
            "enemies": [{"pos": pos, "hp": 400, "ptr": 100, "class": 0xAE7050}]}
    b = R4.Bot(stats={}, director=False)
    b.tick(snap, now=0.0)
    assert b.tick(snap, now=R4.AIM_READY_S + 0.1).get("tap") == R4.AIM_TURN["left"], "a Ganado's width: a nudge"
    monkeypatch.setattr(R4, "BODY_CLASSES", {0xAE7050: C.Body(170.0, 115.0, 45.0, 150.0, 90.0)})
    wide = R4.Bot(stats={}, director=False)
    wide.tick(snap, now=0.0)
    assert wide.tick(snap, now=R4.AIM_READY_S + 0.1).get("tap") == R4.FIRE_BTN, "a class 90 cm wide: the shot"


# --- (b) not in control ------------------------------------------------------------------------------------------------
def test_shots_with_no_effect_and_nothing_moving_him_page_the_scene():
    n, here = C.NotInControl({}), (0.0, 0.0, 0.0)
    assert n.check(P, 0.0, here, 0.0, shots=0) is None                 # the first read: where he is
    assert n.check(P, 4.0, here, 0.0, shots=9) is None                 # not long enough
    page = n.check(P, 5.0, here, 0.0, shots=9)
    assert page == C.Page("a", "fire", True) and n.stats["frozen_fire_spells"] == 1 == n.stats["frozen_spells"]
    assert n.check(P, 5.1, here, 0.0, shots=9) == C.Page(None, "fire", False), "taps paced page_tap_s"
    assert n.check(P, 5.25, here, 0.0, shots=9).tap == "a"
    assert n.check(P, 5.3, (10.0, 0.0, 0.0), 0.0, shots=9) is None, "he moved: in control"


def test_any_effect_or_any_facing_change_means_in_control():
    here = (0.0, 0.0, 0.0)
    n = C.NotInControl({})
    n.check(P, 0.0, here, (0.0, 0.2), shots=0, enemies=[{"ptr": 1, "hp": 300}])
    assert n.check(P, 5.5, here, (0.0, 0.2), shots=20, enemies=[{"ptr": 1, "hp": 250}]) is None, "his health fell"
    n2 = C.NotInControl({})
    n2.check(P, 0.0, here, 0.0, shots=0, kills=3)
    assert n2.check(P, 5.5, here, 0.0, shots=20, kills=4) is None, "a kill"
    n3 = C.NotInControl({})
    n3.check(P, 0.0, here, (0.0, 0.2), shots=0)
    assert n3.check(P, 5.5, here, (0.0, 0.25), shots=20) is None, "the aim's pitch moved"
    n4 = C.NotInControl({})
    n4.check(P, 0.0, here, 0.0, shots=0)
    assert n4.check(P, 5.5, here, 0.0, shots=20, last_hit_at=2.0) is None, "a scored hit"


def test_the_trigger_held_counts_the_units_convert_and_a_near_enemy_holds_the_page():
    here = (0.0, 0.0, 0.0)
    held = C.TitleProfile(title="t", no_effect_trigger_s=4.0, page_clear_cm=150.0)
    n = C.NotInControl({})
    n.check(held, 0.0, here, 0.0, shots=1, trigger_s=0.0)
    assert n.check(held, 5.5, here, 0.0, shots=1, trigger_s=4.5, nearest_cm=100.0) is None, "one at arm's length"
    assert n.check(held, 5.6, here, 0.0, shots=1, trigger_s=4.6, nearest_cm=400.0).tap == "a", "one pull, held"
    mm = C.TitleProfile(title="t", units_per_cm=10.0)
    n2 = C.NotInControl({})
    n2.check(mm, 0.0, here, 0.0, shots=0)
    assert n2.check(mm, 5.5, (20.0, 0.0, 0.0), 0.0, shots=9).tap == "a", "20 mm is 2 cm: unmoved"


def test_a_spell_lasts_page_max_s_then_the_fight_goes_on_and_a_stuck_step_pages_too():
    here = (0.0, 0.0, 0.0)
    n = C.NotInControl({})
    n.check(P, 0.0, here, 0.0, shots=0)
    assert n.check(P, 5.0, here, 0.0, shots=9).fresh
    assert n.check(P, 5.0 + P.page_max_s, here, 0.0, shots=9) is None and n.stats["frozen_releases"] == 1
    assert n.check(P, 6.0 + P.page_max_s, here, 0.0, shots=12) is None, "the rules need their full time again"
    s = C.NotInControl({})
    s.check(P, 0.0, here, 0.0)
    assert s.check(P, 1.0, here, 0.0, stepped_at=0.5) is None                          # the step still running
    assert s.check(P, 1.4, here, 0.0, stepped_at=0.5) == C.Page("a", "step", True)


def test_re4_pages_a_frozen_scene_at_most_frozen_page_max_s_at_a_time():
    """test_re4_switch_fight's frozen scene, held on: the shared detector releases it after FROZEN_PAGE_MAX_S and the
    never-stand step finds it frozen again."""
    s = {"player": {"pos": (0.0, 0.0, 0.0), "rot": 0.0, "hp": 1000, "ptr": 1},
         "enemies": [{"pos": (5000.0, 0.0, 0.0), "hp": 400, "ptr": 100}]}
    b = R4.Bot(stats={}, director=False)
    b.tick(s, now=0.0)
    b.tick(s, now=R4.STAND_MAX_S + 0.1)                                 # the step
    t0 = R4.STAND_MAX_S + 0.2 + R4.STAND_STEP_S
    assert b.tick(s, now=t0).get("tap") == R4.FROZEN_KEY
    for k in range(1, int(R4.FROZEN_PAGE_MAX_S / 0.25)):
        b.tick(s, now=t0 + 0.25 * k)
    released = b.tick(s, now=t0 + R4.FROZEN_PAGE_MAX_S + 0.01)
    assert released.get("tap") != R4.FROZEN_KEY and b.doing != "frozen" and b.stats["frozen_releases"] == 1
    again = [b.tick(s, now=t0 + R4.FROZEN_PAGE_MAX_S + 0.1 * k).get("tap") for k in range(1, 30)]
    assert R4.FROZEN_KEY in again and b.stats["frozen_spells"] == 2


def test_re4_rollback_runs_the_first_frozen_rule(monkeypatch):
    monkeypatch.setattr(R4, "UNIVERSAL_CORE", False)
    b = R4.Bot(stats={}, director=False)
    p = {"pos": (0.0, 0.0, 0.0), "rot": 0.0}
    b._frozen(p, 10.0)
    b.stats["shots"] = 12
    assert b._frozen(p, 15.5) == {"hold": set(), "tap": R4.FROZEN_KEY} and "_uc_nic" not in b.__dict__


def re5_bot():
    clock = [0.0]
    return R5.Bot(stats={}, clock=lambda: clock[0]), clock


def re5_snap(hp=300, pos=(0.0, 0.0, 800.0)):
    p = {"ptr": 0x5D00001000, "pos": (0.0, 0.0, 0.0), "rot": 0.0, "hp": 1000, "hp_max": 1000, "motion": 0,
         "aim_pitch": None}
    return p, {"player": p, "enemies": [{"ptr": 10, "pos": pos, "hp": hp, "hp_max": 300, "class": "uEm10",
                                         "motion": 4}], "inventory": [], "kills": 0, "laser": {"up": False}}


def test_re5_pages_shots_that_do_nothing_with_nothing_moving_him():
    b, _ = re5_bot()
    p, s = re5_snap()
    assert b._frozen_core(p, s, 800.0, 0.0) is None
    b.stats["shots"] = 10
    assert b._frozen_core(p, s, 800.0, 3.0) is None
    assert b._frozen_core(p, s, 800.0, 5.5) == {"tap": "a"} and b.doing == "prompt"
    assert b.stats["frozen_fire_spells"] == 1
    hurt, _ = re5_bot()                                                   # his shots take the Majini's health: a fight
    hurt._frozen_core(p, s, 800.0, 0.0)
    hurt.stats["shots"] = 10
    hurt._frozen_core(p, re5_snap(hp=250)[1], 800.0, 2.0)
    assert hurt._frozen_core(p, re5_snap(hp=250)[1], 800.0, 5.5) is None
    held, _ = re5_bot()                                                   # one pull, the trigger held 4.5 s
    held._frozen_core(p, s, 800.0, 0.0)
    held.stats.update(shots=1, trigger_s=4.5)
    assert held._frozen_core(p, s, 800.0, 5.5) == {"tap": "a"}
    near, _ = re5_bot()
    near._frozen_core(p, s, 100.0, 0.0)
    near.stats["shots"] = 10
    assert near._frozen_core(p, s, 100.0, 5.5) is None, "a Majini at arm's length: the held branch's, not a page"


def test_re5_s_full_tick_pages_a_scene_that_answers_nothing(monkeypatch):
    monkeypatch.setattr(R5, "PS3_BRAIN", False)
    monkeypatch.setattr(R5, "HEAL_ENABLED", False)
    monkeypatch.setattr(R5, "MINES", False)
    b, clock = re5_bot()
    p, s = re5_snap(pos=(0.0, 0.0, 3000.0))                               # 30 m off: nothing he does reaches it
    taps = []
    for k in range(140):
        clock[0] = 0.05 * k
        b.stats["shots"] = k // 4                                         # pulls that change nothing
        taps.append(b.tick(s).get("tap"))
    assert "a" in taps and b.stats["frozen_spells"] >= 1
    monkeypatch.setattr(R5, "UNIVERSAL_CORE", False)
    b2, clock2 = re5_bot()
    for k in range(140):
        clock2[0] = 0.05 * k
        b2.stats["shots"] = k // 4
        assert b2.tick(s).get("tap") != "a" or b2.doing != "prompt"
    assert not b2.stats.get("frozen_spells")


def test_re6_s_full_tick_pages_a_scene_that_answers_nothing(monkeypatch):
    from test_re6_switch import brain, round_guest
    bot, clock, snap = brain(round_guest(enemies=((0.0, 0.0, 3000.0, 700),)))   # one far off, never hurt
    bot.held = lambda p, now: False
    taps = []
    for k in range(160):
        clock[0] = 0.05 * k
        bot.stats["shots"] = k // 4                                       # shots that change nothing
        taps.append(bot.tick(snap).get("tap"))
    assert "a" in taps and bot.stats["frozen_spells"] >= 1 and bot.stats["acts"].get("frozen_page")
    monkeypatch.setattr(R6, "UNIVERSAL_CORE", False)
    b2, clock2, snap2 = brain(round_guest(enemies=((0.0, 0.0, 3000.0, 700),)))
    b2.held = lambda p, now: False
    for k in range(160):
        clock2[0] = 0.05 * k
        b2.stats["shots"] = k // 4
        b2.tick(snap2)
    assert not b2.stats.get("frozen_spells") and not (b2.stats.get("acts") or {}).get("frozen_page")


# --- (c) who hurt him --------------------------------------------------------------------------------------------------
def test_threats_normalize_the_titles_units_before_the_memory_reads_them(tmp_path):
    mm = C.TitleProfile(title="t", units_per_cm=10.0)
    th = C.Threats(mm, {}, path=tmp_path / "t.json")
    e, p = {"ptr": 5, "class": "g", "pos": (0.0, 0.0, 2000.0), "hp": 400}, {"ptr": 1, "pos": (0.0, 0.0, 0.0), "hp": 100}
    th.observe(1.0, p, [e])
    rec = th.observe(1.2, dict(p, hp=80), [e])
    assert rec["attacker"] == 5 and rec["dist_cm"] == 200, "2000 mm is 2 m: within the memory's reach"
    assert th.grudge(e) == 1 and th.stats["tm_hits_attributed"] == 1
    assert th.observe(1.4, dict(p, hp=60), [e]) is None, "a fall within hurt_gap_s of the last is the same hit"
    raw = C.Threats(C.TitleProfile(title="t"), {}, path=tmp_path / "u.json")
    raw.observe(1.0, p, [e])
    assert raw.observe(1.2, dict(p, hp=80), [e]) is None, "the same numbers read as cm: 20 m, nobody"


def learn_unstoppable(th, cls="big", motion="Charge", t0=1.0, dist=400.0):
    """One of `cls` begins `motion`, takes his shots during it and lands anyway."""
    e = lambda m, hp: {"ptr": 7, "class": cls, "motion": m, "pos": (0.0, 0.0, dist), "hp": hp}
    p = {"ptr": 1, "pos": (0.0, 0.0, 0.0), "hp": 1000}
    th.observe(t0, p, [e("Walk", 2000)])
    th.observe(t0 + 0.5, p, [e(motion, 2000)])
    th.observe(t0 + 1.0, p, [e(motion, 1700)])
    th.observe(t0 + 1.2, dict(p, hp=700), [e(motion, 1700)])
    return e


def test_a_learned_wind_up_comes_first_and_one_that_lands_through_his_shots_is_stepped_out_of(tmp_path):
    th = C.Threats(P, {}, path=tmp_path / "t.json")
    e = learn_unstoppable(th)
    charging, walking = e("Charge", 1700), e("Walk", 1700)
    assert th.learned(charging) and th.winding(charging) and not th.winding(walking)
    p = {"ptr": 1, "pos": (0.0, 0.0, 0.0), "hp": 700}
    calm = {"ptr": 8, "class": "small", "pos": (0.0, 0.0, 200.0), "hp": 300}
    got = th.priority(p, [calm, charging])
    assert got[0] is charging and got[1] == "windup"
    assert th.step_out(p, [calm, charging], 10.0) is charging and th.stats["lethal_backoffs"] == 1
    assert th.step_out(p, [calm, charging], 10.0 + P.lethal_backoff_max_s + 0.1) is None, "cornered: he fights it"
    assert th.step_out(p, [calm, walking], 12.0) is None


# --- (d) the target scorer ---------------------------------------------------------------------------------------------
def cand(key, d, err=0.0, dy=0.0, windup=False, grudge=0, reach=300.0, tier="normal", clear=None):
    return {"e": {"ptr": key}, "key": key, "d": d, "err": err, "dy": dy, "windup": windup, "grudge": grudge,
            "reach": reach, "tier": tier, "clear": clear}


def test_the_bands_survival_then_bosses_then_grudges_then_the_cheapest():
    cs = [cand(1, 300.0), cand(2, 900.0, grudge=1), cand(3, 1500.0, tier="dangerous"), cand(4, 250.0, windup=True)]
    assert [r[2]["key"] for r in C.rank(P, cs)] == [4, 3, 2, 1]
    assert C.priority(P, cs)[:2] == (cs[3], "windup")
    assert C.priority(P, cs[:3])[:2] == (cs[2], "dangerous")
    assert C.priority(P, cs[:2])[:2] == (cs[1], "grudge")
    assert C.priority(P, cs[:1]) is None, "nothing pressing: the title's own choice"


def test_a_boss_before_a_dangerous_one_by_the_weights_and_only_in_reach_on_his_level():
    boss, dang = cand(1, 1000.0, tier="boss"), cand(2, 600.0, tier="dangerous")
    assert C.priority(P, [boss, dang])[0] is boss, "1000 x 0.4 under 600 x 0.7"
    assert C.priority(P, [boss, cand(3, 500.0, tier="dangerous")])[0]["key"] == 3
    assert C.priority(P, [cand(1, 300.0, tier="boss", dy=400.0)]) is None, "off his level"
    assert C.priority(P, [cand(1, P.engage_cm + 10.0, tier="boss")]) is None, "out of reach"


def test_one_at_arms_length_is_never_left_for_a_boss_or_a_grudge_but_a_wind_up_still_comes_first():
    boss, grab = cand(1, 800.0, tier="boss"), cand(2, 100.0)
    got = C.priority(P, [boss, grab])
    assert got[0] is grab and got[1] == "grab"
    assert C.priority(P, [cand(3, 700.0, grudge=2), grab])[1] == "grab"
    wind = cand(4, 280.0, windup=True)
    assert C.priority(P, [wind, grab, boss])[:2] == (wind, "windup")


def test_the_rest_by_cost_with_the_current_one_kept_within_keep_x():
    near, front = cand(1, 400.0, err=2.5), cand(2, 500.0)
    assert C.cost(P, near) > C.cost(P, front) and C.pick(P, [near, front])[0] is front
    walled = cand(3, 200.0, clear=False)
    assert C.pick(P, [walled, front])[0] is front, "a wall in the way costs blocked_x"
    a, b = cand(1, 500.0), cand(2, 420.0)
    assert C.pick(P, [a, b], current=1)[0] is a and C.pick(P, [a, cand(2, 300.0)], current=1)[0]["key"] == 2


def test_candidates_read_the_rows_in_the_titles_units():
    mm = C.TitleProfile(title="t", units_per_cm=10.0, tier=C.hp_tier(dangerous_hp=2000))
    p = {"pos": (0.0, 0.0, 0.0), "rot": 0.0}
    rows = [{"ptr": 1, "pos": (3000.0, 500.0, 3000.0), "hp": 400, "hp_max": 3500}, {"ptr": 2, "pos": (1.0, 0, 1.0),
                                                                                   "hp": 0}]
    (c,) = C.candidates(mm, p, rows)
    assert c["d"] == pytest.approx(math.hypot(300.0, 300.0)) and c["dy"] == 50.0
    assert c["err"] == pytest.approx(math.pi / 4) and c["tier"] == "dangerous"


def test_the_tier_comes_from_enemy_identity_when_it_is_there_and_the_titles_own_read_beside_it(monkeypatch):
    fake = types.SimpleNamespace(tier=lambda title, cls: {"uEm20": "boss", "0xae7050": "dangerous"}.get(cls, "normal"))
    monkeypatch.setattr(C, "_identity", fake)
    t = C.identity_tier("X", fallback=C.hp_tier(boss_hp=3000, dangerous_hp=900))
    assert t({"class": "uEm20", "hp_max": 100}) == "boss"
    assert t({"class": 0xAE7050}) == "dangerous", "an int class is asked as hex too"
    assert t({"class": "uEm10", "hp_max": 950}) == "dangerous", "the higher of the two"
    assert t({"class": "uEm10", "hp_max": 100}) == "normal"
    monkeypatch.setattr(C, "IDENTITY", False)
    assert t({"class": "uEm20", "hp_max": 100}) == "normal"
    monkeypatch.setattr(C, "IDENTITY", True)
    monkeypatch.setattr(C, "_identity", types.SimpleNamespace(tier=lambda *a: 1 / 0))
    assert t({"class": "uEm20", "hp_max": 3000}) == "boss", "an identity error falls to the title's own read"


# --- (e) never idle ----------------------------------------------------------------------------------------------------
def guard_run(g, t0, t1, **kw):
    """IdleGuard.tick every 0.1 s from t0 up to t1: the verdicts by time."""
    out, k = {}, 0
    while t0 + 0.1 * k <= t1 + 1e-9:
        t = round(t0 + 0.1 * k, 2)
        out[t] = g.tick(P, t, threat=kw.get("threat", True), aiming=kw.get("aiming", False),
                        fired=kw.get("fired", False), moving=kw.get("moving", False))
        k += 1
    return out


def test_the_gun_up_without_a_shot_is_move_and_standing_still_is_engage():
    g = C.IdleGuard({})
    guard_run(g, 0.0, 0.3, aiming=True)
    assert g.tick(P, 0.4, threat=True, aiming=True, fired=True, moving=False) is None      # a shot: its clock again
    v = guard_run(g, 0.5, 2.5, aiming=True)
    assert v[2.3] is None and v[2.4] == "move" and g.stats["idle_aim_breaks"] == 1
    s = C.IdleGuard({})
    assert set(guard_run(s, 0.0, 0.5, moving=True).values()) == {None}
    v = guard_run(s, 0.6, 1.5)
    assert v[1.3] is None and v[1.4] == "engage" and s.stats["idle_still_breaks"] == 1
    assert set(guard_run(C.IdleGuard({}), 0.0, 3.0, aiming=True, threat=False).values()) == {None}, "no threat"
    q = C.IdleGuard({})
    guard_run(q, 0.0, 1.5, aiming=True)
    assert q.tick(P, 3.0, threat=True, aiming=True, fired=False, moving=False) is None, "a gap: not his decision"
    assert q.tick(P, 3.1, threat=True, aiming=True, fired=False, moving=False) is None


def test_the_core_learns_no_wind_up_from_a_hit_taken_while_the_attacker_only_walked(tmp_path):
    """threat_memory.held_needs_flag (the core sets it): the motion he is IN at the hit counts only with his attack flag
    up; RE5's own memory keeps the first rule."""
    def hit(tm):
        e = {"ptr": 3, "class": "z", "motion": "Walk", "pos": (0.0, 0.0, 150.0), "hp": 700}
        tm.observe(1.0, [e], (0.0, 0.0, 0.0))
        tm.observe(1.5, [e], (0.0, 0.0, 0.0))
        tm.hurt(2.0, (0.0, 0.0, 0.0))
        return e
    core = C.Threats(P, {}, path=tmp_path / "c.json").tm
    assert not core.lethal(hit(core)) and core.grudge({"ptr": 3}) == 1, "a grudge, not a wind-up"
    from gbox.mercs import threat_memory as T
    first = T.ThreatMemory(tmp_path / "f.json")
    assert first.lethal(hit(first)), "the first rule, as RE5 Switch has it"


def test_re4_aiming_at_a_ganado_without_a_shot_rounds_him_instead_of_standing_there(monkeypatch):
    monkeypatch.setattr(R4, "CONTROLS_READY", False)                    # a gate that holds every shot
    s = {"player": {"pos": (0.0, 0.0, 0.0), "rot": 0.0, "hp": 1000, "ptr": 1},
         "enemies": [{"pos": (0.0, 0.0, 5000.0), "hp": 400, "ptr": 100}]}
    b = R4.Bot(stats={}, director=False)
    acts = [b.tick(s, now=0.1 * k) for k in range(21)]
    assert all(R4.AIM_BTN in a["hold"] for a in acts[:20])
    assert b.doing == "flank" and "lup" in acts[-1]["hold"] and R4.AIM_BTN not in acts[-1]["hold"]
    assert b.stats["idle_aim_breaks"] == 1
    monkeypatch.setattr(R4, "UNIVERSAL_CORE", False)
    old = R4.Bot(stats={}, director=False)
    assert all(R4.AIM_BTN in old.tick(s, now=0.1 * k)["hold"] for k in range(25)), "the rollback holds the aim"


def test_re6_aiming_without_a_shot_walks_in_at_him_as_he_aims():
    b = R6.Bot(stats={}, clock=lambda: 0.0)
    b.target, b.doing = 5, "aim"
    ticks = [round(0.1 * k, 2) for k in range(int(R6.IDLE_AIM_S * 10))]
    assert all(b._idle_core({}, {"hold": ("zl",)}, t) == {"hold": ("zl",)} for t in ticks)
    walk = b._idle_core({}, {"hold": ("zl",)}, R6.IDLE_AIM_S)
    assert set(walk["hold"]) == {"zl", "lup"} and b.stats["idle_walks"] == 1
    assert "lup" in b._idle_core({}, {"hold": ("zl",)}, R6.IDLE_AIM_S + 0.1)["hold"], "for IDLE_WALK_S"
    assert b._idle_core({}, {"hold": ("zl", "zr")}, R6.IDLE_AIM_S + 0.2) == {"hold": ("zl", "zr")}, "a shot: aimed"


# --- each title: the profiles and who hurt him ---------------------------------------------------------------------------
def test_every_title_builds_its_profile_from_its_live_constants(monkeypatch):
    p4, p5, p6 = C.profile("re4_switch"), C.profile("re5_switch"), C.profile("re6_switch")
    assert (p4.units_per_cm, p5.units_per_cm, p6.units_per_cm) == (R4.MM_PER_CM, 1.0, 1.0)
    assert (p4.aim_model, p5.aim_model, p6.aim_model) == ("tank_heading", "laser_ray", "laser_camera_geometry")
    assert p4.body_units({}).r == R4.FIRE_HALF_WIDTH_MM and p6.body({}).chest == R6.CHEST_H
    assert p5.body({"class": "uEm32"}) is C.KIND_BODIES["crawler"]
    assert p4.tier({"hp_max": R4.HEAVY_HP}) == "dangerous" and p6.tier({"hp_max": R6.BOSS_HP}) == "boss"
    assert p6.tier({"hp_max": R6.BIG_HP}) == "dangerous" and p5.tier({"hp_max": 300}) == "normal"
    monkeypatch.setattr(R4, "RAISE_TOL", 0.5)
    assert C.profile("re4_switch").raise_tol == 0.5, "a knob turned live is in the next profile"


def test_no_test_reads_or_teaches_the_live_threat_files():
    for mod in (R4, R5, R6):
        assert "gbox-data" not in str(mod.THREAT_FILE), mod.__name__


def r4snap(enemies, hp=1000):
    return {"player": {"pos": (0.0, 0.0, 0.0), "rot": 0.0, "hp": hp, "ptr": 1},
            "enemies": [dict(e, pos=tuple(v * R4.MM_PER_CM for v in e["pos"])) for e in enemies]}


def test_re4_the_ganado_that_hurt_him_is_the_next_target_before_a_nearer_one(monkeypatch):
    b = R4.Bot(stats={}, director=False)
    hitter = {"ptr": 100, "hp": 400, "hp_max": 400, "class": 0xAE7050}
    other = {"ptr": 101, "hp": 400, "hp_max": 400, "class": 0xAE7050}
    b.tick(r4snap([dict(hitter, pos=(0.0, 0.0, 150.0)), dict(other, pos=(300.0, 0.0, 400.0))]), now=1.0)
    b.tick(r4snap([dict(hitter, pos=(0.0, 0.0, 150.0)), dict(other, pos=(300.0, 0.0, 400.0))], hp=900), now=1.1)
    assert b.stats["tm_hits_attributed"] == 1
    later = r4snap([dict(hitter, pos=(0.0, 0.0, 600.0)), dict(other, pos=(100.0, 0.0, 350.0))], hp=900)
    b.tick(later, now=2.0)
    assert b.target == 100 and b.stats["core_pick"].startswith("grudge")
    b.save()
    assert R4.THREAT_FILE.exists() and "0xae7050:400" in R4.THREAT_FILE.read_text(encoding="utf-8")
    monkeypatch.setattr(R4, "UNIVERSAL_CORE", False)
    old = R4.Bot(stats={}, director=False)
    old.tick(later, now=2.0)
    assert old.target == 101, "the rollback: the nearest"


def test_re4_a_heavy_in_reach_is_dispatched_first_unless_one_is_at_arms_length():
    heavy = {"ptr": 100, "hp": 3500, "hp_max": 3500, "pos": (0.0, 0.0, 700.0)}
    b = R4.Bot(stats={}, director=False)
    b.tick(r4snap([heavy, {"ptr": 101, "hp": 400, "hp_max": 400, "pos": (100.0, 0.0, 400.0)}]), now=1.0)
    assert b.target == 100 and b.stats["dangerous_picks"] == 1
    g = R4.Bot(stats={}, director=False)
    g.tick(r4snap([heavy, {"ptr": 101, "hp": 400, "hp_max": 400, "pos": (60.0, 0.0, 150.0)}]), now=1.0)
    assert g.target == 101 and g.stats["grab_picks"] == 1


def re6_rows(dist_hitter=150.0, action="cEm5200ActWalk", hp=700, hp_max=700):
    hitter = {"ptr": 10, "slot": 0, "pos": (0.0, 0.0, dist_hitter), "hp": hp, "hp_max": hp_max, "class": "uEm5200",
              "action": action}
    other = {"ptr": 11, "slot": 1, "pos": (100.0, 0.0, 350.0), "hp": 700, "hp_max": 700, "class": "uEm5200",
             "action": "cEm5200ActWalk"}
    return hitter, other


def test_re6_the_one_that_hurt_him_is_the_next_target_before_a_nearer_one(monkeypatch):
    b = R6.Bot(stats={}, clock=lambda: 0.0)
    p = {"ptr": 1, "pos": (0.0, 0.0, 0.0), "rot": 0.0, "hp": 900, "hp_max": 900}
    th = b._uc("threats")
    th.observe(1.0, p, re6_rows(), R6.combat_profile())
    th.observe(1.1, dict(p, hp=800), re6_rows(), R6.combat_profile())
    hitter, other = re6_rows(dist_hitter=600.0)
    assert b._choose(p, 0.0, [hitter, other], 2.0) is hitter and b.stats["grudge_picks"] == 1
    monkeypatch.setattr(R6, "UNIVERSAL_CORE", False)
    assert R6.Bot(stats={}, clock=lambda: 0.0)._choose(p, 0.0, [hitter, other], 2.0) is other


def test_re6_learns_an_attack_its_fixed_keys_do_not_know_and_stops_it_first():
    b = R6.Bot(stats={}, clock=lambda: 0.0)
    p = {"ptr": 1, "pos": (0.0, 0.0, 0.0), "rot": 0.0, "hp": 900, "hp_max": 900}
    prof, th = R6.combat_profile(), b._uc("threats")
    tackle = "cEm5200ActTackle"                                          # no WINDUP_KEYS in it: never a wind-up before
    assert R6.windup(re6_rows(action=tackle)[0], (0.0, 0.0, 0.0)) is None
    th.observe(1.0, p, re6_rows(dist_hitter=300.0), prof)
    th.observe(1.5, p, re6_rows(dist_hitter=300.0, action=tackle), prof)
    th.observe(2.0, dict(p, hp=700), re6_rows(dist_hitter=300.0, action=tackle), prof)
    tackler, _ = re6_rows(dist_hitter=420.0, action=tackle)
    tackler = dict(tackler, ptr=12, slot=2)                              # another of the class, mid-tackle
    near = {"ptr": 13, "slot": 3, "pos": (0.0, 0.0, 250.0), "hp": 700, "hp_max": 700, "class": "uEm1000",
            "action": "cEm1000ActWalk"}
    assert b._choose(dict(p, hp=700), 0.0, [near, tackler], 3.0) is tackler and b.stats["windup_picks"] == 1


def test_re6_steps_out_of_an_attack_that_lands_through_his_shots():
    b = R6.Bot(stats={}, clock=lambda: 0.0)
    p = {"ptr": 1, "pos": (0.0, 0.0, 0.0), "rot": 0.0, "hp": 900, "hp_max": 900}
    prof, th = R6.combat_profile(), b._uc("threats")
    charge = "cEm3000ActRush"
    big = lambda a, hp: {"ptr": 20, "slot": 0, "pos": (0.0, 0.0, 450.0), "hp": hp, "hp_max": 3000,
                         "class": "uEm3000", "action": a}
    th.observe(1.0, p, [big("cEm3000ActWalk", 3000)], prof)
    th.observe(1.5, p, [big(charge, 3000)], prof)
    th.observe(2.0, p, [big(charge, 2500)], prof)                       # his shots hurt it all through the charge
    th.observe(2.2, dict(p, hp=500), [big(charge, 2500)], prof)
    out = b._lethal_out(dict(p, hp=500), [big(charge, 2500)], {}, 5.0)
    assert out is not None and b.stats["act"] == "lethal_backoff" and "zr" not in out.get("hold", ())
    assert set(out["hold"]) & {"ldown", "lleft", "lright", "lup"} and b.stats["lethal_backoffs"] == 1


def test_re6_a_boss_in_reach_first_by_its_own_health_read_never_past_one_at_arms_length():
    b = R6.Bot(stats={}, clock=lambda: 0.0)
    p = {"ptr": 1, "pos": (0.0, 0.0, 0.0), "rot": 0.0, "hp": 900, "hp_max": 900}
    boss = {"ptr": 30, "slot": 0, "pos": (0.0, 0.0, 900.0), "hp": 4000, "hp_max": 4000, "class": "uEm2300"}
    zombie = {"ptr": 31, "slot": 1, "pos": (100.0, 0.0, 300.0), "hp": 700, "hp_max": 700, "class": "uEm5200"}
    assert b._choose(p, 0.0, [zombie, boss], 1.0) is boss and b.stats["boss_picks"] == 1
    hug = dict(zombie, ptr=32, slot=2, pos=(20.0, 0.0, 100.0))
    assert b._choose(p, 0.0, [zombie, boss, hug], 2.0) is hug and b.stats["grab_picks"] == 1


def test_re5_a_boss_in_reach_is_dispatched_after_the_wind_ups_and_never_past_one_at_arms_length():
    b, _ = re5_bot()
    p = {"ptr": 1, "pos": (0.0, 0.0, 0.0), "rot": 0.0, "hp": 1000, "hp_max": 1000, "motion": 0}
    boss = {"ptr": 40, "pos": (0.0, 0.0, 900.0), "hp": 5000, "hp_max": 5000, "class": "uEm40", "motion": 4}
    majini = {"ptr": 41, "pos": (50.0, 0.0, 450.0), "hp": 300, "hp_max": 300, "class": "uEm10", "motion": 4}
    assert b._choose(p, [majini, boss], 1.0) is boss and b.stats["boss_picks"] == 1
    g, _ = re5_bot()
    hug = dict(majini, ptr=42, pos=(10.0, 0.0, 90.0))
    assert g._choose(p, [majini, boss, hug], 1.0) is hug
