"""Split-screen co-op on RE5 / RE6 Switch (gbox.mercs.titles.switch_team and the titles' per-player readers): each
player's own pointer, laser and camera from the static findings in docs/research/switch-coop-bot.md, the menus' split
targets, and the team's behaviour on fake guests and snapshots. No live two-player run yet."""
import math
import struct

import pytest

import test_re5_switch as T5
import test_re6_switch as T6
from gbox.mercs.titles import re5_switch as R5, re6_switch as R6, switch_team as S


@pytest.fixture(autouse=True)
def _fresh():
    for cache in (R5._LASER, R5._LASER_MISS, R5._NOT_LASER, R6._FOUND, R6._MISS):
        cache.clear()
    R6._BONUS.update(base=None)
    R6.TITLE.since = None
    yield


# --- RE5: Player 2 in RAM ----------------------------------------------------------------------------------------------

def re5_two(p2_index=1, owner=1, split=True):
    """A round with Chris as P1 (slot +0x30) and Sheva as P2 (slot +0x38), each with its own laser sight."""
    g = T5.round_guest(units=((R5.LASER_LINE, "uLaserSight"),))
    sp = R5.u64(g, T5.BASE + R5.S_PLAYER)
    p1 = R5.u64(g, sp + R5.P_FIRST)
    g.put(p1 + R5.P_INDEX, bytes([0]))
    p2 = g.obj("uPl01ShebaNormal", 0x4000)
    g.q(sp + R5.P_FIRST + 8, p2)
    g.put(p2 + R5.P_INDEX, bytes([p2_index]))
    g.put(p2 + R5.P_POS, struct.pack("<3f", 500.0, 0.0, 100.0))
    g.put(p2 + R5.P_ROT, struct.pack("<4f", 0.0, 0.0, 0.0, 1.0))
    g.put(p2 + R5.P_HP, struct.pack("<hh", 640, 1000))
    for p, idx, dot in ((p1, 0, (0.0, 120.0, 900.0)), (p2, owner, (500.0, 120.0, 900.0))):
        lu = g.obj("uLaserSight", 0x400)
        g.q(p + R5.P_LASER, lu)
        g.put(lu + R5.LASER_OWNER, struct.pack("<I", idx))
        g.put(lu + R5.LASER_FROM, struct.pack("<3f", dot[0], 140.0, 40.0))
        g.put(lu + R5.LASER_DOT, struct.pack("<3f", *dot))
    gs = R5.game_sys(g, T5.BASE)
    g.i32(gs + R5.GS_PLAYERS, R5.PLAYERS_SPLIT if split else 0)
    return g, p1, p2


def test_re5_a_view_reads_its_own_player_and_laser():
    g, p1, p2 = re5_two()
    solo = R5.snapshot(g)                                   # no view: player 0 and the effects line, as always
    assert solo["player"]["ptr"] == p1 and "player_index" not in solo and "scoring_players" not in solo
    one = R5.snapshot(S.View(g, 0))
    two = R5.snapshot(S.View(g, 1))
    assert one["player"]["ptr"] == p1 and one["laser"]["at"] == (0.0, 120.0, 900.0) and one["player_index"] == 0
    assert two["player"]["ptr"] == p2 and two["player"]["hp"] == 640 and two["player"]["pos"] == (500.0, 0.0, 100.0)
    assert two["laser"] == {"from": (500.0, 140.0, 40.0), "at": (500.0, 120.0, 900.0), "up": True}
    assert one["scoring_players"] == two["scoring_players"] == 2      # cGameSys +0x898 = 2: a team round
    assert two["enemies"] == one["enemies"]                           # the enemies are both players'


def test_re5_a_slot_whose_index_byte_disagrees_is_no_player():
    g, _, _ = re5_two(p2_index=3)
    assert R5.snapshot(S.View(g, 1))["player"] is None


def test_re5_another_players_laser_is_never_taken():
    g, _, _ = re5_two(owner=0)                              # P2's pointer leads to a laser owned by index 0
    assert R5.snapshot(S.View(g, 1))["laser"] is None


def test_re5_menus_take_split_screen_on_request():
    g = T5.round_guest(player=False, units=((18, "uIdStartUp29"),), cursors={"uIdStartUp29": {R5.MENU_SUB: 1,
                                                                                               R5.MODE_CURSOR: 3}})
    assert R5.screen(g)["target"] == R5.MODE_NO_MERCY
    g.mercs_split_screen = True                             # this session only (switch_team.Session sets it)
    scr = R5.screen(g)
    assert (scr["where"], scr["cursor"], scr["target"]) == ("mercs_mode", 3, R5.MODE_SPLIT_SCREEN)
    assert R5.step(scr) == "dup"


def test_re5_participants_are_both_players_by_their_index_bytes():
    g, p1, p2 = re5_two()
    rows = S.participants(g, S.TITLES[R5.MAP_ID])
    assert [(r["slot"], r["id"], r["actor"]) for r in rows] == [(1, "p1", p1), (2, "p2", p2)]
    assert all(r["provenance"]["native_actor_verified"] for r in rows)
    g2, _, _ = re5_two(p2_index=0)
    assert [r["slot"] for r in S.participants(g2, S.TITLES[R5.MAP_ID])] == [1]


# --- RE6: Player 2 in RAM ----------------------------------------------------------------------------------------------

def re6_two(owner=None, cam_owner=None):
    g = T6.round_guest()
    sp = R6.u64(g, T6.BASE + R6.S_PLAYER)
    p1 = R6.u64(g, sp + R6.P_FIRST)
    g.put(p1 + R6.P_INDEX, bytes([0]))
    p2 = g.obj("uPl01HelenaAsia", 0x8000)
    g.q(sp + R6.P_FIRST + 8, p2)
    g.put(p2 + R6.P_INDEX, bytes([1]))
    g.f32(p2 + R6.P_POS, 400.0, 0.0, 0.0)
    g.f32(p2 + R6.P_ROT, 0.0, 0.0, 0.0, 1.0)
    g.put(p2 + R6.P_HP, struct.pack("<hh", 600, 900))
    cam = g.obj("uCameraCtrl", 0x4CF0)                      # P2's own camera, looking along +x (yaw 90 deg)
    g.q(p2 + R6.P_CAMERA, cam)
    g.q(cam + R6.CAM_OWNER, p2 if cam_owner is None else cam_owner)
    g.f32(cam + R6.CAM_POS, 200.0, 140.0, 0.0)
    g.f32(cam + R6.CAM_TARGET, 500.0, 140.0, 0.0)
    lu = g.obj("uLaserSight", 0x600)
    g.q(p2 + R6.P_LASER, lu)
    g.put(lu + R6.LASER_OWNER, struct.pack("<I", 1 if owner is None else owner))
    g.f32(lu + R6.LASER_DOT, 900.0, 120.0, 0.0)
    g.f32(lu + R6.LASER_FROM, 430.0, 190.0, 0.0)
    g.f32(lu + R6.LASER_UP, 0.86)
    return g, p1, p2, cam


def test_re6_a_view_reads_its_own_player_camera_and_laser():
    g, p1, p2, cam = re6_two()
    assert R6.snapshot(g)["player"]["ptr"] == p1            # no view: as always
    two = R6.snapshot(S.View(g, 1))
    assert two["player"]["ptr"] == p2 and two["player"]["hp"] == 600 and two["player_index"] == 1
    assert two["camera"]["unit"] == cam and math.isclose(two["camera"]["yaw"], math.pi / 2, abs_tol=1e-6)
    assert two["laser"]["at"] == (900.0, 120.0, 0.0) and two["laser"]["up"] is True


def test_re6_a_camera_or_laser_owned_by_someone_else_is_not_his():
    g, p1, _, _ = re6_two(owner=0, cam_owner=1)
    two = R6.snapshot(S.View(g, 1))
    assert two["camera"] is None and two["laser"] is None


def test_re6_menus_take_split_on_request():
    g = T6.menu_guest("uIdStartUp30", R6.MENU_CURSOR, 0)
    assert R6.screen(g)["target"] == R6.MERCS_SOLO
    g.mercs_split_screen = True
    scr = R6.screen(g)
    assert (scr["where"], scr["target"]) == ("mercs_mode", R6.MERCS_SPLIT) and R6.step(scr) == "ddown"


# --- shaping what each brain sees ------------------------------------------------------------------------------------

def foe(ptr, x, z, hp=800):
    return {"ptr": ptr, "pos": (x, 0.0, z), "hp": hp, "hp_max": 800}


def team_snap(me=(0.0, 0.0, 0.0), mate=(300.0, 0.0, 0.0), enemies=(), mate_motion=0, mate_hp=1000, laser=None,
              mate_rot=0.0, me_hp=1000):
    return {"player": {"pos": me, "rot": 0.0, "hp": me_hp, "hp_max": 1000, "motion": 0},
            "partner": {"pos": mate, "rot": mate_rot, "hp": mate_hp, "hp_max": 1000, "motion": mate_motion},
            "partner_laser": laser, "enemies": list(enemies)}


RE5T = S.TITLES[R5.MAP_ID]


def test_the_teammate_leaves_the_operators_targets_to_them():
    aimed, in_front, mine = foe(1, 300.0, 1500.0), foe(2, 300.0, 200.0), foe(3, -800.0, 0.0)
    laser = {"from": (300.0, 140.0, 40.0), "at": (300.0, 110.0, 1500.0), "up": True}
    out = S.shape(team_snap(enemies=[aimed, in_front, mine], laser=laser), RE5T, S.TEAMMATE)
    assert [e["ptr"] for e in out["enemies"]] == [3] and out["team_shaped"]["why"] == "operator_targets_left"
    close = foe(4, 100.0, 150.0)                           # in the operator's cone but on top of the bot: his business
    out = S.shape(team_snap(enemies=[in_front, close]), RE5T, S.TEAMMATE)
    assert 4 in [e["ptr"] for e in out["enemies"]]


def test_a_held_partners_grabbers_come_first():
    grabber, far = foe(1, 310.0, 20.0), foe(2, -900.0, 0.0)
    out = S.shape(team_snap(enemies=[grabber, far], mate_motion=107), RE5T, S.TEAMMATE)
    assert [e["ptr"] for e in out["enemies"]] == [1] and out["team_shaped"]["why"] == "partner_held"


def test_two_bots_split_the_crowd_by_who_is_nearer():
    mine, theirs, on_me = foe(1, -500.0, 0.0), foe(2, 900.0, 0.0), foe(3, 200.0, 0.0)
    out = S.shape(team_snap(mate=(800.0, 0.0, 0.0), enemies=[mine, theirs, on_me]), RE5T, S.PAIR)
    assert sorted(e["ptr"] for e in out["enemies"]) == [1, 3]
    out = S.shape(team_snap(mate=(800.0, 0.0, 0.0), enemies=[theirs]), RE5T, S.PAIR)
    assert [e["ptr"] for e in out["enemies"]] == [2] and out["team_shaped"]["why"] == "partner_crowd"


def test_dead_enemies_pass_through_and_no_partner_changes_nothing():
    dead = foe(9, 0.0, 100.0, hp=0)
    snap = team_snap(enemies=[foe(1, 300.0, 200.0), dead])
    assert dead in S.shape(snap, RE5T, S.TEAMMATE)["enemies"]
    solo = {"player": snap["player"], "enemies": snap["enemies"]}
    assert S.shape(solo, RE5T, S.TEAMMATE) is solo


# --- the teammate's overrides ----------------------------------------------------------------------------------------

class Brain:
    def __init__(self):
        self.seen = []
        self._round_started = 7

    def tick(self, snap):
        self.seen.append(snap)
        return {"hold": {"zl"}}

    def prompt_ok(self, button, snap, now):
        return True

    def save(self):
        self.saved = True


def mate_for(title, brain=None, mode=S.TEAMMATE):
    clock = [0.0]
    bot = brain or Brain()
    return S.Teammate(bot, title, mode, {}, clock=lambda: clock[0]), bot, clock


def test_a_dying_partner_is_walked_to_and_helped_with_the_partner_action():
    t, bot, clock = mate_for(RE5T)
    far = team_snap(mate=(0.0, 0.0, 600.0), mate_hp=1)          # dead ahead, 6 m
    assert t.tick(far)["hold"] == {"lup"} and t.stats["team_act"] == "to_dying_partner"
    near = team_snap(mate=(0.0, 0.0, 100.0), mate_hp=1)
    presses = []
    for i in range(8):
        clock[0] = i * 0.1
        presses.append("a" in t.tick(near)["hold"])
    assert any(presses) and not all(presses) and t.stats["team_revives"] >= 1 and bot.seen == []


def test_a_held_partner_within_reach_gets_the_partner_action_else_his_grabbers_are_shot():
    t, bot, clock = mate_for(RE5T)
    grabber = foe(1, 110.0, 20.0)
    held_near = team_snap(mate=(100.0, 0.0, 0.0), mate_motion=106, enemies=[grabber])
    clock[0] = 1.0
    assert t.tick(held_near)["hold"] == {"a"} and t.stats["team_act"] == "help_held"
    held_far = team_snap(mate=(600.0, 0.0, 0.0), mate_motion=106, enemies=[foe(1, 610.0, 20.0), foe(2, -900, 0)])
    assert t.tick(held_far) == {"hold": {"zl"}}
    assert [e["ptr"] for e in bot.seen[-1]["enemies"]] == [1]


def test_far_from_the_partner_with_nothing_near_the_bot_walks_back():
    t, bot, _ = mate_for(RE5T)
    behind_right = team_snap(mate=(-1200.0, 0.0, -400.0))
    keys = t.tick(behind_right)["hold"]
    assert ("rleft" in keys or "rright" in keys) and t.stats["team_act"] == "follow"
    ahead = team_snap(mate=(0.0, 0.0, 2000.0))
    assert t.tick(ahead)["hold"] == {"lup", "b"}               # far and straight ahead: run
    mid = team_snap(mate=(0.0, 0.0, 600.0))                     # inside the band: still following (hysteresis)
    assert t.tick(mid)["hold"] == {"lup"}
    close = team_snap(mate=(0.0, 0.0, 400.0))
    assert t.tick(close) == {"hold": {"zl"}} and t.stats["team_act"] == "fight"
    threatened = team_snap(mate=(0.0, 0.0, 2000.0), enemies=[foe(1, 100.0, 100.0)])
    assert t.tick(threatened) == {"hold": {"zl"}}              # an enemy on the bot: fight first


def test_re6_follows_along_its_own_camera():
    t, _, _ = mate_for(S.TITLES[R6.MAP_ID])
    snap = team_snap(mate=(2000.0, 0.0, 0.0))                   # along +x: yaw 90 deg
    snap["player"]["state"] = 0
    snap["partner"]["state"] = 0
    snap["camera"] = {"yaw": 0.0}
    keys = t.tick(snap)["hold"]
    assert "rleft" in keys and "lup" in keys                    # the camera turns toward him while walking
    snap["camera"] = {"yaw": math.pi / 2}
    assert t.tick(snap)["hold"] == {"lup", "b"}


def test_the_bots_own_trouble_is_the_brains():
    t, bot, _ = mate_for(RE5T)
    snap = team_snap(mate=(0.0, 0.0, 600.0), mate_hp=1)
    snap["player"]["motion"] = 107                              # he is held himself
    assert t.tick(snap) == {"hold": {"zl"}} and bot.seen[-1] is snap
    assert t._round_started == 7                                # the engine's view of the brain is the brain's


# --- two bots on one loop --------------------------------------------------------------------------------------------

def test_a_pair_prefixes_player_twos_keys_and_holds_its_taps_briefly():
    clock = [0.0]

    class Tapper(Brain):
        def tick(self, snap):
            return {"tap": "a"}
    one = S.Teammate(Brain(), RE5T, S.PAIR, {}, clock=lambda: clock[0])
    two = S.Teammate(Tapper(), RE5T, S.PAIR, {"shots": 4}, clock=lambda: clock[0])
    stats = {}
    pair = S.Pair(one, two, stats, clock=lambda: clock[0])
    snap = team_snap(mate=(300.0, 0.0, 0.0))
    snap["p2"] = team_snap(me=(300.0, 0.0, 0.0), mate=(0.0, 0.0, 0.0))
    assert pair.tick(snap)["hold"] == {"zl", "p2:a"}
    clock[0] = S.TAP_S + 0.01
    assert "p2:a" in pair.tick(snap)["hold"]                    # tapped again: held again
    assert stats["p2_shots"] == 4 and pair._round_started == 7
    del snap["p2"]
    assert pair.tick(snap)["hold"] == {"zl"}                    # no Player 2 snapshot: nothing for Player 2


# --- the driver ------------------------------------------------------------------------------------------------------

def test_the_teammate_driver_plays_player_two_with_the_operator_as_partner():
    g, p1, p2 = re5_two()
    d = S.CoopDriver(R5.MAP_ID, S.TEAMMATE, clock=lambda: 0.0)
    snap = d.snapshot(g)
    assert snap["player"]["ptr"] == p2 and snap["partner"]["pos"] == (0.0, 0.0, 0.0)
    assert snap["partner_laser"]["at"] == (0.0, 120.0, 900.0) and snap["coop_mode"] == S.TEAMMATE
    assert d.control == 1 and d.screen(g, snap) == "playing" and d.solo_p1 is False
    brain = d.brain(g, {}, lambda: 0.0)
    assert isinstance(brain, S.Teammate) and brain.mode == S.TEAMMATE


def test_the_pair_driver_carries_both_snapshots_each_with_its_partner():
    g, p1, p2 = re5_two()
    d = S.CoopDriver(R5.MAP_ID, S.PAIR, clock=lambda: 0.0)
    snap = d.snapshot(g)
    assert snap["player"]["ptr"] == p1 and snap["p2"]["player"]["ptr"] == p2
    assert snap["partner"]["pos"] == (500.0, 0.0, 100.0) and snap["p2"]["partner"]["pos"] == (0.0, 0.0, 0.0)
    stats = {}
    brain = d.brain(g, stats, lambda: 0.0)
    assert isinstance(brain, S.Pair) and brain.two.stats is d.p2_stats and brain.one.stats is stats


def test_readiness_needs_player_two_in_ram_and_its_verified_pad():
    g, p1, p2 = re5_two()
    d = S.CoopDriver(R5.MAP_ID, S.TEAMMATE)
    g.adapter = type("Ad", (), {"teammate_pad_status": lambda self: {"verified": True, "prepared": True}})()
    ev = d.readiness(g)
    assert ev["p2_verified"] and ev["controller2_verified"] and [r["slot"] for r in ev["active_players"]] == [1, 2]
    g.adapter = type("Ad", (), {"teammate_pad_status": lambda self: {"verified": False, "reason": "no pad"}})()
    ev = d.readiness(g)
    assert not ev["p2_verified"] and ev["p2_actor_verified"] and ev["reason"] == "no pad"
    g2, _, _ = re5_two(p2_index=0)
    g2.adapter = g.adapter
    assert d.readiness(g2)["reason"].startswith("Player 2 has not joined")


def test_player_two_takes_its_character_after_player_one():
    sent, clock = [], [0.0]
    mp = S.MenuPartner(sent.append, clock=lambda: clock[0], after_s=2.0, sleep=lambda s: None)
    assert not mp.step({"where": "select_stage"})
    assert not mp.step({"where": "select_player"})              # the operator picks first
    clock[0] = 2.5
    assert mp.step({"where": "select_player"})
    assert sent == [[{"key": "a", "down": True, "player": 2}], [{"key": "a", "down": False, "player": 2}]]
    clock[0] = 3.0
    assert not mp.step({"where": "select_player"})              # one press per MENU_GAP_S
