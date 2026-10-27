"""RE5 combat: continuous direct fire while tracking, measured cover avoidance, and independent RAM shot counts."""
import json
import math
import struct

import pytest

from gbox.mercs.titles import re5_combat as C

@pytest.fixture(autouse=True)
def _legacy_fire_gate(monkeypatch, request):
    """Older tests cover the first-overlap gate; the steady-head tests (#3046) opt back in. The sight / dot gate tests
    run without the close-threat blast; the blast tests opt in."""
    if "steady" not in request.node.name:
        monkeypatch.setattr(C, "STEADY_HEAD", False)
    if "blast" not in request.node.name:
        monkeypatch.setattr(C, "THREAT_BLAST", False)


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


def supported_laserless(state):
    """Laser-free decisions also need measured floor support and the native aim pitch."""
    from gbox.mercs.titles.re5_nav import NavMesh
    state['nav'] = NavMesh([(-2000.,0.,-2000.),(2000.,0.,-2000.),(2000.,0.,2000.),(-2000.,0.,2000.)],
                           [(0,1,2),(0,2,3)],[[(1,2,1.)],[(0,0,1.)]])
    state['player']['pitch'] = 0.
    return state


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
def test_tracking_small_diagonal_errors_does_not_starve_either_axis(tmp_path, yaw_sign, pitch_sign, monkeypatch):
    monkeypatch.setattr(C, "DEFAULT_ZONE", "head")             # the head aim (the strategy's say)
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
    assert all({"l1", "r1"} <= keys for keys in actions)  # firing continues while both tracking axes correct


def test_near_origin_direction_reversals_do_not_thrash_the_stick_and_valid_ray_recovers(tmp_path):
    # Run9's successive 6 cm ray baselines changed elevation -67.5 -> +71.4 degrees while P_PITCH changed 0.15.
    # Replay those endpoints against one fixed target, without treating P_PITCH as an authoritative shot ray.
    rays = [((143.091, 53.571, 135.908), (140.765, 47.860, 135.446)),
            ((153.911, 41.709, 125.940), (155.722, 47.685, 126.810))]
    m = world()
    bot = C.Combat(m, {}, learn_dir=tmp_path, lessons=lambda row: None)
    for i, (origin, dot) in enumerate(rays * 2):
        s = snap(m, enemy=(349.539, 0.0, 83.037))
        s["player"].update(pos=(202.237, 3.692, 150.020), rot=1.95, pitch=-0.339)   # facing him
        s["laser"] = {"from": origin, "at": dot}
        action = bot.tick(s, s["player"], s["enemies"][0], 1.0 + i * 0.1)
        assert action["hold"] == {"l1"}                       # a dot at the muzzle is no line to him: hold fire
        assert bot.stats["aim_feedback"] == "near-origin ray; correction paused"
    s["laser"] = {"from": (143, 53, 136), "at": (400, 100, 200)}
    action = bot.tick(s, s["player"], s["enemies"][0], 1.35)
    # valid ray, 28 deg off him in yaw (outside his window): turn, no shot; its 5 deg of pitch sit inside his window's
    # deadband (re5_engage.deadband): the stick leaves them alone - no waving while the dot is on his body height
    assert {"l1", "rleft"} <= action["hold"] and not {"rup", "rdown"} & action["hold"] and "r1" not in action["hold"]
    assert bot.near_ray_since is None
    assert bot.stats["aim_feedback"] == "ray direction"


def test_persistent_near_origin_feedback_has_bounded_reacquisition_and_valid_ray_resets_it(tmp_path):
    m = world()
    bot = C.Combat(m, {}, learn_dir=tmp_path, lessons=lambda row: None)
    s = snap(m)
    s["laser"] = {"from": (0, 149, 46), "at": (3, 153, 49)}
    assert bot.tick(s, s["player"], s["enemies"][0], 1.0)["hold"] == {"l1"}
    action = bot.tick(s, s["player"], s["enemies"][0], 1.5)
    assert action["hold"] in ({"lleft"}, {"lright"})
    assert "reacquire" in bot.stats["combat"]
    assert not bot.blocked_until                 # uncertain direction does not invent cover evidence
    s["laser"] = None
    assert bot.tick(s, s["player"], s["enemies"][0], 1.6)["hold"] == {"l1"}  # no ray: no blind sidestep, the gun stays up
    assert bot.near_ray_move_until == 0                                     # (its ray comes with it)
    s["laser"] = {"from": (0, 149, 46), "at": (0, 110, 400)}
    assert bot.tick(s, s["player"], s["enemies"][0], 1.65)["hold"] == {"l1", "r1"}
    assert bot.near_ray_since is None and bot.near_ray_move_until == 0
    s["laser"] = {"from": (0, 149, 46), "at": (3, 153, 49)}
    assert bot.tick(s, s["player"], s["enemies"][0], 1.7)["hold"] == {"l1"}
    s["prompt"] = "mash:circle"
    assert bot.tick(s, s["player"], s["enemies"][0], 1.8)["hold"] == set()
    assert bot.near_ray_since is None and bot.near_ray_move_until == 0


def test_short_ray_at_a_nearby_enemy_still_fires_and_aligned_near_cover_still_repositions(tmp_path):
    m = world()
    bot = C.Combat(m, {}, learn_dir=tmp_path, lessons=lambda row: None)
    s = snap(m)
    s["player"]["pos"] = (0, 0, 350)
    s["laser"] = {"from": (0, 100, 390), "at": (0, 110, 400)}
    for now in (1.0, 1.5, 2.0):
        assert bot.tick(s, s["player"], s["enemies"][0], now)["hold"] == {"l1", "r1"}
        assert bot.last_dot[0] == "body"
        assert bot.near_ray_since is None
    # a torn read (its origin 3 m behind him) is no ray: a Majini at arm's length straight ahead is still shot
    s["laser"] = {"from": (0, 110, 46), "at": (0, 110, 56)}
    assert bot.tick(s, s["player"], s["enemies"][0], 2.1)["hold"] == {"l1", "r1"}
    assert bot.stats["fire_gate"] == "point blank" and bot.stats["laser_rejected"] == 1
    # aligned near cover: a wall 45 cm in front of the muzzle, straight toward a Majini 4 m off - one sidestep
    s["player"]["pos"] = (0, 0, 0)
    s["laser"] = {"from": (0, 149, 46), "at": (0, 140, 90)}
    assert bot.tick(s, s["player"], s["enemies"][0], 2.2)["hold"] in ({"lleft"}, {"lright"})
    assert bot.stats["combat"] == "reposition: measured obstruction"


@pytest.mark.parametrize("bad", [(float("nan"), 100, 400), (0, float("inf"), 400), (0, 100)])
def test_malformed_ray_cannot_drive_stick_feedback(tmp_path, bad):
    m = world()
    bot = C.Combat(m, {}, learn_dir=tmp_path, lessons=lambda row: None)
    s = snap(m)
    s["laser"] = {"from": (0, 149, 46), "at": bad}
    assert bot.tick(s, s["player"], s["enemies"][0], 1.0)["hold"] == {"l1"}   # no ray: the gun up, no stick, no trigger
    assert bot._ray(s, 1.0) is None


def test_fires_immediately_on_an_exposed_body_and_keeps_the_dot_on_it(monkeypatch):
    monkeypatch.setattr(C, "DEFAULT_ZONE", "head")             # the head aim (the strategy's say)
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


def test_steady_direct_fire_holds_with_the_dot_beside_or_below_him_and_continues_down_a_line_past_him(monkeypatch):
    monkeypatch.setattr(C, "DEFAULT_ZONE", "head")             # the head aim (the strategy's say)
    """Operator 2026-10-22: "he is shooting at nonsense": the ground before him, the air beside him and a dot on past
    him (the game's dot stops on the first body it meets: beyond him is a miss) are no shot; on his head is."""
    for dot, fire in (((90.0, 120.0, 400.0), False), ((0.0, 0.0, 300.0), False), ((0.0, 160.0, 900.0), False),
                      ((0.0, 160.0, 400.0), True)):
        m = world(laser_dot=dot)
        bot = C.Combat(m, {}, clock=lambda: 0.0)
        s = snap(m)
        act = bot.tick(s, s["player"], s["enemies"][0], 0.0)
        if fire:                                       # a steady aim: the dot settles on the head first
            assert "r1" not in act["hold"] and bot.stats["fire_gate"].startswith("settling")
            act = bot.tick(s, s["player"], s["enemies"][0], C.HEAD_SETTLE_S + 0.01)
        assert "l1" in act["hold"] and ("r1" in act["hold"]) == fire, dot
        assert bot.stats["fire_gate"].endswith("hold fire") != fire
        assert bot.stats["shots"] == 0                 # held fire is intent, not a fabricated shot event


def test_steady_direct_fire_holds_while_the_dot_is_beside_below_or_past_the_target_then_resumes_on_him(monkeypatch):
    monkeypatch.setattr(C, "DEFAULT_ZONE", "head")             # the head aim (the strategy's say)
    # coaching note 3: shooting at the ground. The trigger waits while the stick brings the dot onto him.
    for dot in ((90.0, 120.0, 400.0), (0.0, 30.0, 400.0), (0.0, 20.0, 150.0), (0.0, 160.0, 900.0)):
        m = world(laser_dot=dot)
        bot = C.Combat(m, {}, clock=lambda: 0.0)
        s = snap(m)
        for k in range(30):
            act = bot.tick(s, s["player"], s["enemies"][0], k * 0.02)
            assert "l1" in act["hold"] and "r1" not in act["hold"], dot
        assert bot.stats["shots"] == 0 and bot.stats["los_held_fire"] > 0
    for dot, wait in (((0.0, 110.0, 400.0), C.HEAD_PATIENCE_S), ((0.0, 160.0, 400.0), C.HEAD_SETTLE_S)):
        m = world(laser_dot=dot)                         # on his body (after the patience) / head (settled): fire
        bot = C.Combat(m, {}, clock=lambda: 0.0)
        s = snap(m)
        assert "r1" not in bot.tick(s, s["player"], s["enemies"][0], 0.0)["hold"], dot
        assert {"l1", "r1"} <= bot.tick(s, s["player"], s["enemies"][0], wait + 0.01)["hold"], dot


def test_line_of_sight_aim_rejects_floor_short_of_target_and_accepts_aligned_ray():
    foot = (0.0, 0.0, 400.0)
    origin = (0.0, 140.0, 0.0)
    aim = (0.0, 72.0, 400.0)
    assert not C.line_of_sight_aim((origin, (0.0, 0.0, 200.0)), aim, None, foot)      # floor, halfway
    assert not C.line_of_sight_aim((origin, (150.0, 100.0, 400.0)), aim, None, foot)  # well to the side
    assert C.line_of_sight_aim((origin, (0.0, 75.0, 400.0)), aim, None, foot)
    assert C.line_of_sight_aim((origin, (0.0, 0.0, 0.0)), aim, "body", foot)
    assert not C.line_of_sight_aim(None, aim, None, foot)


def test_line_to_needs_the_ray_to_reach_him_in_line():
    o = (0.0, 150.0, 0.0)
    assert C.line_to((o, (0.0, 160.0, 1500.0)), (0.0, 160.0, 1000.0))            # on past him
    assert not C.line_to((o, (0.0, 150.0, 300.0)), (0.0, 160.0, 1000.0))         # a wall 3 m off
    assert not C.line_to((o, (0.0, 150.0, 50.0)), (0.0, 160.0, 1000.0))          # at the muzzle
    assert not C.line_to((o, (300.0, 160.0, 1500.0)), (0.0, 160.0, 1000.0))      # 11 deg off him
    assert C.line_to((o, (30.0, 150.0, 300.0)), (0.0, 160.0, 280.0))             # close up: his body is wide
    assert not C.line_to(None, (0.0, 160.0, 1000.0))


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


def test_every_majini_gets_the_body_and_the_head_or_leg_only_on_the_strategys_say():
    # operator 2026-10-22: "He needs to just hit them wherever he can hit them" - the body by default (helmets, shields)
    for dist, timer, combo in ((400.0, 8.0, 3), (400.0, 2.0, 3), (400.0, None, 0), (900.0, 8.0, 3)):
        assert C.zone_for({"hp_max": 800}, dist, timer, combo) == "body"
    assert C.zone_for({"hp_max": 9000}, 300.0, 8.0, 3) == "body"
    assert C.zone_for({"hp_max": 800, "zone": "head"}, 300.0, 8.0, 3) == "head"  # the strategy's say
    assert C.zone_for({"hp_max": 800, "zone": "leg"}, 300.0, 8.0, 3) == "leg"   # the strategy's say
    m = world(laser_dot=(0.0, 72.0, 400.0))                             # the dot on his thighs
    bot = C.Combat(m, {}, clock=lambda: 0.0)
    s = snap(m)
    tgt = dict(s["enemies"][0], zone="leg")
    fired = False
    for k in range(20):
        act = bot.tick(s, s["player"], tgt, k * 0.02)
        fired = fired or "r1" in act["hold"]
    assert bot.zone == "leg" and fired
    m.put(ACT, ">I", C.FIRE_VT)                                         # the shot leaves, his health falls
    m.put(ACT + C.ACT_FRAMES, ">f", 1.0)
    bot.tick(s, s["player"], tgt, 0.5)
    s2 = snap(m, hp=500)
    bot.tick(s2, s2["player"], s2["enemies"][0], 0.55)
    assert bot.stats["legshots"] == 1 and ENEMY in bot.stunned          # a leg hit: he kneels, in for the finisher
    assert bot.stunned_target(s2["enemies"], s2["player"], 0.6) is s2["enemies"][0]


def test_steady_head_aim_waits_for_the_settle_resets_when_the_dot_leaves_and_falls_back_to_the_body(monkeypatch):
    monkeypatch.setattr(C, "DEFAULT_ZONE", "head")             # the head aim (the strategy's say)
    m = world(laser_dot=(0.0, 160.0, 400.0))
    bot = C.Combat(m, {}, clock=lambda: 0.0)
    s = snap(m)
    tgt = s["enemies"][0]
    assert "r1" not in bot.tick(s, s["player"], tgt, 0.0)["hold"]
    m.put(LASER + C.LASER_DOT, ">3f", 0.0, 0.0, 300.0)                  # the dot drops to the ground: settle resets
    assert "r1" not in bot.tick(s, s["player"], tgt, 0.06)["hold"] and bot.dot_head_since is None
    m.put(LASER + C.LASER_DOT, ">3f", 0.0, 160.0, 400.0)
    assert "r1" not in bot.tick(s, s["player"], tgt, 0.07)["hold"]      # a new settle starts here
    assert "r1" not in bot.tick(s, s["player"], tgt, 0.12)["hold"]
    assert "r1" in bot.tick(s, s["player"], tgt, 0.18)["hold"]
    m.put(LASER + C.LASER_DOT, ">3f", 0.0, 110.0, 400.0)                # head out of reach: the body after the patience
    assert "r1" not in bot.tick(s, s["player"], tgt, 1.0)["hold"]
    assert "r1" in bot.tick(s, s["player"], tgt, 1.0 + C.HEAD_PATIENCE_S + 0.01)["hold"]


def test_steady_metrics_report_headshot_percent_and_shots_per_kill():
    m = world()
    bot = C.Combat(m, {}, clock=lambda: 0.0)
    bot.stats.update(shots=8, headshots=6)
    bot._count_kills({"kills": 10})
    bot._count_kills({"kills": 12})
    assert bot.stats["headshot_pct"] == 75.0 and bot.stats["shots_per_kill"] == 4.0


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
    first['ground_mines'] = {}  # this gun-only observation has a verified empty mine list
    bot.observe_round(first, "playing", 0.0)
    m.put(PL + C.P_FIRE_CMD, ">I", 4)
    fire = snap(m)
    fire['ground_mines'] = {}
    fire["prompt"] = "square"
    bot.observe_round(fire, "playing", 0.2)  # engine observation before prompt dispatch
    now[0] = 0.3                           # >25 ms: fallback fire command could otherwise count twice
    assert bot.tick(fire) == {"hold": set()}
    bot.combat.tick(fire, fire["player"], fire["enemies"][0], 0.3, observed=True)
    assert bot.stats["shots"] == 1
    m.put(PL + C.P_FIRE_CMD, ">I", 0)
    hit = snap(m, hp=600)
    hit['ground_mines'] = {}
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


def test_confirmed_cover_lowers_the_gun_until_cooldown_then_acquisition_can_fire():
    m = world(laser_dot=(0.0, 110.0, 1000.0))
    m.put(C.FIRE_TIMER_FPS, ">f", C.FIRE_TIMER_ORIG * 80)
    m.put(C.WEAPON_TABLE + 0x12 * C.WEAPON_STRIDE + C.WEAPON_INTERVAL, ">f", 0.0)
    bot = C.Combat(m, {}, lessons=lambda e: None)
    s = snap(m, enemy=(0.0, 0.0, 1000.0))
    for t in (0.0, 0.05, 0.1, 0.15):
        assert "r1" in bot.tick(s, s["player"], s["enemies"][0], t)["hold"]
    assert bot.stats["rapid_fire_verified"] is True
    m.put(LASER + C.LASER_DOT, ">3f", 0.0, 135.0, 400.0)  # first hit on intervening cover
    assert not ({"l1", "r1"} & bot.tick(s, s["player"], s["enemies"][0], 0.2)["hold"])
    s["laser"] = None
    assert "r1" not in bot.tick(s, s["player"], s["enemies"][0], 0.25)["hold"]
    act = bot.tick(s, s["player"], s["enemies"][0], 1.1)["hold"]
    assert "l1" in act and "r1" not in act and not bot.needs_firing_position   # the gun up, waiting for its ray
    for t in (1.6, 2.1, 2.6):                            # up LASERLESS_SWITCH_S without one: the laserless controller,
        act = bot.tick(s, s["player"], s["enemies"][0], t)["hold"]   # and without ray or floor it routes rather than
    assert not ({"l1","r1"} & act)                       # holding the aim forever
    assert bot.needs_firing_position
    s["laser"] = {"from": (0.0, 149.0, 46.0), "at": (0.0, 110.0, 1000.0)}
    assert {"l1", "r1"} <= bot.tick(s, s["player"], s["enemies"][0], 2.65)["hold"]


def test_measured_exposed_enemy_wins_over_a_nearer_front_candidate():
    m = world(laser_dot=(0.0, 110.0, 1000.0))
    bot = C.Combat(m, {}, lessons=lambda e: None)
    s = snap(m, enemy=(0.0, 0.0, 1000.0))
    exposed = s["enemies"][0]
    nearer = {"slot": 1, "ptr": ENEMY + 1, "pos": (150.0, 0.0, 400.0), "hp": 800, "hp_max": 800}
    assert bot.choose_target(s, s["player"], [nearer, exposed], 0.0) is exposed
    assert bot.stats["target_evidence"] == "laser first hit on enemy"


def test_actual_first_hit_overrides_camera_sector_for_a_close_low_enemy_until_dead():
    foot, impact = (0.0, -140.0, 140.0), (0.0, -30.0, 140.0)            # below the camera's sector, the dot on him
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
    m.put(LASER + C.LASER_DOT, ">3f", 0.0, 100.0, 80.0)          # actual first hit now stops short (a ledge)
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


def test_close_rear_enemy_outranks_distant_front_enemy_and_fire_tracks_the_turn():
    m = world(laser_dot=(90.0, 110.0, 400.0))
    bot = C.Combat(m, {}, lessons=lambda e: None)
    s = snap(m, enemy=(0.0, 0.0, 1000.0))
    s["camera"] = {"eye": (0.0, 140.0, 0.0), "at": (0.0, 140.0, 1000.0)}
    front = s["enemies"][0]
    behind = {"slot": 1, "ptr": ENEMY + 1, "pos": (0.0, 0.0, -200.0), "hp": 800, "hp_max": 800}
    assert bot.choose_target(s, s["player"], [behind, front], 0.0) is behind
    action = bot.tick(s, s["player"], behind, 0.0)["hold"]
    assert {"rleft", "rright"} & action                   # he is behind: swing round with the gun down (~150 deg/s,
    assert not action & {"l1", "r1"}                      # not ~30 deg/s aiming), then raise and fire
    assert "swinging" in bot.stats["combat"]


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
    s["player"]["action"] = 5  # queue the held input through hit recovery; do not count it as a fired shot
    assert {"l1", "r1"} <= bot.tick(s, s["player"], s["enemies"][0], 0.1)["hold"]
    assert bot.stats["shots"] == 0


def test_close_hourglass_punch_still_wins_over_an_exposed_enemy(tmp_path):
    from gbox.mercs.titles import re5_ps3 as R

    m = world(laser_dot=(0.0, 110.0, 1000.0))
    bot = R.Bot(m, clock=lambda: 10.0, learn_dir=tmp_path, lessons=lambda e: None)
    s = snap(m, enemy=(0.0, 0.0, 1000.0))
    s["bonuses"] = [{"ptr": 1, "pos": (0.0, 13.0, 100.0), "kind": "time"}]
    assert bot.tick(s) == {"tap": "square"}
    assert bot.stats["bonus_presses"] == 1


@pytest.mark.parametrize("wid", [0x02, 0x09, 0x19, 0x05, 0x0B, 0x1A, 0x1B])
def test_loaded_direct_guns_raise_with_trigger_and_hold_while_acquiring(tmp_path, wid):
    m = world(aiming=False, act_vt=0)
    m.put(PL + C.P_INV + 3 * C.INV_SLOT + C.INV_ID, ">I", 0x100 | wid)
    bot = C.Combat(m, {}, learn_dir=tmp_path, lessons=lambda row: None)
    s = supported_laserless(snap(m, enemy=(100, 0, 250)))  # 22 deg off: supported floor, native pitch
    s["laser"] = None
    for now in (0.0, 0.05, 0.5, 1.0):               # target 50 deg off the facing, no ray yet: raise and turn, no blind shot
        keys = bot.tick(s, s["player"], s["enemies"][0], now)["hold"]
        assert {"l1", "rleft"} <= keys and "r1" not in keys    # raise and turn; the trigger waits for a line
    assert bot.stats["shots"] == 0 and bot.round_counts["shots"] == 0


@pytest.mark.parametrize("condition", ["dead_player", "dead_target", "missing_target", "far", "recovery", "qte"])
def test_direct_fire_releases_for_invalid_targets_and_priority_recovery(tmp_path, condition):
    m = world()
    bot = C.Combat(m, {}, learn_dir=tmp_path, lessons=lambda row: None)
    s = snap(m)
    target = s["enemies"][0]
    if condition == "dead_player": s["player"]["hp"] = 0
    if condition == "dead_target": target["hp"] = 0
    if condition == "missing_target": target = None
    if condition == "far": target["pos"] = (0, 0, C.ENGAGE_R + 1)
    if condition == "recovery": s["recovery_active"] = True
    if condition == "qte": s["prompt"] = "mash:circle"
    assert bot.tick(s, s["player"], target, 0.0) == {"hold": set()}


@pytest.mark.parametrize("wid", [0x0D, 0x0C, 0x0F, 0x99])
def test_splash_unknown_and_unverified_weapons_do_not_inherit_tracking_fire(tmp_path, wid):
    m = world(laser_dot=(160, 110, 1500))
    m.put(PL + C.P_INV + 3 * C.INV_SLOT + C.INV_ID, ">I", 0x100 | wid)
    bot = C.Combat(m, {}, learn_dir=tmp_path, lessons=lambda row: None)
    s = snap(m, enemy=(0, 0, 1500))
    s["weapon_round_type"] = "explosive"
    assert "r1" not in bot.tick(s, s["player"], s["enemies"][0], 0.0)["hold"]
    s["laser"] = None
    assert "r1" not in bot.tick(s, s["player"], s["enemies"][0], 0.1)["hold"]


def test_unknown_ammo_never_counts_as_loaded_for_tracking(tmp_path):
    m = world()
    bot = C.Combat(m, {}, learn_dir=tmp_path, lessons=lambda row: None)
    s = snap(m)
    s["inventory"] = [{"hand": True, "item": 0x1A, "rounds": None}]
    assert "r1" not in bot.tick(s, s["player"], s["enemies"][0], 0.0)["hold"]


@pytest.mark.parametrize("override", ["qte", "recovery", "heal", "dead", "no_enemy"])
def test_bot_priority_actions_override_continuous_fire(tmp_path, override):
    from gbox.mercs.titles import re5_ps3 as R
    m = world(laser_dot=(100, 110, 180))
    bot = R.Bot(m, clock=lambda: 10.0, learn_dir=tmp_path, lessons=lambda row: None)
    s = snap(m, enemy=(0, 0, 180))
    if override == "qte": s["prompt"] = "mash:circle"
    if override == "recovery": s["recovery_active"] = True
    if override == "dead": s["player"]["hp"] = 0
    if override == "no_enemy": s["enemies"] = []
    if override == "heal":
        s["player"]["hp"] = 100
        s["inventory"] = [{"type": 2, "id": next(iter(R.HEAL_IDS)), "item": 0, "slot": 4,
                           "grid": 1, "hand": 0, "rounds": 1}]
    result = bot.tick(s)
    assert not ({"l1", "r1"} & result.get("hold", set()))
    if override == "heal":
        assert result == {"hold": set()}  # lower the raised gun before the recovery-item D-pad tap
        assert bot.healing is not None


def test_bot_nearby_off_reticle_target_keeps_gun_up_and_fires_only_down_a_line(tmp_path):
    from gbox.mercs.titles import re5_ps3 as R
    m = world(laser_dot=(100, 110, 180), aiming=False, act_vt=0)
    bot = R.Bot(m, clock=lambda: 10.0, learn_dir=tmp_path, lessons=lambda row: None)
    s = supported_laserless(snap(m, enemy=(100, 0, 180)))  # off body/camera aim; no guessed ray
    s["laser"] = None
    keys = bot.tick(s)["hold"]
    assert "l1" in keys and "r1" not in keys              # 1.8 m off, no ray yet: up, not firing
    assert bot.stats["shots"] == 0 and bot.stats["phase"] == "clear_nearby"
    s["laser"] = {"from": (0.0, 149.0, 46.0), "at": (100.0, 110.0, 180.0)}
    assert {"l1", "r1"} <= bot.tick(s)["hold"]


def test_hit_recovery_never_waits_to_reacquire_and_mandatory_escape_still_wins(tmp_path):
    from gbox.mercs.titles import re5_ps3 as R
    now = [10.0]
    m = world(aiming=False, act_vt=0)
    bot = R.Bot(m, clock=lambda: now[0], learn_dir=tmp_path, lessons=lambda row: None)
    for pose in (5, 5, 0, 2):
        s = supported_laserless(snap(m, enemy=(0, 0, 60)))
        s["player"]["action"] = pose
        s["laser"] = None
        assert {"l1", "r1"} <= bot.tick(s)["hold"]
        now[0] += 0.1
    assert bot.stats["shots"] == 0 and bot.stats["backoffs"] == 0
    s = snap(m, enemy=(0, 0, 60))
    s["player"]["action"] = 5
    s["prompt"] = "mash:circle"
    assert bot.tick(s) == {"hold": set()}
    now[0] += 0.1
    s = snap(m, enemy=(0, 0, 60))
    s["player"]["action"] = 4
    assert bot.tick(s) == {"hold": set()}


def test_wall_in_front_off_axis_ray_is_cover_and_holds_fire(tmp_path):
    """Coaching #3002: the dot lands on a wall short of him a few degrees off his capsule: do not shoot the wall."""
    for dot in ((30.0, 120.0, 300.0), (-35.0, 110.0, 320.0)):
        m = world(laser_dot=dot, enemy=(0.0, 0.0, 1000.0))
        bot = C.Combat(m, {}, learn_dir=tmp_path, lessons=lambda row: None)
        s = snap(m, enemy=(0.0, 0.0, 1000.0))
        s["laser"] = {"from": (0.0, 149.0, 46.0), "at": dot}
        act = bot.tick(s, s["player"], s["enemies"][0], 1.0)
        assert bot.blocked_until[ENEMY] > 1.0, dot
        assert "r1" not in act["hold"], dot
    # a wide miss (beside him, well off the cone) stays unknown, not cover: no candidate switch. The trigger still
    # waits for the dot to come onto him (#869: no shots off the aim point) while the stick turns.
    m = world(laser_dot=(300.0, 120.0, 400.0), enemy=(0.0, 0.0, 1000.0))
    bot = C.Combat(m, {}, learn_dir=tmp_path, lessons=lambda row: None)
    s = snap(m, enemy=(0.0, 0.0, 1000.0))
    s["laser"] = {"from": (0.0, 149.0, 46.0), "at": (300.0, 120.0, 400.0)}
    act = bot.tick(s, s["player"], s["enemies"][0], 1.0)
    assert "l1" in act["hold"] and "r1" not in act["hold"] and bot.stats["los_held_fire"] > 0
    assert not bot.blocked_until


def test_by_default_he_fires_as_soon_as_the_dot_is_anywhere_on_him():
    # operator 2026-10-22: "He is just standing there letting these people devastate him ... These enemies are wearing
    # helmets, some of them are using shields. He needs to just hit them wherever he can hit them."
    for dot in ((0.0, 110.0, 400.0), (0.0, 160.0, 400.0), (0.0, 72.0, 400.0)):   # chest, head, thighs
        m = world(laser_dot=dot)
        bot = C.Combat(m, {}, clock=lambda: 0.0)
        s = snap(m)
        act = bot.tick(s, s["player"], s["enemies"][0], 0.0)
        assert bot.zone == "body" and {"l1", "r1"} <= act["hold"], dot          # no settle, no patience: the trigger


def test_a_close_threat_is_blasted_once_the_aim_is_on_him_never_beside_him_or_at_his_feet():
    # operator 2026-10-22: "I need them blasting like a lunatic on a threat" - and 2026-10-26: "she lowered her gun, shot
    # at his feet, circled around him and then shot him. This is an absurd way to behave". The trigger is down from the
    # first frame the aim is inside his window (re5_engage.window); beside him or at his feet it waits while the stick
    # brings the dot on (2026-10-26: the old blast fired whatever the aim within 30 deg - "shooting at walls")
    for dot, want in (((90.0, 120.0, 400.0), {"rright"}), ((0.0, 30.0, 300.0), {"rup"})):   # beside him, at his feet
        m = world(laser_dot=dot)
        bot = C.Combat(m, {}, clock=lambda: 0.0)
        s = supported_laserless(snap(m, enemy=(0.0, 0.0, 300.0)))
        for k in range(3):
            act = bot.tick(s, s["player"], s["enemies"][0], k * 0.02)["hold"]
            assert "l1" in act and "r1" not in act and want <= act, (dot, k)
        assert bot.stats["fire_gate"].startswith("slewing") and bot.stats["los_held_fire"] == 3
    for dot in ((0.0, 110.0, 300.0), None):              # the dot on him; no ray yet, the gun up and level, faced
        m = world(laser_dot=dot) if dot else world()
        bot = C.Combat(m, {}, clock=lambda: 0.0)
        s = supported_laserless(snap(m, enemy=(0.0, 0.0, 300.0)))
        if dot is None:
            s["laser"] = None
        for k in range(5):
            act = bot.tick(s, s["player"], s["enemies"][0], k * 0.02)["hold"]
            assert {"l1", "r1"} <= act, (dot, k)                     # gun up, trigger down, every frame
        assert bot.stats["fire_gate"] == ("threat: blasting" if dot is None else "on him")


def test_blast_stays_off_for_far_majini_and_ones_off_to_the_side():
    m = world(laser_dot=(0.0, 0.0, 600.0))                           # 15 m off, the dot on the ground short of him
    bot = C.Combat(m, {}, clock=lambda: 0.0)
    s = snap(m, enemy=(0.0, 0.0, 1500.0))
    assert "r1" not in bot.tick(s, s["player"], s["enemies"][0], 0.0)["hold"]   # far: the sight gates decide
    assert bot.stats["fire_gate"] != "threat: blasting"
    m = world(laser_dot=(90.0, 120.0, 400.0))
    bot = C.Combat(m, {}, clock=lambda: 0.0)
    s = snap(m, enemy=(300.0, 0.0, 100.0))                           # close but 70 deg off the facing: turn first
    assert "r1" not in bot.tick(s, s["player"], s["enemies"][0], 0.0)["hold"]


def test_laserless_gun_fires_when_off_axis_but_camera_ray_already_on_his_chest():
    # Direct gun, no laser dot read, but the native camera is already aimed at his chest. Even though the body faces
    # ~72 deg off to the side, the aim line is on him: fire now instead of lowering the gun to swing the body round.
    m = world()
    bot = C.Combat(m, {}, clock=lambda: 0.0)
    s = supported_laserless(snap(m, enemy=(300.0, 0.0, 100.0)))
    s["laser"] = None
    s["camera"] = {"eye": (0.0, 140.0, 0.0), "at": (300.0, 110.0, 100.0)}   # CHEST_H above his feet: on target
    act = bot.tick(s, s["player"], s["enemies"][0], 0.0)
    assert "r1" in act["hold"], act                                     # on-target aim: fire, do not swing
    assert "swing" not in bot.stats.get("combat", "")
    assert "camera direction" in bot.stats.get("aim_feedback", "")


@pytest.mark.parametrize('ready,on_target',[(True,True),(True,False),(False,True)])
def test_valid_first_hit_keeps_off_axis_gun_raised_only_in_ready_pose(tmp_path,ready,on_target):
    target=(300.,0.,100.)
    dot=(300.,110.,100.) if on_target else (0.,110.,1000.)
    memory=world(laser_dot=dot,enemy=target,aiming=ready,act_vt=C.READY_VT if ready else 0)
    state=snap(memory,enemy=target)
    combat=C.Combat(memory,{},learn_dir=tmp_path)
    keys=combat.tick(state,state['player'],state['enemies'][0],1.)['hold']
    if ready and on_target:
        assert {'l1','r1'}<=keys
        assert not ({'rleft','rright'} & keys)
        assert combat.stats['aim_feedback']=='ray direction'
    else:
        assert 'rleft' in keys and not ({'l1','r1'} & keys)
        assert 'swinging' in combat.stats['combat']


def test_a_direct_gun_with_the_gun_down_is_raised_not_treated_as_laserless():
    # round map 2026-10-26: 42 s standing still in 'fight' - "laserless gun: lower weapon and turn toward target" -
    # the laser ray only exists while aiming, so every gun looked laserless with the gun down and never came up
    m = world(aiming=False, act_vt=0)
    bot = C.Combat(m, {}, clock=lambda: 0.0)
    s = supported_laserless(snap(m, enemy=(700.0, 0.0, 900.0)))        # a Majini off to the side, in range
    s["laser"] = None                                                   # the gun is down: no ray
    act = bot.tick(s, s["player"], s["enemies"][0], 0.0)["hold"]
    assert "l1" in act                                                  # raise the gun (the ray comes with it)
    assert not str(bot.stats.get("combat", "")).startswith("laserless gun")


def test_a_wild_ray_error_faces_him_levels_the_gun_and_holds_the_trigger():
    # operator 2026-10-26, watching: "the bot will do a thing while aiming where they begin looking down and to the side
    # while dispatching the foes" (round map Ship_Deck 11:37: yaw -55 / pitch -56 with the trigger held, the dot on nothing)
    m = world(laser_dot=(-120.0, 20.0, 60.0))        # the ray from the gun down into the deck, 80 deg off to the right
    bot = C.Combat(m, {}, clock=lambda: 0.0)
    s = snap(m, enemy=(0.0, 0.0, 300.0))             # a Majini 3 m straight ahead, on his level: a threat
    s["player"]["pitch"] = -0.9                      # the snapshot's pitch, + = up: he is looking at the deck
    act = bot.tick(s, s["player"], s["enemies"][0], 0.0)["hold"]
    assert "rup" in act and "rdown" not in act, act  # the gun comes up to level
    assert not act & {"rleft", "rright"}, act        # his body already faces him: no ray-driven sweep
    assert "r1" not in act and "l1" in act, act      # no rounds into the deck while the dot is off him
    assert bot.stats["aim_guard"].startswith("wild") and bot.stats["aim_guards"] == 1
    assert "guard wild" in bot.stats["combat"]
    m = world(laser_dot=(0.0, 112.0, 300.0))         # the dot back on his chest: the ordinary fire goes on
    bot = C.Combat(m, {}, clock=lambda: 0.0)
    s = snap(m, enemy=(0.0, 0.0, 300.0))
    s["player"]["pitch"] = -0.9
    act = bot.tick(s, s["player"], s["enemies"][0], 0.0)["hold"]
    assert "r1" in act and "aim_guard" not in bot.stats, act


def test_a_moderate_error_at_the_muzzle_is_steered_and_the_blast_waits_for_his_window():
    # 13:05 live: a "close" guard that skipped the steering left yaw +14 / pitch +24 uncorrected through 149 ticks of fire.
    # The error is steered like any other; the trigger waits until the aim is inside his window (no rounds beside him)
    m = world(laser_dot=(40.0, 100.0, 140.0))        # the dot a hand beside him: 23 deg of yaw to take out
    bot = C.Combat(m, {}, clock=lambda: 0.0)
    s = snap(m, enemy=(0.0, 0.0, 150.0))
    s["player"]["pitch"] = 0.0
    act = bot.tick(s, s["player"], s["enemies"][0], 0.0)["hold"]
    assert "l1" in act and "r1" not in act, act
    assert act & {"rleft", "rright"}, act            # the stick takes the error out
    assert "aim_guard" not in bot.stats and bot.stats["fire_gate"].startswith("slewing")
    m.put(LASER + C.LASER_DOT, ">3f", 40.0, 110.0, 260.0)   # 11 deg off his chest (past him): inside his window at 1.5 m
    act = bot.tick(s, s["player"], s["enemies"][0], 0.1)["hold"]
    assert {"l1", "r1"} <= act and bot.stats["fire_gate"] == "threat: blasting", act


def test_a_majini_behind_gets_the_quick_turn_and_the_aim_takes_over_once_the_heading_swings():
    # operator 2026-10-26: "turning around nonsensically ignoring threats"; live: killed by a Majini 119 deg behind while
    # the body swung round with the gun down
    m = world(aiming=False)
    bot = C.Combat(m, {}, clock=lambda: 0.0)
    s = snap(m, enemy=(0.0, 0.0, -300.0))            # straight behind him
    assert bot.tick(s, s["player"], s["enemies"][0], 0.0)["hold"] == {"ldown", "cross"}
    assert bot.stats["quick_turns"] == 1 and bot.stats["combat"].startswith("quick turn")
    assert bot.tick(s, s["player"], s["enemies"][0], 0.1)["hold"] == set()   # hands off while it turns
    s["player"]["rot"] = math.pi                      # the heading swung round: he faces the Majini
    act = bot.tick(s, s["player"], s["enemies"][0], 0.3)["hold"]
    assert "l1" in act and not act & {"ldown", "cross"}, act
    assert bot.stats["quick_turn"].startswith("works: 1")


def test_a_quick_turn_that_never_turns_is_switched_off_and_the_body_turns_instead():
    m = world(aiming=False)
    bot = C.Combat(m, {}, clock=lambda: 0.0)
    s = snap(m, enemy=(0.0, 0.0, -300.0))
    for t in (0.0, 2.0):                              # two presses, the heading never moves
        assert bot.tick(s, s["player"], s["enemies"][0], t)["hold"] == {"ldown", "cross"}
        act = bot.tick(s, s["player"], s["enemies"][0], t + 0.75)["hold"]   # judged, inside the gap
        assert act & {"rleft", "rright"} and not act & {"ldown", "cross"}, act   # judged: the body swing goes on
    assert bot.qturn_off and "off" in bot.stats["quick_turn"]
    act = bot.tick(s, s["player"], s["enemies"][0], 5.0)["hold"]
    assert act & {"rleft", "rright"} and bot.stats["quick_turns"] == 2


def test_the_majini_in_front_is_chosen_over_a_slightly_nearer_one_behind_and_the_target_is_held():
    # live 2026-10-26 15:39: 19.6 s of a 30 s life turning with the gun down between the nearest Majini, hit 3 of 3 times
    m = world(aiming=False)
    bot = C.Combat(m, {}, clock=lambda: 0.0)
    s = snap(m, enemy=(0.0, 0.0, 300.0))
    front = s["enemies"][0]
    behind = {"slot": 1, "ptr": ENEMY + 0x1000, "pos": (0.0, 0.0, -250.0), "hp": 800, "hp_max": 800}
    s["enemies"] = [behind, front]
    assert bot.choose_target(s, s["player"], s["enemies"], 0.0) is front
    behind["pos"] = (0.0, 0.0, -230.0)                 # a little nearer still: no swing round for him
    assert bot.choose_target(s, s["player"], s["enemies"], 0.1) is front
    behind["pos"] = (0.0, 0.0, -60.0)                  # on top of him behind - but one stands 3 m in front: the gun never
    assert bot.choose_target(s, s["player"], s["enemies"], 0.2) is front    # comes down to turn away (operator 2026-10-26)
    front["pos"] = (0.0, 0.0, 450.0)                   # the front one further off than FRONT_CLEAR_R: the turn now
    assert bot.choose_target(s, s["player"], s["enemies"], 0.3) is behind
