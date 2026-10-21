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
    return {"player": {"ptr": PL, "pos": (0.0, 0.0, 0.0), "rot": 0.0, "action": C.AIMING if aiming else 0},
            "enemies": [{"slot": 0, "ptr": ENEMY, "pos": enemy, "hp": hp, "hp_max": 800}], "timer": 100.0}


def test_the_dot_names_where_it_sits_on_a_majini():
    assert C.dot_on((0, 160, 400), (0, 0, 400)) == "head"
    assert C.dot_on((20, 100, 390), (0, 0, 400)) == "body"
    assert C.dot_on((0, 20, 400), (0, 0, 400)) is None                 # the ground at his feet
    assert C.dot_on((80, 100, 400), (0, 0, 400)) is None                # beside him
    assert C.dot_on((0, 160, 700), (0, 0, 400)) is None                 # past him


def test_the_ray_error_is_the_turn_that_puts_the_dot_on_the_head():
    yaw, pitch = C.ray_error((0, 150, 0), (0, 150, 1000), (100, 250, 1000))
    assert math.degrees(yaw) == pytest.approx(5.71, abs=0.05) and math.degrees(pitch) == pytest.approx(5.68, abs=0.05)


def test_fires_only_with_the_dot_on_the_head_and_writes_the_pitch():
    far = (0.0, 0.0, 1000.0)                                            # beyond FINISHER_SETUP_R: the head
    m = world(laser_dot=(0.0, 120.0, 1000.0), enemy=far)               # on his chest, 40 cm under the head
    bot = C.Combat(m, {}, clock=lambda: 0.0, learn_dir=None)
    s = snap(m, enemy=far)
    tgt = s["enemies"][0]
    act = bot.tick(s, s["player"], tgt, 0.0)
    assert bot.zone == "head"
    assert "r1" not in act["hold"] and "l1" in act["hold"]            # body only, not yet BODY_AFTER_S: no shot
    if C.PITCH_WRITE:
        pitch = struct.unpack(">f", m.rd(PL + C.P_PITCH, 4))[0]
        assert pitch < 0 and bot.stats["pitch_writes"] == 1             # the aim raised (+0x1AA0: + = down)
    else:
        assert "rup" in act["hold"]                                     # the aim raised with the stick
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


def test_a_body_shot_after_the_head_stays_out_of_reach():
    m = world(laser_dot=(0.0, 100.0, 400.0))
    bot = C.Combat(m, {}, clock=lambda: 0.0)
    s = snap(m)
    fired = False
    for k in range(40):
        act = bot.tick(s, s["player"], s["enemies"][0], k * 0.02)
        fired = fired or "r1" in act["hold"]
    assert fired                                                        # BODY_AFTER_S on the body: a hit is a hit


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
