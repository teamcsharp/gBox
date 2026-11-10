"""The fire pattern (gbox.mercs.core.fire_pattern): the PS3 magnum's rapid repeat and scatter, on synthetic state.

Every test here is synthetic: shapes and invariants of the pattern and of each title's binding, never a claim about a
live round (the measured PS3 numbers are fire_pattern.PS3_MAGNUM's, from the round maps).
"""
import math

import pytest

from gbox.mercs.core import combat
from gbox.mercs.core import fire_pattern as F


BODIES = [combat.HUMAN, combat.KIND_BODIES["crawler"], combat.KIND_BODIES["dog"]]


# --- the scatter ---------------------------------------------------------------------------------------------------------
def test_the_ps3_measurement_is_recorded_with_its_source():
    m = F.PS3_MAGNUM
    assert "BLUS30491" in m["source"] and "held" in m["trigger"]
    assert all(0.05 <= g <= 0.3 for g in m["gap_s_median"] + m["gap_s_p10"])
    assert all(p > med for p, med in zip(m["shots_per_s_burst_p90"], m["shots_per_s_burst_median"]))


@pytest.mark.parametrize("family", sorted(F.FAMILIES))
@pytest.mark.parametrize("body", BODIES)
def test_every_point_of_the_scatter_lands_on_the_body_the_hit_test_uses(family, body):
    sp = F.spec(family)
    for k in range(400):
        lat, h = F.offset(sp, body, k)
        assert combat.dot_on((lat, h, 0.0), (0.0, 0.0, 0.0), body) is not None, (family, k, lat, h)


def test_the_first_shot_is_the_chest_and_the_rest_spread_across_him_both_ways():
    sp = F.spec("magnum")
    assert F.offset(sp, combat.HUMAN, 0) == (0.0, combat.HUMAN.chest)
    pts = [F.offset(sp, combat.HUMAN, k) for k in range(1, 13)]
    lats, hs = [p[0] for p in pts], [p[1] for p in pts]
    assert min(lats) < -10.0 and max(lats) > 10.0, "both sides of him"
    assert max(hs) - min(hs) > 40.0, "from the belly to the shoulders"
    assert len({(round(a), round(b)) for a, b in pts}) == len(pts), "no two shots on one spot"
    steps = [math.dist(a, b) for a, b in zip(pts, pts[1:])]
    assert min(steps) > 5.0, "successive shots well apart (R2, never a random clump)"


def test_the_shotgun_keeps_its_own_spread_and_the_automatics_have_no_pattern():
    assert F.offset(F.spec("shotgun"), combat.HUMAN, 7) == (0.0, combat.HUMAN.chest)
    assert F.spec("automatic") is None and F.spec("launcher") is None and F.spec("bow") is None


# --- the rapid repeat ------------------------------------------------------------------------------------------------------
def presses(style, gap_s, seconds=1.0, tick=0.05):
    t, tr, downs = F.Trigger(), 0.0, []
    for i in range(int(round(seconds / tick))):
        downs.append(t.tick(i * tick, True, style, gap_s))
    return t.presses, downs


def test_the_trigger_styles_at_the_20_hz_tick():
    n, downs = presses("hold", 0.0)
    assert n == 1 and all(downs), "held: one press, the game repeats it"
    n, downs = presses("edge", 0.0)
    assert n == 10 and downs[:4] == [True, False, True, False], "edge: down a tick, up a tick"
    assert presses("tap", 0.05)[0] == 20, "tap: one every tick at the 0.05 s floor"
    assert presses("tap", 0.25)[0] == 4 and presses("edge", 0.09)[0] == 10


def test_the_trigger_lets_go_when_the_line_leaves_him():
    t = F.Trigger()
    assert t.tick(0.0, True, "hold") and not t.tick(0.05, False, "hold") and t.tick(0.1, True, "hold")
    assert t.presses == 2


def test_cadence_per_title_profile():
    assert combat.fire_cadence(combat.profile("re6_switch")) == pytest.approx(10.0)
    assert combat.fire_cadence(combat.profile("re4_gc")) == pytest.approx(10.0)
    assert combat.fire_cadence(combat.profile("re5_ps3")) == pytest.approx(12.5)
    assert combat.fire_cadence(combat.profile("re5_switch")) == 0.0, "held: the game's repeat, not counted at x5"
    re4 = combat.profile("re4_switch")
    assert F.cadence_hz(re4.fire_style, re4.fire_tick_s, 0.05, re4.fire_cap_hz) == pytest.approx(10.0), \
        "at fire_rate 20x the taps (20 a second) outrun the shot gate's floor (10)"


# --- earned by an effect ---------------------------------------------------------------------------------------------------
def foe(ptr, pos, hp=100):
    return {"ptr": ptr, "pos": pos, "hp": hp, "hp_max": 100}


def test_the_scatter_is_earned_by_an_effect_and_lapses_without_one():
    fp, sp = F.FirePattern({}), F.spec("magnum")
    a = foe(1, (0.0, 0.0, 500.0))
    fp.observe(0.0, [a])
    fp.shot(0.0, 1)
    assert fp.point_k(sp, 0.1, 500.0) == 0, "no effect yet: the chest (an intro card never sees a scatter)"
    fp.note(0, sp, 0.1)
    assert fp.stats["fire_pattern_unearned"] == 1
    fp.observe(0.2, [dict(a, hp=80)])
    assert fp.point_k(sp, 0.3, 500.0) >= 1
    assert fp.point_k(sp, 0.3, 100.0) == 0, "point blank: the chest"
    assert fp.point_k(sp, 0.2 + sp.earn_s + 0.1, 500.0) == 0, "no effect for earn_s: back on the chest"
    fp2 = F.FirePattern({})
    fp2.observe(0.0, None, kills=3)
    fp2.observe(0.5, None, kills=4)
    assert fp2.earned(sp, 0.6), "a kill is an effect too"


# --- the hop -----------------------------------------------------------------------------------------------------------
def hop_setup():
    fp, sp = F.FirePattern({}), F.spec("magnum")
    a, b = foe(1, (0.0, 0.0, 500.0)), foe(2, (20.0, 0.0, 700.0))
    fp.effect(0.0)
    return fp, sp, a, b


def test_after_hop_every_shots_the_next_goes_to_the_one_on_the_gun_line():
    fp, sp, a, b = hop_setup()
    for i in range(sp.hop_every - 1):
        fp.shot(0.1 * i, 1)
        assert fp.hop(sp, 0.1 * i, (0, 0, 0), a, [a, b], level_dy=120.0) is None
    fp.shot(0.3, 1)
    assert fp.hop(sp, 0.3, (0, 0, 0), a, [a, b], level_dy=120.0) is b
    assert fp.stats["fire_pattern_hops"] == 1


@pytest.mark.parametrize("why, change", [
    ("off the line", {"pos": (200.0, 0.0, 600.0)}),
    ("too far from him", {"pos": (0.0, 0.0, 900.0)}),
    ("another floor", {"pos": (20.0, 300.0, 700.0)}),
    ("dead", {"hp": 0}),
])
def test_no_hop_to_one_off_the_line_far_off_on_another_floor_or_dead(why, change):
    fp, sp, a, b = hop_setup()
    b.update(change)
    for i in range(sp.hop_every):
        fp.shot(0.1 * i, 1)
    assert fp.hop(sp, 0.5, (0, 0, 0), a, [a, b], level_dy=120.0) is None, why


def test_no_hop_away_from_a_priority_pick_or_without_an_effect():
    fp, sp, a, b = hop_setup()
    for i in range(sp.hop_every):
        fp.shot(0.1 * i, 1)
    assert fp.hop(sp, 0.5, (0, 0, 0), a, [a, b], level_dy=120.0, locked=True) is None
    assert fp.hop(sp, 5.0, (0, 0, 0), a, [a, b], level_dy=120.0) is None, "no effect for earn_s"


# --- the drivers -------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("title", ["re4_switch", "re4_gc"])
def test_the_tank_driver_scatter_stays_inside_the_body_half_angle(title):
    prof = combat.profile(title)
    drv = combat.fire_driver(prof)
    assert isinstance(drv, F.TankDriver) and prof.units_per_cm == 10.0
    drv.fp.effect(0.0)
    e = {"ptr": 5, "pos": (0.0, 0.0, 5000.0), "hp": 400}
    offs = set()
    for d_mm in (2000.0, 5000.0, 12000.0):
        for k in range(12):
            drv.fired(0.01 * k, 5)
            steer, off = drv.aim(prof, "magnum", e, d_mm, 0.0, 0.2)
            half = combat.half_angle(prof.body_units(e), d_mm)
            assert abs(off) < half and steer == pytest.approx(off)
            offs.add(round(off, 4))
    assert len(offs) > 10


@pytest.mark.parametrize("title", ["re5_switch", "re5_ps3"])
def test_the_laser_driver_steers_onto_points_of_his_body(title):
    prof = combat.profile(title)
    drv = combat.fire_driver(prof)
    assert isinstance(drv, F.LaserDriver)
    drv.fp.effect(0.0)
    e = {"ptr": 5, "pos": (100.0, 0.0, 600.0), "hp": 100}
    chest = (100.0, combat.HUMAN.chest, 600.0)
    seen = set()
    for k in range(20):
        drv.fired(0.01 * k, 5)
        pt = drv.point(prof, "magnum", e, (0.0, 0.0, 0.0), chest, 0.25)
        assert combat.dot_on(pt, e["pos"], prof.body(e)) is not None
        seen.add(tuple(round(v) for v in pt))
    assert len(seen) > 15


def test_a_special_site_keeps_its_height_and_scatters_across_only():
    prof = combat.profile("re5_switch")
    drv = combat.fire_driver(prof)
    drv.fp.effect(0.0)
    e = {"ptr": 5, "pos": (0.0, 0.0, 600.0), "hp": 100}
    head = (0.0, combat.HUMAN.head, 600.0)
    for k in range(10):
        drv.fired(0.01 * k, 5)
        pt = drv.point(prof, "magnum", e, (0.0, 0.0, 0.0), head, 0.2)
        assert pt[1] == pytest.approx(min(combat.HUMAN.head, combat.HUMAN.shoulder + 15.0))
        assert pt[2] == pytest.approx(600.0), "across the line of fire: x only, the line runs along z"


@pytest.mark.parametrize("title", ["re6_switch", "re6_ps3"])
def test_the_camera_driver_offset_runs_across_the_line_and_is_zero_until_earned(title):
    prof = combat.profile(title)
    drv = combat.fire_driver(prof)
    assert isinstance(drv, F.CameraDriver)
    e = {"ptr": 5, "pos": (300.0, 0.0, 400.0), "hp": 100}
    aim = (300.0, prof.body(e).chest, 400.0)
    drv.fired(0.0, 5)
    assert drv.offset(prof, "magnum", e, (0.0, 0.0, 0.0), aim, 0.1) == (0.0, 0.0, 0.0)
    drv.fp.effect(0.1)
    for k in range(10):
        drv.fired(0.1 + 0.01 * k, 5)
        dx, dy, dz = drv.offset(prof, "magnum", e, (0.0, 0.0, 0.0), aim, 0.3)
        assert abs(dx * 300.0 + dz * 400.0) < 1e-6, "perpendicular to the line of fire"
        assert combat.dot_on((aim[0] + dx, aim[1] + dy, aim[2] + dz), e["pos"], prof.body(e)) is not None


def test_fire_spec_follows_the_title_switch():
    on = combat.profile("re5_switch")
    assert on.fire_pattern and combat.fire_spec(on, "magnum") is F.spec("magnum")
    off = combat.profile("re5_ps3")
    assert not off.fire_pattern and combat.fire_spec(off, "magnum") is None


def test_the_ps3_and_gamecube_editions_have_profiles_the_core_can_drive():
    for title, model, units, btn in (("re5_ps3", "laser_ray", 1.0, "r1"), ("re6_ps3", "laser_camera_geometry", 1.0, "r1"),
                                     ("re4_gc", "tank_heading", 10.0, "a")):
        prof = combat.profile(title)
        assert prof.aim_model == model and prof.units_per_cm == units and prof.fire_btn == btn
        assert prof.fire_pattern is False, "described, not wired: their own fights are unchanged"
        assert type(combat.fire_driver(prof)).model == model
    from gbox.mercs.titles import re4_gc, re5_ps3
    assert re5_ps3.fire_family({"type": 1, "item": 0x0B}) == "magnum"
    assert re5_ps3.fire_family({"type": 1, "item": 0x03}) == "automatic" and F.spec("automatic") is None
    assert combat.profile("re4_gc").family("magnum") == "magnum" and re4_gc.FIRE_FAMILY_BY_KIND["rocket"] is None


# --- RE4 Switch's binding ---------------------------------------------------------------------------------------------------
from gbox.mercs.titles import re4_switch as D4                                    # noqa: E402


def mm(p):
    return tuple(v * D4.MM_PER_CM for v in p)


def snap4(enemies, rot=0.0, **extra):
    return {"player": {"pos": (0.0, 0.0, 0.0), "rot": rot, "hp": 1000, "ptr": 1},
            "enemies": [{"pos": mm(p), "hp": h, "ptr": 100 + i} for i, (p, h) in enumerate(enemies)], **extra}


def test_re4_families_from_the_equipped_class():
    assert D4.fire_family({"weapon_class": 0x0F}) == "magnum" and D4.fire_family({"weapon_class": 0x05}) == "magnum"
    assert D4.fire_family({"weapon_class": 0x0B}) is None, "the TMP: no pattern"
    assert D4.fire_family({}) == D4.FIRE_DEFAULT_FAMILY


def re4_shots(monkeypatch, on=True, hit_at=1, n=7, cls=0x0F):
    monkeypatch.setattr(D4, "FIRE_PATTERN", on)
    monkeypatch.setattr(D4, "FIRE_GAP_S", 0.25)
    b = D4.Bot(stats={}, director=False)
    s = snap4([((0.0, 0.0, 500.0), 400)], weapon_class=cls)
    b.tick(s, now=9.0)                                              # the gun up
    yaws, taps, t = [], 0, 10.0
    for i in range(n):
        if i == hit_at:
            s["enemies"][0]["hp"] = 300                             # a hit landed
        act = b.tick(s, now=t)
        taps += act.get("tap") == D4.FIRE_BTN
        yaws.append(D4.AIM_REQUEST["yaw"])
        t += D4.FIRE_GAP_S + 0.01
    return b, yaws, taps


def test_re4_taps_scatter_the_facing_across_him_once_a_shot_lands(monkeypatch):
    b, yaws, taps = re4_shots(monkeypatch)
    assert taps == 7, "the rapid repeat untouched: a tap every FIRE_GAP_S"
    assert yaws[0] == pytest.approx(0.0), "before any effect: his bearing"
    later = yaws[2:]
    half = math.atan2(D4.FIRE_HALF_WIDTH_MM, 5000.0)
    assert len({round(y, 4) for y in later}) >= 4 and all(abs(y) < half for y in later)
    assert b.stats["fire_pattern_scattered"] >= 4 and b.stats["fire_pattern_family"] == "magnum"


def test_re4_rollback_and_no_effect_keep_every_tap_on_his_bearing(monkeypatch):
    _b, yaws, taps = re4_shots(monkeypatch, on=False)
    assert taps == 7 and all(y == pytest.approx(0.0) for y in yaws)
    _b, yaws, taps = re4_shots(monkeypatch, on=True, hit_at=None)
    assert taps == 7 and all(y == pytest.approx(0.0) for y in yaws), "no effect: an intro card sees no scatter"
    _b, yaws, _t = re4_shots(monkeypatch, on=True, cls=0x0B)
    assert all(y == pytest.approx(0.0) for y in yaws), "an automatic has no pattern"


def test_re4_hops_to_the_next_ganado_on_the_gun_line_and_back(monkeypatch):
    monkeypatch.setattr(D4, "FIRE_PATTERN", True)
    monkeypatch.setattr(D4, "FIRE_GAP_S", 0.25)
    b = D4.Bot(stats={}, director=False)
    s = snap4([((0.0, 0.0, 500.0), 400), ((20.0, 0.0, 700.0), 400)], weapon_class=0x0F)
    b.tick(s, now=9.0)
    targets, t = [], 10.0
    for i in range(8):
        if i == 0:
            s["enemies"][0]["hp"] = 300
        act = b.tick(s, now=t)
        if act.get("tap"):
            targets.append(b.target)
        t += D4.FIRE_GAP_S + 0.01
    assert 101 in targets and targets.count(100) > targets.count(101), targets
    assert b.stats["fire_pattern_hops"] >= 1


# --- RE5 Switch's binding -----------------------------------------------------------------------------------------------
from gbox.mercs.titles import re5_switch as D5                                    # noqa: E402


def test_re5_families_from_the_gun_in_hand():
    assert D5.fire_family({"inventory": [{"hand": True, "type": 1, "item": 0x0B}]}) == "magnum"
    assert D5.fire_family({"inventory": [{"hand": True, "type": 1, "item": 0x03}]}) == "automatic"
    assert D5.fire_family({"inventory": []}) is None


def re5_steer(motion=26, item=0x0B, hp_fall=True, calls=4):
    b = D5.Bot(stats={}, clock=lambda: 0.0)
    tgt = {"ptr": 7, "pos": (0.0, 0.0, 500.0), "hp": 100, "hp_max": 100}
    chest = (0.0, D5.HUMAN.chest, 500.0)
    origin, dot = (0.0, 140.0, 0.0), chest                          # the laser on his chest
    snap = {"inventory": [{"hand": True, "type": 1, "item": item}], "enemies": [tgt], "kills": 0}
    keys = set()
    for i in range(calls):
        if hp_fall and i == 1:
            tgt["hp"] = 80
        keys |= b._fp_steer({"pos": (0.0, 0.0, 0.0)}, tgt, chest, origin, dot, snap, motion, 1.0 + 0.04 * i)
    return b, keys


def test_re5_on_him_the_stick_moves_the_laser_across_his_body_between_shot_motions():
    b, keys = re5_steer()
    assert keys & {"rleft", "rright", "rup", "rdown"} and b.stats["fire_pattern_steer_ticks"] >= 1


def test_re5_no_scatter_in_the_shot_motion_for_an_automatic_or_without_an_effect():
    b, keys = re5_steer(motion=D5.MOTION_SHOT)
    assert not keys and b.stats["fire_pattern_motion_waits"] >= 1, "the time-scaled shot motion: the stick waits"
    _b, keys = re5_steer(item=0x03)
    assert not keys, "the VZ61: no pattern"
    _b, keys = re5_steer(hp_fall=False)
    assert not keys, "no effect: the laser stays where it is, as before"


def test_re5_the_call_site_is_behind_its_switch(monkeypatch):
    import inspect
    src = inspect.getsource(D5.Bot._decide)
    assert "elif FIRE_PATTERN and on and not long_shot and not confirmed:" in src


# --- RE6 Switch's binding -----------------------------------------------------------------------------------------------
from gbox.mercs.titles import re6_switch as D6                                    # noqa: E402
from test_re6_switch import _fresh_caches, lock_brain, run                        # noqa: E402,F401


def test_re6_families_from_the_weapon_id():
    assert D6.fire_family({"weapon_id": 7}) == "magnum" and D6.fire_family({"weapon_id": 8}) == "magnum"
    assert D6.fire_family({"weapon_id": 0x0F}) is None, "the assault rifle: held, no pattern"
    assert D6.fire_family({"weapon_id": 1}) == "handgun" and D6.fire_family({}) is None


def re6_round(monkeypatch, on=True, hit=True, wid=7):
    monkeypatch.setattr(D6, "FIRE_PATTERN", on)
    laser = ((0.0, D6.CHEST_H, 900.0), (20.0, 145.0, 30.0), 0.86)
    bot, clock, snap, writes = lock_brain(((0.0, 0.0, 900.0, 700),), laser=laser)
    snap["player"]["weapon_id"] = wid
    first = run(bot, snap, clock, 12)
    if hit:
        snap["enemies"][0]["hp"] = 600
    acts = run(bot, snap, clock, 20)
    presses = sum("zr" in a.get("hold", ()) for a in first + acts)
    return bot, writes, presses


def test_re6_magnum_presses_move_the_lock_across_him_once_shots_land(monkeypatch):
    bot, writes, presses = re6_round(monkeypatch)
    assert presses > 0 and bot.stats["fire_pattern_scattered"] >= 3
    assert len({round(w[2], 4) for w in writes[-12:]}) >= 3, "the written yaw moves between presses"
    _b, _w, presses_off = re6_round(monkeypatch, on=False)
    assert presses >= presses_off - 2, "the scatter never slows the rapid repeat (a redirect is the edge's up tick)"


def test_re6_rollback_and_automatics_keep_the_lock_on_his_aim_point(monkeypatch):
    for kw in ({"on": False}, {"hit": False}, {"wid": 0x0F}):
        _bot, writes, _p = re6_round(monkeypatch, **kw)
        assert len({round(w[2], 4) for w in writes[-12:]}) == 1, kw
