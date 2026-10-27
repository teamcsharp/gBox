"""RE4 Mercenaries behaviour fixes (operator 2026-10-26, watching MercMode RE4): steering without the sine wave, through
doorway centres, a locked aim that does not wave, no ammo pickups, time bonuses taken when the route passes them,
chickens only when health is low and only on target, what a stage taught kept across runs, and the per-round behaviour
metrics that make each of these measurable (gbox.mercs.behavior_metrics, the round audit)."""
import json
import math
import struct

import pytest

from gbox import re4_merc_bot as B
from gbox.mercs import behavior_metrics as BM
from gbox.mercs.round_audit import RoundAudit
from gbox.mercs.round_map import RoundTrace
from gbox.re4_threats import Threat
from tests.test_re4_merc_bot import EM, PG, PL, STRIDE, act_state, facing, item, run, set_pitch, world


def bare_bot():
    bot = B.Bot(world([]), nav=False)
    bot._round(0x400)
    return bot


# --- steering -----------------------------------------------------------------------------------------------------
def test_steering_stays_quiet_inside_the_deadband_pulses_in_proportion_and_holds_a_big_error():
    bot = bare_bot()
    assert bot._steer(0.03) == 0                                          # inside the deadband: nothing
    turns = [bot._steer(0.175) for _ in range(20)]                        # half the pulse zone: about every other tick
    assert 8 <= sum(t == 1 for t in turns) <= 12 and set(turns) <= {0, 1}
    bot2 = bare_bot()
    assert all(bot2._steer(-0.6) == -1 for _ in range(5))                 # beyond STEER_PULSE: held
    bot3 = bare_bot()
    assert bot3._steer(0.2) == 1                                          # a fresh error: the key at once


def test_steering_coasts_when_the_turn_under_way_will_carry_him_and_never_flip_flops():
    bot = bare_bot()
    bot.run_turn_rate = 3.0
    assert bot._steer(0.6) == 1                                           # turning left
    assert bot._steer(0.2) == 0                                           # 0.2 - 3 x 0.1 < 0: the turn carries him (coast)
    assert bot._steer(-0.1) == 0                                          # a small error the other way: no reversal
    assert bot._steer(-0.3) == -1                                         # a real one: the other way


def test_the_run_steers_at_a_point_ahead_on_the_path_not_at_the_waypoint():
    bot = bare_bot()
    p = {"pos": (0.0, 0.0, 0.0), "rot": 0.0}
    way = [(0.0, 5000.0), (5000.0, 5000.0)]
    pt, last = bot._lookahead(p, way)
    assert pt == pytest.approx((0.0, B.LOOKAHEAD)) and not last
    near_corner = {"pos": (0.0, 0.0, 4000.0), "rot": 0.0}
    pt, last = bot._lookahead(near_corner, way)                           # past the corner onto the next leg (open)
    assert pt[1] == pytest.approx(5000.0) and 0.0 < pt[0] < B.LOOKAHEAD and not last
    bot.st = {"walls": [[-100.0, 4800.0, 100.0, 4800.0, -1000.0, 3000.0, 0.0],
                        [1000.0, 4000.0, 1000.0, 6000.0, -1000.0, 3000.0, 0.0]]}   # the corner is walled off
    pt, _ = bot._lookahead(near_corner, way)
    assert pt == (0.0, 5000.0)                                            # not round the corner through the wall
    pt, _ = bot._lookahead(p, [(0.0, 900.0, "vault"), (0.0, 5000.0)])
    assert pt == (0.0, 900.0)                                             # never past a vault (its press is there)


def test_a_run_reports_its_weave_to_the_round_metrics():
    now = [0.0]
    m = world([], room=0x400, leon=(5592.0, 0.0, 12000.0), timer_s=100.0)
    bot = B.Bot(m, clock=lambda: now[0], nav=False)
    facing(m, 0.4)                                                        # 0.4 rad off the hourglass straight ahead
    for k in range(1, 12):
        now[0] = k * 0.1
        m.put(B.MERC_TIMER, ">I", int((100 - now[0]) * 30))
        bot.tick(B.snapshot(m))
    s = bot.metrics.summary()["path"]
    assert s["run_s"] > 0.5 and s["stick_turns"] >= 1


# --- doorways -----------------------------------------------------------------------------------------------------
def door_stage():
    # a wall across z = 3000 with a 1200 wide doorway between x 400 and 1600 (two segments)
    return {"walls": [[-6000.0, 3000.0, 400.0, 3000.0, -1000.0, 3000.0, 0.0],
                      [1600.0, 3000.0, 6000.0, 3000.0, -1000.0, 3000.0, 0.0],
                      [400.0, 3000.0, 400.0, 3600.0, -1000.0, 3000.0, 0.0],      # the door's jambs (depth 600)
                      [1600.0, 3000.0, 1600.0, 3600.0, -1000.0, 3000.0, 0.0]]}


def test_a_leg_through_a_doorway_gets_a_waypoint_at_its_centre():
    """Operator 2026-10-26: "always running into the entrances of locations instead of going inside" - the planned leg
    hugged the frame. A leg through a passage narrower than DOOR_W is pinned to the passage's middle."""
    bot = bare_bot()
    bot.st = door_stage()
    way = bot._centre_doors((500.0, 0.0, 0.0), [(700.0, 6000.0, None)])   # along the door's left edge
    assert len(way) == 2 and way[-1] == (700.0, 6000.0, None)
    cx, cz = way[0]
    assert cx == pytest.approx(1000.0, abs=60) and 3000.0 <= cz <= 3600.0     # the middle of the doorway
    assert bot.stats["doors_centred"] == 1 and len(bot.portals) == 1
    open_way = bot._centre_doors((-5000.0, 0.0, 0.0), [(-5000.0, 2500.0, None)])
    assert open_way == [(-5000.0, 2500.0, None)]                          # open floor: nothing added
    vault = bot._centre_doors((500.0, 0.0, 0.0), [(700.0, 6000.0, "vault")])
    assert vault == [(700.0, 6000.0, "vault")]                            # a vault leg is left as it is


def test_doorway_passes_and_bumps_are_counted_and_kept_for_the_stage(tmp_path):
    bot = B.Bot(world([]), nav=False, learn_dir=tmp_path)
    bot._round(0x400)
    bot.portals = {"1000,3200": (1000.0, 3200.0)}
    for z in (2000.0, 3000.0, 3200.0, 3400.0, 4500.0):                   # through it once
        bot.metrics.portal_tick(list(bot.portals.items()), (1000.0, z))
    assert bot.metrics.portal_bump(list(bot.portals.items()), (1100.0, 3100.0)) == "1000,3200"
    s = bot.metrics.summary()
    assert s["portal_passes"] == 1 and s["portal_bumps"] == 1
    bot.knowledge.portal(1000.0, 3200.0, bumps=2)
    bot.save()
    again = B.StageKnowledge(tmp_path / "r400-knowledge.json")
    assert again.bumped_portals() == [(1000.0, 3200.0)] and again.summary()["portal_bumps"] == 2


# --- the aim --------------------------------------------------------------------------------------------------------
def threat(slot, kind, dist, eta=math.inf, x=0.0):
    e = {"slot": slot, "pos": (x, 0.0, dist), "hp": 1000, "hp_max": 1000, "r": (1, 0x26 if kind == "swing" else 3, 0, 0)}
    return Threat(slot, kind, eta, (x, 0.0, dist), dist, enemy=e)


def test_the_aim_keeps_its_target_until_a_nearer_one_is_about_to_hit():
    """Operator: "he's waving the gun around randomly" - today 11.8 target switches a minute with the gun up. One target
    is locked; a re-ranked one never takes the aim, a nearer attack landing within LOCK_BREAK_S does."""
    bot = bare_bot()
    s = {"player": {"pos": (0.0, 0.0, 0.0), "rot": 0.0}}
    a, b = threat(1, "near", 1500.0), threat(2, "near", 1400.0, x=200.0)
    assert bot._locked(a, [a, b], s) is a and bot.lock == 1
    assert bot._locked(b, [a, b], s) is a and bot.stats["lock_holds"] == 1       # re-ranked: the aim stays on 1
    far_swing = threat(3, "swing", 1800.0, eta=0.5)
    assert bot._locked(far_swing, [a, b, far_swing], s) is a                     # about to hit but further: no
    close_swing = threat(4, "swing", 800.0, eta=0.6)
    assert bot._locked(close_swing, [a, b, close_swing], s) is close_swing and bot.lock == 4
    assert bot.stats["lock_breaks"] == 1
    dead = threat(4, "near", 800.0)
    dead.enemy["hp"] = 0
    assert bot._locked(b, [a, b, dead], s) is b and bot.lock == 2                 # the locked one died: the next


def test_the_aim_slews_with_a_deadband_and_in_proportion():
    bot = bare_bot()
    tol = math.radians(5)
    assert bot._aim_turn(0.6 * tol - 0.001, tol) == {"r"}                  # inside the deadband: hold still
    assert bot._aim_turn(0.15, tol) == {"r", "left"}                       # a fresh error: at once
    turns = [("left" in bot._aim_turn(0.1, tol)) for _ in range(20)]       # half AIM_PULSE: about half the ticks
    assert 8 <= sum(turns) <= 12
    assert all("right" in bot._aim_turn(-0.5, tol) for _ in range(3))      # a big one: held


def test_the_gun_keeps_tracking_its_target_while_it_fires():
    now = [0.0]
    m = world([((0, 0, 1500), True)])
    facing(m, 0.0)
    bot = B.Bot(m, clock=lambda: now[0], nav=False)
    acts = run(bot, m, now, 0.0, 8)
    assert any("a" in a["hold"] for a in acts)
    facing(m, -0.1)                       # he steps aside: still inside the shot's window (6.8 deg at 1.5 m), past the deadband
    act = run(bot, m, now, now[0] + 0.05)[0]
    assert {"r", "left"} <= act["hold"] and bot.stats["fire_gate"] == "on him"   # firing, and the stick follows him


# --- pickups --------------------------------------------------------------------------------------------------------
def test_a_take_dialog_is_answered_no_unless_he_is_taking_a_time_bonus():
    """Operator: "pick up ammo that they do not need. They should just ignore ammo" - the clock-stopping "Take the ...?"
    was always answered A."""
    now = [0.0]
    m = world([], room=0x400, timer_s=60.0)
    bot = B.Bot(m, clock=lambda: now[0], nav=False)
    bot.tick(B.snapshot(m))
    taps = []
    for k in range(1, 8):                                                 # the clock stops on a pickup dialog
        now[0] = 1.5 + k * 0.5
        taps.append(bot.tick(B.snapshot(m)).get("tap"))
    assert set(t for t in taps if t) == {"b"} and bot.stats["pickups_declined"] >= 1
    hg = item("time_bonus", 0.0, 300.0)                                   # taking an hourglass at hand: Yes
    bot.goal = {"item": hg, "pos": (0.0, 0.0), "path": [(0.0, 0.0)]}
    p = B.snapshot(m)["player"]
    bot.timer_since = now[0] - 2.0
    assert bot._dialog_answer(p, now[0]) == "a"


def test_no_blind_vault_tap_where_a_take_prompt_would_pick_the_item_up():
    now = [0.0]
    m = world([], room=0x400, leon=(100.0, 7.0, 200.0), timer_s=100.0)
    bot = B.Bot(m, clock=lambda: now[0], nav=False)
    bot.stats["ram_action"] = "TAKE"                                      # ammo at his feet
    facing(m, B.heading(5592.0 - 100.0, 16384.0 - 200.0))
    acts = []
    for t in range(1, 16):
        now[0] = t * 0.1
        m.put(B.MERC_TIMER, ">I", int((100 - now[0]) * 30))
        acts.append(bot.tick(B.snapshot(m)))
    assert {"tap": "a"} not in acts and bot.stats["vaults_skipped_for_pickup"] == 1 and bot.stats["detours"] >= 1


class ItemRam:
    """re4_ram_prompts.items_from_ram's rows for the item scan."""

    def __init__(self, rows):
        self.rows = rows

    def __call__(self, m, entries=None):
        return [dict(r) for r in self.rows]


def test_pickups_are_counted_by_kind_and_an_ammo_spot_is_remembered(monkeypatch, tmp_path):
    now = [0.0]
    m = world([], room=0x400, leon=(0.0, 0.0, 0.0), timer_s=100.0)
    bot = B.Bot(m, clock=lambda: now[0], nav=False, learn_dir=tmp_path)
    rows = [{"addr": 0x80400000, "item_id": 0x04, "pos": [300.0, 0.0, 300.0], "enabled": True},     # handgun ammo
            {"addr": 0x80400100, "item_id": B.re4_ram_prompts and 0x73, "pos": [9000.0, 0.0, 0.0], "enabled": True}]
    ram = ItemRam(rows)
    monkeypatch.setattr(B.re4_ram_prompts, "items_from_ram", ram)
    bot.tick(B.snapshot(m))
    ram.rows = rows[1:]                                                   # the ammo is gone while he stands by it
    now[0] = 1.0
    m.put(B.MERC_TIMER, ">I", int((100 - now[0]) * 30))
    bot.tick(B.snapshot(m))
    s = bot.metrics.summary()
    assert s["pickups"] == {"ammo": 1} and s["ammo_pickups"] == 1
    assert bot.knowledge.near_ammo_spot(300.0, 300.0)


def test_a_time_bonus_walked_past_within_reach_is_counted():
    met = BM.BehaviorMetrics()
    hg = [("hg1", (1000.0, 0.0))]
    for x in (-3000.0, -1000.0, 0.0, 800.0, 2500.0, 4500.0):             # past it within a metre, on and away
        met.bonus_tick((x, 0.0), hg)
    met.bonus_tick((9000.0, 0.0), [("hg2", (0.0, 9000.0))])
    s = met.summary()
    assert s["bonuses_passed"] == 1 and s["bonuses_passed_at"][0]["closest_mm"] <= 1000


def test_a_time_bonus_the_route_passes_comes_first():
    bot = B.Bot(world([], room=0x400), nav=False)
    bot._round(0x400)
    far, near = item("time_bonus", 0.0, 20000.0), item("time_bonus", 1500.0, 1500.0)
    bot.items = [far, near]
    bot._bonus_detour({"pos": (0.0, 0.0, 0.0), "rot": 0.0}, 10.0)
    assert bot.items[0] is near and bot.stats["bonus_detours"] == 1
    bot.items = [far, item("time_bonus", 0.0, 9000.0)]                    # nothing near: the tour's order stays
    bot._bonus_detour({"pos": (0.0, 0.0, 0.0), "rot": 0.0}, 20.0)
    assert bot.items[0] is far


# --- chickens -------------------------------------------------------------------------------------------------------
def test_chickens_are_shot_only_when_his_health_is_low_and_only_with_the_aim_on_them():
    """Operator: "if he's going to shoot these chickens, he's going to need to aim at these chickens"."""
    now = [0.0]
    m = world([((0, 0, 2000), True)])                                     # 2 m: past the low aim's reach (1.74 m)
    m.put(EM + STRIDE + B.EM_HP, ">hh", 10, 10)                           # a chicken
    facing(m, 0.0)
    m.put(PG + B.G_HP, ">h", 1000)
    bot = B.Bot(m, clock=lambda: now[0], nav=False)
    acts = run(bot, m, now, 0.0, 10)
    assert not any("a" in a.get("hold", set()) or "r" in a.get("hold", set()) for a in acts)   # healthy: ignored
    m.put(PG + B.G_HP, ">h", 300)                                         # low: its eggs heal - now it is a target
    set_pitch(m, -0.5)                                                    # (the aim down on it)
    acts = run(bot, m, now, now[0] + 0.05, 12)
    assert any("r" in a.get("hold", set()) for a in acts) and bot.stats["phase"] == "fight"
    s = B.snapshot(m)
    chick = {"slot": 1, "pos": (0.0, 0.0, 2000.0), "hp": 10, "hp_max": 10}
    ganado = dict(chick, hp=1000, hp_max=1000)
    facing(m, -0.075)                     # 0.075 rad off at 2 m: inside a Ganado's window (0.09), off the chicken (0.06)
    for tgt, gate in ((chick, "off target: hold"), (ganado, None)):
        b = B.Bot(m, clock=lambda: now[0], nav=False)
        b.hp_best, b.r_since = 1000, now[0] - 1.0
        act = b._fight(B.snapshot(m)["player"], tgt, now[0], s)
        if gate:
            assert "a" not in act["hold"] and b.stats["fire_gate"] == gate          # no shot past the chicken's width
        else:
            assert b.stats["fire_gate"] != "off target: hold"


# --- the metrics and the audit ----------------------------------------------------------------------------------------
def test_the_behaviour_block_names_each_wayward_action_in_the_round_audit():
    met = BM.BehaviorMetrics()
    for k in range(40):                                                   # a sine wave: wide and back and forth
        met.run_tick(0.1, 1400.0 if k % 2 else 200.0, 1 if (k // 2) % 2 else -1)
    met.raise_gun(0.0)
    for k in range(40):                                                   # waving: reversals, switches
        met.aim_tick(0.1, 0.3, 1.0, 1 if k % 2 else -1, k % 3)
    for k in range(10):
        met.shot(1.0 + k * 0.1, on_target=k < 3)
    met.shot(3.0, on_target=False, small=True)
    met.pickup("ammo", 0x04, (0.0, 0.0))
    met.portals["p"] = {"pos": [0, 0], "passes": 0, "bumps": 3}
    met.bonus_passed.append({"id": "hg", "at": [0, 0], "closest_mm": 600})
    met.fire_tick("handgun", 2.5, True, 4)
    met.fire_tick("machine gun", 2.5, True, 60)
    trace = RoundTrace(None, "G4BE08", "r400", "r1", 400.0)
    for k in range(40):
        trace.add(k * 0.25, k * 300.0, 0.0, 0.0, {"phase": "fight"})
    trace.annex["behavior"] = met.summary()
    audit, stats = RoundAudit("G4BE08"), {"rounds": 1, "character": "Ada",
                                          "round_loadout": {"round": 1, "verified": True, "fire_applied": True}}
    audit.start(stats)
    trace.auditor = lambda summary, tr: audit.finish(summary, tr, stats)
    probs = " | ".join(trace.finish()["audit"]["problems"])
    for want in ("path weave", "gun waving", "shots outside the on-target window", "doorways: 1 portal",
                 "1 ammo pickup", "1 time bonus(es) passed", "1 chicken shot(s) without the aim",
                 "not blasting: handgun 1.6 shots/s"):
        assert want in probs, (want, probs)
    assert "machine gun" not in probs.split("not blasting:")[1]          # 24 shots/s: blasting


def test_shots_are_credited_to_the_tick_that_fired_them_and_the_fire_rate_is_per_weapon_class():
    now = [0.0]
    m = world([((0, 0, 1500), True)])
    facing(m, 0.0)
    m.put(B.ITEM_MGR + 0x10, ">H", 0x30)                                  # the TMP
    bot = B.Bot(m, clock=lambda: now[0], nav=False)
    run(bot, m, now, 0.0, 8)                                              # on him, the trigger going
    bot._on_target, bot._fire_held = True, True
    bot.shots.fired(now[0])                                               # the game fired twice since
    bot.shots.fired(now[0])
    bot._fire_at = now[0] - 0.1
    bot._shot_metrics(B.snapshot(m), now[0])
    s = bot.metrics.summary()
    assert s["aim"]["shots_on_target"] >= 2 and s["fire_rate"]["machine gun"]["shots"] >= 2


def test_the_round_map_carries_the_behaviour_block_and_the_stage_knowledge(tmp_path):
    now = [0.0]
    bot = B.Bot(world([]), clock=lambda: now[0], nav=False, learn_dir=tmp_path, round_maps_dir=tmp_path / "maps")
    bot.stats.update(rounds=1, character="Leon")
    bot._round(0x400)
    bot.trace_start("round-one")
    for k in range(20):
        bot.trace.add(k * 0.25, k * 400.0, 0.0, 0.0, {"phase": "run_to_target"})
    bot.metrics.pickup("ammo", 0x04, (0.0, 0.0))
    bot.trace_finish()
    d = json.loads(next((tmp_path / "maps" / "r400").glob("*.json")).read_text())
    assert d["behavior"]["ammo_pickups"] == 1 and d["stage_knowledge"]["rounds"] == 1
    assert "1 ammo pickup" in " | ".join(d["audit"]["problems"]) and bot.stats["behavior"]["pickups"] == {"ammo": 1}
    assert json.loads((tmp_path / "r400-knowledge.json").read_text())["rounds"] == 1


# --- "look at the bot" (stats["look"], gbox.mercs.bot_look) ----------------------------------------------------------
def fire_ram(m, firing=True):
    """Leon's routine: 00 06 02 (the fire motion) or 00 06 01 (aiming)."""
    m.put(PL + B.threats_ram.EM_ROUTINE, "4B", 0, B.AIM_R1, 2 if firing else 1, 0)


def test_a_shot_that_hurts_its_target_shows_in_the_look_as_a_hit():
    """Operator 2026-10-26: "when i say 'look at the bot' i want you able to see the last things and results of the last
    bullets being fired by the bot"."""
    now = [0.0]
    m = world([((0, 0, 1500), True)])
    facing(m, 0.0)
    fire_ram(m, firing=False)                                             # the aim pose: shots are read from RAM
    bot = B.Bot(m, clock=lambda: now[0], nav=False)
    acts = run(bot, m, now, 0.0, 8)                                       # on him, the trigger going
    assert any("a" in a["hold"] for a in acts) and bot.shots.stats["shots"] == 0
    fire_ram(m)                                                           # the game fires
    run(bot, m, now, now[0] + 0.05)
    m.put(EM + STRIDE + B.EM_HP, ">hh", 940, 1000)                        # ... and his health falls
    run(bot, m, now, now[0] + 0.05)
    shot = bot.look.snapshot()["shots"][-1]
    assert shot["target"] == {"id": "1", "kind": "ganado", "dist_m": 1.5, "bearing_deg": 0.0}
    assert shot["gate"] == "on him" and shot["dot_on"] == "target" and shot["weapon"]
    assert shot["outcome"] == "hit:ganado" and shot["hp_delta"] == -60 and shot["aim_err_deg"] == 0.0
    assert bot.metrics.summary()["shot_outcomes"] == {"hit": 1}


def test_a_shot_that_hurts_nobody_is_a_miss_with_its_cause():
    now = [0.0]
    m = world([((0, 0, 1500), True)])
    facing(m, 0.0)
    fire_ram(m, firing=False)
    bot = B.Bot(m, clock=lambda: now[0], nav=False)
    run(bot, m, now, 0.0, 8)
    fire_ram(m)
    run(bot, m, now, now[0] + 0.05, 14)                                   # past the hit window, no health lost
    shot = bot.look.snapshot()["shots"][0]
    assert shot["outcome"] == "miss:no_damage" and shot["hp_delta"] is None   # the line was on him: no damage done


def test_no_shot_while_the_aim_line_meets_a_wall_and_the_target_is_left_after_a_while():
    """Operator: "They are shooting at walls" - the level map's sight line let the shot through, the aim line did not."""
    now = [0.0]
    m = world([((0, 0, 2000), True)])
    facing(m, 0.0)
    bot = B.Bot(m, clock=lambda: now[0], nav=False)
    run(bot, m, now, 0.0, 1)
    bot.st = {"walls": [[-2000.0, 1000.0, 2000.0, 1000.0, -1000.0, 3000.0, 0.0]]}   # a wall 1 m ahead (the map's
    acts = run(bot, m, now, now[0] + 0.05, 10)                                     # sight line is off: nav=False)
    assert not any("a" in a.get("hold", set()) for a in acts) and any("r" in a.get("hold", set()) for a in acts)
    assert bot.stats["fire_gate"] == "aim line on a wall: hold" and bot.stats["wall_line_holds"] >= 5
    assert bot.look.snapshot()["decisions"][-1]["decision"] == "hold fire"
    run(bot, m, now, now[0] + 0.05, 30)                                   # 1.5 s of it: he is left, the next one taken
    assert bot.stats["wall_line_skips"] == 1 and bot.skip.get(1, 0) > now[0]
    assert bot._aim_line(B.snapshot(m)["player"] | {"pitch": 0.0}, B.snapshot(m))[0] in ("wall", "off")


def test_the_aim_line_names_what_it_meets_first():
    bot = bare_bot()
    bot.r_since = 0.0
    s = {"enemies": [{"slot": 4, "pos": (0.0, 0.0, 3000.0), "hp": 500, "hp_max": 500, "r": (1, 3, 0, 0)}]}
    p = {"pos": (0.0, 0.0, 0.0), "rot": 0.0, "aim_rot": 0.0, "pitch": 0.0}
    assert bot._aim_line(p, s)[0::2] == ("target", 4)
    assert bot._aim_line(dict(p, aim_rot=0.4), s)[0] == "none"            # beside him: nothing in range
    assert bot._aim_line(dict(p, pitch=-0.6), s)[0] == "floor"            # aimed into the ground before him
    bot.st = {"walls": [[-500.0, 2000.0, 500.0, 2000.0, -1000.0, 3000.0, 0.0]]}
    kind, dist, _ = bot._aim_line(p, s)
    assert kind == "wall" and dist == pytest.approx(2000.0)
    bot.st = {"walls": [[-500.0, 2000.0, 500.0, 2000.0, -1000.0, 3000.0, float(0x20)]]}   # a fence: bullets go through
    assert bot._aim_line(p, s)[0] == "target"
    bot.r_since = None
    assert bot._aim_line(p, s)[0] == "off"                                # the gun is down


def test_sitting_among_foes_is_timed_in_the_look_and_flagged_by_the_round_audit(tmp_path):
    """Operator: "just sitting here amongst foes" - here he turns to a Ganado behind him and never comes round (the
    fake Leon does not turn): neither moving nor shooting with a foe 1.5 m away."""
    now = [0.0]
    m = world([((0, 0, -1500), True)])
    facing(m, 0.0)
    bot = B.Bot(m, clock=lambda: now[0], nav=False, round_maps_dir=tmp_path / "maps")
    bot.stats.update(rounds=1, character="Leon")
    bot._round(0x400)
    bot.trace_start("idle-round")
    run(bot, m, now, 0.0, 80)                                             # 4 s
    snap = bot.look.snapshot()
    assert snap["idle_among_foes_s"] >= 3.5 and bot.stats["look"]["idle_among_foes_s"] >= 3.0
    assert snap["decisions"][-1]["phase"] == "fight" and snap["decisions"][-1]["decision"] in ("turn", "quick turn")
    for k in range(20):
        bot.trace.add(k * 0.25, 0.0, 0.0, 0.0, {"phase": "fight"})
    bot.trace_finish()
    d = json.loads(next((tmp_path / "maps").rglob("*.json")).read_text())
    assert d["behavior"]["idle_among_foes"]["max_s"] >= 3.5
    assert any(p.startswith("sat among foes") for p in d["audit"]["problems"])


def test_the_look_starts_a_new_round_with_its_counters_cleared_and_its_last_shots_kept():
    bot = bare_bot()
    bot.look.record_shot("Handgun (0x23)", "on him", None, None, "wall")
    bot._look_pending = [None]
    bot.new_round()
    snap = bot.look.snapshot()
    assert snap["walls_shot"] == 0 and len(snap["shots"]) == 1 and bot._look_pending == []


def test_the_audit_flags_a_round_of_wall_shots():
    met = BM.BehaviorMetrics()
    for k in range(20):
        met.shot_line("wall" if k < 6 else "target")
    met.shot_result("miss:wall")
    s = met.summary()
    assert s["walls_shot"] == 6 and s["shot_lines"] == {"wall": 6, "target": 14} and s["shot_outcomes"] == {"miss:wall": 1}
    trace = RoundTrace(None, "G4BE08", "r400", "r2", 400.0)
    for k in range(40):
        trace.add(k * 0.25, k * 300.0, 0.0, 0.0, {"phase": "fight"})
    trace.annex["behavior"] = s
    audit, stats = RoundAudit("G4BE08"), {"rounds": 1, "character": "Leon",
                                          "round_loadout": {"round": 1, "verified": True, "fire_applied": True}}
    audit.start(stats)
    trace.auditor = lambda summary, tr: audit.finish(summary, tr, stats)
    assert "shooting walls: 6 of 20 shots had the aim line on a wall" in trace.finish()["audit"]["problems"]
