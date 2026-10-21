"""RE5 combat layer (gbox.mercs.titles.re5_combat): the laser dot decides the shot, the trigger per weapon, shots
seen from the action object, headshots scored, the aim pitch written, the tunables kept."""
import json
import math
import struct

import pytest

from gbox.mercs.titles import re5_combat as C

PL, ACT, LASER, SUNIT, ENEMY = 0x30400000, 0x30500000, 0x30600000, 0x30700000, 0x30800000


class FakeMem:
    """Guest memory as a dict of pages; writable through write() (like a Guest opened r+b)."""

    def __init__(self):
        self.b = {}
        self.writable = True
        self.writes = []

    def rd(self, a, n):
        return bytes(self.b.get(a + i, 0) for i in range(n))

    def write(self, a, data):
        self.writes.append((a, data))
        for i, v in enumerate(data):
            self.b[a + i] = v

    def put(self, a, fmt, *v):
        self.write(a, struct.pack(fmt, *v))


def world(laser_dot=(0.0, 160.0, 400.0), aiming=True, rounds=10, act_vt=C.READY_VT, frames=0.0, enemy=(0.0, 0.0, 400.0)):
    m = FakeMem()
    m.put(C.S_PLAYER, ">I", 0x30300000)
    m.put(0x30300000 + 0x28, ">I", PL)
    m.put(PL, ">I", 0x016172B8)                                      # Barry
    m.put(PL + C.P_ACTION, ">B", C.AIMING if aiming else 0)
    m.put(PL + C.P_PITCH, ">f", 0.0)
    m.put(PL + C.P_ACTION_OBJ, ">I", ACT)
    m.put(ACT, ">I", act_vt)
    m.put(ACT + C.ACT_FRAMES, ">f", frames)
    o = PL + C.P_INV + 3 * C.INV_SLOT                                 # slot 3 in hand: weapon 0x12, rounds
    m.put(o + C.INV_ID, ">I", 0x0112)
    m.put(o + C.INV_ROUNDS, ">i", rounds)
    m.put(o + C.INV_HAND, ">I", 1)
    m.put(o + C.INV_USED, ">B", 1)
    m.put(C.S_UNIT, ">I", SUNIT)
    m.put(SUNIT + C.UNIT_LINES + C.LINE_STRIDE * C.FX_LINE + C.LINE_FIRST, ">I", LASER)
    m.put(LASER, ">I", C.LASER_VT)
    m.put(LASER + C.LASER_ORIGIN, ">3f", 0.0, 149.0, 46.0)
    m.put(LASER + C.LASER_DOT, ">3f", *laser_dot)
    return m


def snap(m, enemy=(0.0, 0.0, 400.0), hp=800):
    aiming = m.rd(PL + C.P_ACTION, 1)[0] == C.AIMING
    return {"player": {"ptr": PL, "pos": (0.0, 0.0, 0.0), "rot": 0.0, "hp": 1000, "hp_max": 1000, "action": C.AIMING if aiming else 0},
            "enemies": [{"slot": 0, "ptr": ENEMY, "pos": enemy, "hp": hp, "hp_max": 800}], "timer": 100.0, "combo": 0, "combo_timer": 0}


def test_the_dot_names_where_it_sits_on_a_majini():
    assert C.dot_on((0, 160, 400), (0, 0, 400)) == "head"
    assert C.dot_on((20, 100, 390), (0, 0, 400)) == "body"
    assert C.dot_on((0, 20, 400), (0, 0, 400)) is None                 # the ground at his feet
    assert C.dot_on((80, 100, 400), (0, 0, 400)) is None                # beside him
    assert C.dot_on((0, 160, 700), (0, 0, 400)) is None                 # past him


def test_missing_equipped_weapon_does_not_crash_or_fire():
    m = world()
    m.put(PL + C.P_INV + 3 * C.INV_SLOT + C.INV_HAND, ">I", 0)
    bot = C.Combat(m, {}, learn_dir=None)
    s = snap(m)
    action = bot.tick(s, s["player"], s["enemies"][0], 1.0)
    assert "r1" not in action["hold"]
    assert "unknown" in bot.stats["combat"]


def test_the_ray_error_is_the_turn_that_puts_the_dot_on_the_head():
    yaw, pitch = C.ray_error((0, 150, 0), (0, 150, 1000), (100, 250, 1000))
    assert math.degrees(yaw) == pytest.approx(5.71, abs=0.05) and math.degrees(pitch) == pytest.approx(5.68, abs=0.05)


@pytest.mark.parametrize("yaw_sign,pitch_sign", [(1, 1), (1, -1), (-1, 1), (-1, -1)])
def test_tracking_small_diagonal_errors_does_not_starve_either_axis(tmp_path, yaw_sign, pitch_sign):
    # A moving target can retain small yaw and pitch errors across many snapshots.
    # Sharing one toggle made the yaw call consume every "on" pulse and pitch consume every "off" pulse.
    distance = 1500.0 - 46.0
    yaw = -yaw_sign * math.radians(2)
    pitch = math.atan2(160.0 - 149.0, distance) - pitch_sign * math.radians(2)
    dot = (distance * math.tan(yaw), 149.0 + distance / math.cos(yaw) * math.tan(pitch), 1500.0)
    m = world(laser_dot=dot)
    bot = C.Combat(m, {}, learn_dir=tmp_path, lessons=lambda row: None)
    yaw_key, pitch_key = ("rleft" if yaw_sign > 0 else "rright"), ("rup" if pitch_sign > 0 else "rdown")
    actions = []
    for frame in range(6):
        s = snap(m, enemy=(0.0, 0.0, 1500.0))
        actions.append(bot.tick(s, s["player"], s["enemies"][0], frame * 0.05)["hold"])
    assert sum(yaw_key in keys for keys in actions) >= 2
    assert sum(pitch_key in keys for keys in actions) >= 2
    assert all("r1" not in keys for keys in actions)  # diagonal correction never authorizes a speculative shot


def test_fires_immediately_on_an_exposed_body_and_keeps_the_dot_on_it():
    far = (0.0, 0.0, 1000.0)                                            # beyond FINISHER_SETUP_R: the head
    m = world(laser_dot=(0.0, 120.0, 1000.0), enemy=far)               # on his chest, 40 cm under the head
    bot = C.Combat(m, {}, clock=lambda: 0.0, learn_dir=None)
    s = snap(m, enemy=far)
    tgt = s["enemies"][0]
    act = bot.tick(s, s["player"], tgt, 0.0)
    assert bot.zone == "head"
    assert {"r1", "l1"} <= act["hold"]                            # current first-hit overlap: no body-shot delay
    assert not ({"rup", "rdown"} & act["hold"])                      # keep the already exposed body under the dot
    m.put(LASER + C.LASER_DOT, ">3f", 0.0, 162.0, 998.0)               # the game's dot now on the head
    t = 0.05
    fired = False
    while t < 0.5:
        act = bot.tick(s, s["player"], tgt, t)
        fired = fired or "r1" in act["hold"]
        t += 0.02
    assert fired                                                        # settled on the head: the trigger


def test_no_shot_with_the_dot_beside_him_or_on_the_floor():
    for dot in ((90.0, 120.0, 400.0), (0.0, 30.0, 400.0), (0.0, 160.0, 900.0)):
        m = world(laser_dot=dot)
        bot = C.Combat(m, {}, clock=lambda: 0.0)
        s = snap(m)
        for k in range(30):
            act = bot.tick(s, s["player"], s["enemies"][0], k * 0.02)
            assert "r1" not in act["hold"], dot


def test_a_body_shot_does_not_wait_for_a_preferred_head_or_leg_zone():
    m = world(laser_dot=(0.0, 100.0, 400.0))
    bot = C.Combat(m, {}, clock=lambda: 0.0)
    s = snap(m)
    act = bot.tick(s, s["player"], s["enemies"][0], 0.0)
    assert "r1" in act["hold"]


def test_shots_are_seen_from_the_action_object_and_headshots_scored():
    m = world(laser_dot=(0.0, 160.0, 400.0))
    bot = C.Combat(m, {}, clock=lambda: 0.0)
    s = snap(m)
    tgt = s["enemies"][0]
    bot.tick(s, s["player"], tgt, 0.0)
    m.put(ACT, ">I", C.FIRE_VT)                                         # the game fires
    m.put(ACT + C.ACT_FRAMES, ">f", 1.0)
    bot.tick(s, s["player"], tgt, 0.3)
    assert bot.stats["shots"] == 1
    s2 = snap(m, hp=600)                                                # his health fell
    bot.tick(s2, s2["player"], s2["enemies"][0], 0.4)
    assert bot.stats["hits"] == 1 and bot.stats["headshots"] == 1 and bot.stats["accuracy"] == 1.0
    assert bot.stunned_target(s2["enemies"], s2["player"], 0.5) is tgt or bot.stunned.get(ENEMY)
    m.put(ACT + C.ACT_FRAMES, ">f", 0.0)                                # the next shot: the counter starts over
    bot.tick(s2, s2["player"], s2["enemies"][0], 0.6)
    assert bot.stats["shots"] == 2
    for k in range(30):                                                 # nothing lost health: a miss
        bot.tick(s2, s2["player"], s2["enemies"][0], 0.7 + k * 0.02)
    assert bot.stats["misses"] == 1 and bot.stats["accuracy"] == 0.5


def test_a_held_r1_that_fires_once_turns_into_taps():
    tr = C.Trigger("hold")
    keys = [tr.keys(t * 0.02, True, t == 2) for t in range(60)]        # one shot at the start, then nothing
    assert tr.mode == "tap"
    downs = sum(1 for k in keys[30:] if "r1" in k)
    assert 0 < downs < 30                                               # tapping: down some ticks, up others
    tr2 = C.Trigger("tap")
    modes = set()
    for t in range(200):                                                # taps fire nothing: a hold is tried
        tr2.keys(t * 0.02, True, False)
        modes.add(tr2.mode)
    assert modes == {"tap", "hold"}                                     # (and back: it keeps trying both)


def test_an_empty_weapon_is_reloaded():
    m = world(laser_dot=(0.0, 160.0, 400.0), rounds=0)
    bot = C.Combat(m, {}, clock=lambda: 0.0)
    s = snap(m)
    act = bot.tick(s, s["player"], s["enemies"][0], 0.0)
    assert act["hold"] >= {"l1", "cross"} and "r1" not in act["hold"] and bot.stats["reloads"] == 1


def test_the_tunables_are_kept_and_tightened_after_a_poor_round(tmp_path):
    m = world(laser_dot=(0.0, 160.0, 400.0))
    bot = C.Combat(m, {}, clock=lambda: 0.0, learn_dir=tmp_path)
    s = snap(m)
    bot.tick(s, s["player"], s["enemies"][0], 0.0)
    bot.round_counts.update(shots=10, hits=5)
    bot.save()
    d = json.loads((tmp_path / C.TUNABLES_FILE).read_text())
    w = d["weapons"]["barry:0x12"]
    assert w["head_r"] < C.HEAD_R and w["settle_s"] > C.SETTLE_S and d["rounds"][-1]["hit_rate"] == 0.5
    bot2 = C.Combat(world(), {}, learn_dir=tmp_path)
    assert bot2.tun.weapon("barry", 0x12)["head_r"] == w["head_r"]   # the next round starts from it


def test_a_near_majini_gets_the_leg_for_the_stun_and_a_far_one_the_head():
    assert C.zone_for({"hp_max": 800}, 400.0, 8.0, 3) == "leg"
    assert C.zone_for({"hp_max": 800}, 400.0, 2.0, 3) == "head"          # the combo window is short: a kill now
    assert C.zone_for({"hp_max": 800}, 400.0, None, 0) == "leg"          # no combo running
    assert C.zone_for({"hp_max": 800}, 900.0, 8.0, 3) == "head"          # too far for the finisher setup
    assert C.zone_for({"hp_max": 9000}, 300.0, 8.0, 3) == "head"         # a boss: no melee setup
    assert C.zone_for({"hp_max": 800, "zone": "head"}, 300.0, 8.0, 3) == "head"   # the strategy's say
    m = world(laser_dot=(0.0, 72.0, 400.0))                             # the dot on his thighs
    bot = C.Combat(m, {}, clock=lambda: 0.0)
    s = snap(m)
    fired = False
    for k in range(20):
        act = bot.tick(s, s["player"], s["enemies"][0], k * 0.02)
        fired = fired or "r1" in act["hold"]
    assert bot.zone == "leg" and fired
    m.put(ACT, ">I", C.FIRE_VT)                                         # the shot leaves, his health falls
    m.put(ACT + C.ACT_FRAMES, ">f", 1.0)
    bot.tick(s, s["player"], s["enemies"][0], 0.5)
    s2 = snap(m, hp=500)
    bot.tick(s2, s2["player"], s2["enemies"][0], 0.55)
    assert bot.stats["legshots"] == 1 and ENEMY in bot.stunned          # a leg hit: he kneels, in for the finisher
    assert bot.stunned_target(s2["enemies"], s2["player"], 0.6) is s2["enemies"][0]
    assert bot.run_to(s2["player"], s2["enemies"][0])["hold"] >= {"lup", "cross"}


def test_a_boss_gets_one_finisher_only():
    m = world()
    bot = C.Combat(m, {}, clock=lambda: 0.0)
    boss = {"slot": 0, "ptr": ENEMY, "pos": (0.0, 0.0, 150.0), "hp": 9000, "hp_max": 9000}
    s = {"player": snap(m)["player"], "enemies": [boss], "prompt": "square", "prompt_target": ENEMY}
    assert bot.prompt_ok("square", s, 1.0) is True                      # the first finisher
    assert bot.prompt_ok("square", s, 3.0) is False                     # never the wild swing
    assert bot.prompt_ok("wiggle", s, 3.0) is True
    assert bot.stunned_target([boss], s["player"], 3.5) is None          # and no running in for another


def test_hourglasses_do_not_split_round_accuracy(tmp_path):
    bot = C.Combat(world(), {}, learn_dir=tmp_path, lessons=lambda e: None)
    bot._clock({"timer": 60.0}, 1.0)
    bot.round_counts.update(shots=10, hits=7)
    for timer in (90.0, 150.0, 240.0):
        bot._clock({"timer": timer}, 2.0)
    assert bot.round_t0 == 1.0 and bot.round_counts["shots"] == 10 and bot.round_counts["hits"] == 7
    assert bot.round_counts["time_gained_s"] == 180.0 and bot.tun.d["rounds"] == []
    bot.end_round(3.0)
    bot.end_round(4.0)    # repeated dead frames only finalize once
    assert len(bot.tun.d["rounds"]) == 1 and bot.tun.d["rounds"][0]["hit_rate"] == 0.7
    bot.start_round(5.0)
    bot._clock({"timer": 120.0}, 5.0)
    assert bot.round_counts["shots"] == 0 and bot.round_counts["time_gained_s"] == 0.0


def test_restart_resolves_pending_shots_before_enemy_slots_are_reused(tmp_path):
    bot = C.Combat(world(), {}, learn_dir=tmp_path, lessons=lambda e: None)
    bot.start_round(0.0)
    bot.shots.update([{"slot": 0, "hp": 800}], 0.0)
    bot._on_shot(1.0)
    bot.end_round(1.1)
    assert bot.stats["shots"] == bot.stats["misses"] == 1 and bot.stats["hits"] == 0
    bot.start_round(2.0)
    bot.shots.update([{"slot": 0, "hp": 600}], 2.0)
    bot._score(2.0)
    assert bot.stats["hits"] == 0 and bot.stats["round_shots"] == 0


def test_shot_classification_uses_its_own_cursors_not_shared_telemetry():
    m = world(laser_dot=(0.0, 160.0, 1000.0))
    bot = C.Combat(m, {"hits": 99, "misses": 99}, lessons=lambda e: None)
    s = snap(m, enemy=(0.0, 0.0, 1000.0))
    bot.tick(s, s["player"], s["enemies"][0], 0.0)
    m.put(ACT, ">I", C.FIRE_VT)
    bot.tick(s, s["player"], s["enemies"][0], 0.2)
    bot.stats["hits"] = 99
    s = snap(m, enemy=(0.0, 0.0, 1000.0), hp=600)
    bot.tick(s, s["player"], s["enemies"][0], 0.3)
    assert bot.stats["shots"] == bot.stats["hits"] == bot.stats["headshots"] == 1
    assert bot.stats["round_hits"] == 1 and bot.stats["round_accuracy"] == 1.0


def test_prompt_frames_score_pending_hits_and_the_same_frame_is_observed_once(tmp_path):
    from gbox.mercs.titles import re5_ps3 as R

    m, now = world(act_vt=0xDEADBEEF), [0.0]
    bot = R.Bot(m, clock=lambda: now[0], learn_dir=tmp_path, lessons=lambda e: None)
    bot.combat.infinite = True
    first = snap(m)
    bot.observe_round(first, "playing", 0.0)
    m.put(PL + C.P_FIRE_CMD, ">I", 4)
    fire = snap(m)
    fire["prompt"] = "square"
    bot.observe_round(fire, "playing", 0.2)  # engine observation before prompt dispatch
    now[0] = 0.3                           # >25 ms: fallback fire command could otherwise count twice
    assert bot.tick(fire) == {"hold": set()}
    bot.combat.tick(fire, fire["player"], fire["enemies"][0], 0.3, observed=True)
    assert bot.stats["shots"] == 1
    m.put(PL + C.P_FIRE_CMD, ">I", 0)
    hit = snap(m, hp=600)
    hit["prompt"] = "square"
    now[0] = 0.4
    assert bot.tick(hit) == {"hold": set()}
    assert bot.stats["hits"] == bot.stats["round_hits"] == 1 and bot.stats["misses"] == 0


def test_death_snapshot_resolves_a_landed_shot_before_round_finalization(tmp_path):
    from gbox.mercs.titles import re5_ps3 as R

    m = world()
    bot = R.Bot(m, learn_dir=tmp_path, lessons=lambda e: None)
    bot.observe_round(snap(m), "playing", 0.0)
    m.put(ACT, ">I", C.FIRE_VT)
    bot.observe_round(snap(m), "playing", 0.2)
    dead = snap(m, hp=600)
    dead["player"]["hp"] = 0
    bot.observe_round(dead, "dead", 0.3)
    assert bot.stats["shots"] == bot.stats["hits"] == 1 and bot.stats["misses"] == 0
    assert bot.combat.tun.d["rounds"][-1]["hit_rate"] == 1.0


def test_gathering_a_bonus_updates_combat_clock_without_a_combat_decision(tmp_path):
    from gbox.mercs.titles import re5_ps3 as R

    m = world()
    bot = R.Bot(m, clock=lambda: 10.0, learn_dir=tmp_path, lessons=lambda e: None)
    for timer in (60.0, 120.0):
        s = snap(m)
        s.update(timer=timer, enemies=[], bonuses=[{"ptr": 1, "pos": (0.0, 0.0, 2000.0), "kind": "time"}])
        bot.tick(s)
        assert bot.stats["phase"] == "gather_time"
    assert bot.combat.round_counts["time_gained_s"] == 60.0 and bot.combat.tun.d["rounds"] == []


def test_loading_gap_clears_combat_clock_health_and_action_baselines(tmp_path):
    m = world()
    bot = C.Combat(m, {}, learn_dir=tmp_path, lessons=lambda e: None)
    bot.observe(snap(m), 0.0)
    bot._on_shot(0.1)
    bot.suspend_observation(0.2)
    after = snap(m, hp=600)
    after["timer"] = 160.0
    bot.observe(after, 1.0)
    assert bot.stats["hits"] == 0 and bot.stats["misses"] == 1
    assert bot.round_counts["time_gained_s"] == 0.0


def test_fresh_combat_resets_all_shot_classification_counters_together():
    stats = {"shots": 8, "hits": 6, "headshots": 4, "legshots": 2, "misses": 2, "miss_short": 1, "miss_moved": 1}
    C.Combat(world(), stats, lessons=lambda e: None)
    assert all(stats[k] == 0 for k in ("shots", "hits", "headshots", "legshots", "misses", "miss_short", "miss_moved"))


def test_verified_rapid_fire_holds_only_while_the_first_hit_is_on_an_enemy():
    m = world(laser_dot=(0.0, 110.0, 1000.0))
    m.put(C.FIRE_TIMER_FPS, ">f", C.FIRE_TIMER_ORIG * 80)
    m.put(C.WEAPON_TABLE + 0x12 * C.WEAPON_STRIDE + C.WEAPON_INTERVAL, ">f", 0.0)
    bot = C.Combat(m, {}, lessons=lambda e: None)
    s = snap(m, enemy=(0.0, 0.0, 1000.0))
    for t in (0.0, 0.05, 0.1, 0.15):
        assert "r1" in bot.tick(s, s["player"], s["enemies"][0], t)["hold"]
    assert bot.stats["rapid_fire_verified"] is True
    m.put(LASER + C.LASER_DOT, ">3f", 0.0, 135.0, 400.0)  # first hit on intervening cover
    assert "r1" not in bot.tick(s, s["player"], s["enemies"][0], 0.2)["hold"]
    s["laser"] = None
    assert "r1" not in bot.tick(s, s["player"], s["enemies"][0], 0.25)["hold"]
    assert "laser=no" in bot.stats["combat"]


def test_measured_exposed_enemy_wins_over_a_nearer_front_candidate():
    m = world(laser_dot=(0.0, 110.0, 1000.0))
    bot = C.Combat(m, {}, lessons=lambda e: None)
    s = snap(m, enemy=(0.0, 0.0, 1000.0))
    exposed = s["enemies"][0]
    nearer = {"slot": 1, "ptr": ENEMY + 1, "pos": (150.0, 0.0, 400.0), "hp": 800, "hp_max": 800}
    assert bot.choose_target(s, s["player"], [nearer, exposed], 0.0) is exposed
    assert bot.stats["target_evidence"] == "laser first hit on enemy"


def test_actual_first_hit_overrides_camera_sector_for_a_close_low_enemy_until_dead():
    foot, impact = (0.0, -180.0, 70.0), (0.0, -70.0, 70.0)
    m = world(laser_dot=impact)
    m.put(C.FIRE_TIMER_FPS, ">f", C.FIRE_TIMER_ORIG * 80)
    m.put(C.WEAPON_TABLE + 0x12 * C.WEAPON_STRIDE + C.WEAPON_INTERVAL, ">f", 0.0)
    bot = C.Combat(m, {}, lessons=lambda e: None)
    s = snap(m, enemy=foot)
    s["player"].update(hp=30000, hp_max=30000)
    s["camera"] = {"eye": (0.0, 140.0, 0.0), "at": (0.0, 140.0, 1000.0)}
    target = s["enemies"][0]
    assert not bot.front_candidate(s, s["player"], target)
    assert C.dot_on(impact, foot) == "body"
    for now in (0.0, 0.05, 0.1):
        assert bot.choose_target(s, s["player"], s["enemies"], now) is target
        assert bot.target_exposed
        assert {"l1", "r1"} <= bot.tick(s, s["player"], target, now)["hold"]
    assert bot.stats["rapid_fire_verified"]
    m.put(LASER + C.LASER_DOT, ">3f", 0.0, 50.0, 57.0)           # actual first hit now stops short
    assert bot.choose_target(s, s["player"], s["enemies"], 0.15) is None
    assert "r1" not in bot.tick(s, s["player"], target, 0.15)["hold"]
    m.put(LASER + C.LASER_DOT, ">3f", *impact)
    target["hp"] = 0
    assert bot.choose_target(s, s["player"], s["enemies"], 0.2) is None


def test_measured_cover_switches_target_but_an_off_target_ray_does_not_claim_cover():
    m = world(laser_dot=(0.0, 135.0, 400.0))
    bot = C.Combat(m, {}, lessons=lambda e: None)
    s = snap(m, enemy=(0.0, 0.0, 1000.0))
    blocked = s["enemies"][0]
    other = {"slot": 1, "ptr": ENEMY + 1, "pos": (250.0, 0.0, 1200.0), "hp": 800, "hp_max": 800}
    assert bot.choose_target(s, s["player"], [blocked, other], 0.0) is other
    assert bot.blocked_until[ENEMY] > 0.0
    assert bot.choose_target(s, s["player"], [blocked], 0.1) is None
    assert "r1" not in bot.seek_target(s, s["player"], [blocked], 0.1)["hold"]
    m.put(LASER + C.LASER_DOT, ">3f", 150.0, 120.0, 400.0)  # aim beside him: exposure is simply unknown
    bot.blocked_until.clear()
    assert bot.choose_target(s, s["player"], [blocked], 0.2) is blocked
    assert not bot.blocked_until and bot.stats["target_evidence"] == "front candidate; visibility unconfirmed"


def test_close_rear_enemy_outranks_distant_front_enemy_but_does_not_authorize_blind_fire():
    m = world(laser_dot=(90.0, 110.0, 400.0))
    bot = C.Combat(m, {}, lessons=lambda e: None)
    s = snap(m, enemy=(0.0, 0.0, 1000.0))
    s["camera"] = {"eye": (0.0, 140.0, 0.0), "at": (0.0, 140.0, 1000.0)}
    front = s["enemies"][0]
    behind = {"slot": 1, "ptr": ENEMY + 1, "pos": (0.0, 0.0, -200.0), "hp": 800, "hp_max": 800}
    assert bot.choose_target(s, s["player"], [behind, front], 0.0) is behind
    assert "r1" not in bot.tick(s, s["player"], behind, 0.0)["hold"]
    behind["pos"] = (0, 0, -1000)
    assert bot.choose_target(s, s["player"], [behind, front], 0.1) is front


def test_nearest_living_enemy_wins_until_dead_and_awareness_reports_cover(tmp_path):
    m = world(laser_dot=(0, 110, 1000))
    bot = C.Combat(m, {}, learn_dir=tmp_path, lessons=lambda e: None)
    s = snap(m, enemy=(0, 0, 1000))
    close = {"slot": 1, "ptr": ENEMY + 1, "pos": (100, 0, 150), "hp": 20, "hp_max": 800}
    closer = {"slot": 2, "ptr": ENEMY + 2, "pos": (-50, 0, 100), "hp": 800, "hp_max": 800}
    enemies = s["enemies"] = [s["enemies"][0], close, closer]
    assert bot.choose_target(s, s["player"], enemies, 1) is closer
    assert bot.awareness[0]["hp"] == 800 and bot.awareness[0]["visibility"] == "unknown"
    closer["hp"] = 0
    assert bot.choose_target(s, s["player"], enemies, 1.1) is close
    m.put(LASER + C.LASER_DOT, ">3f", 0, 149, 120)
    close["pos"] = (0, 0, 300)
    s["enemies"] = [close]
    assert bot.choose_target(s, s["player"], [close], 1.2) is None
    assert bot.awareness[0]["visibility"] == "blocked"


def test_weapon_ready_action_and_first_hit_allow_fire_when_pose_byte_lags():
    m = world(laser_dot=(0.0, 110.0, 1000.0), aiming=False, act_vt=C.READY_VT)
    bot = C.Combat(m, {}, lessons=lambda e: None)
    s = snap(m, enemy=(0.0, 0.0, 1000.0))
    assert "r1" in bot.tick(s, s["player"], s["enemies"][0], 0.0)["hold"]
    s["player"]["action"] = 5  # taking a hit is not a usable aim pose
    assert "r1" not in bot.tick(s, s["player"], s["enemies"][0], 0.1)["hold"]


def test_close_hourglass_punch_still_wins_over_an_exposed_enemy(tmp_path):
    from gbox.mercs.titles import re5_ps3 as R

    m = world(laser_dot=(0.0, 110.0, 1000.0))
    bot = R.Bot(m, clock=lambda: 10.0, learn_dir=tmp_path, lessons=lambda e: None)
    s = snap(m, enemy=(0.0, 0.0, 1000.0))
    s["bonuses"] = [{"ptr": 1, "pos": (0.0, 13.0, 100.0), "kind": "time"}]
    assert bot.tick(s) == {"tap": "square"}
    assert bot.stats["bonus_presses"] == 1
