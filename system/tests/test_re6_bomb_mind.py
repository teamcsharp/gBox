"""RE6 Switch: the remote bombs set off "with his mind" (the detonator's own flag), the gun back by the hook, no item
wheel, grenades thrown on the move, the bot's grenade ring, and the coached moment of request 5482 (note 7).

Synthetic memory: test_re6_switch's Guest / round_guest / Adapter (main at BASE, a heap, sUnit's lines)."""
import json
import math
import struct
from pathlib import Path

import pytest

from gbox.mercs.titles import re6_switch as R
from gbox.mercs.titles import re6_switch_mods as M
from tests.test_re6_switch import BASE, Adapter, round_guest, run, brain   # noqa: F401 - the fixtures' guest
from tests.test_re6_switch_equip import NativeBridge

FIXTURE = Path(__file__).parent / "fixtures" / "mercs_incidents" / "re6_switch_coach_5482_7.json"


@pytest.fixture(autouse=True)
def _fresh():
    M.ORIG.clear()
    M._UNIT_NAMES.clear()
    for cache in (R._FOUND, R._MISS):
        cache.clear()
    yield
    M.ORIG.clear()


def player_of(g):
    return R.u64(g, R.u64(g, BASE + R.S_PLAYER) + R.P_FIRST)


def bomb_guest(armed=True, owner=None, action="cWpAction_wp_act_setting", slot_mode=1, bombs=1):
    """A round with his remote bomb slot (wheel index 12, type 0x116) out and `bombs` uWp1097 lying placed on line 13."""
    g = round_guest(enemies=((0.0, 0.0, 900.0, 700),))
    p = player_of(g)
    slot = p + M.SLOTS + M.SLOT_STRIDE * 12
    g.q(slot, BASE + M.SLOT_VTABLE)
    g.put(slot + M.SLOT_USED, bytes([1, R.BOMB_INDEX]) + struct.pack("<H", R.BOMB_TYPE))
    g.put(slot + R.SLOT_MODE, bytes([slot_mode]))
    g.put(slot + 0xE, struct.pack("<h", 4))
    g.put(p + M.ARMED_BYTE, bytes([0x41 | (M.ARMED_BIT if armed else 0)]))    # other bits of the byte stay as they are
    units = []
    for i in range(bombs):
        u = g.unit(13, M.REMOTE_BOMB_CLASS, size=0x4000)
        g.q(u + M.U_OWNER, p if owner is None else owner)
        g.put(u + M.U_GENERATION, struct.pack("<I", 77 + i))
        g.q(u + M.U_ACTION, g.obj(action, 0x100))
        g.f32(u + R.P_POS, 0.0, 0.0, 300.0 + 10 * i)
        units.append(u)
    g.unit(13, "uWp1095", size=0x4000)                                         # a flash in the air: not his bomb
    return g, p, units


class GameAdapter(Adapter):
    """The game's own answer to the hook: a placed bomb reading the flag clear requests its explosion (action 10)."""

    def __init__(self, g, player, units):
        super().__init__(g)
        self.player, self.units = player, units

    def write_memory(self, a, data):
        out = super().write_memory(a, data)
        if a == self.player + M.ARMED_BYTE and not data[0] & M.ARMED_BIT:
            for u in self.units:
                self.g.q(u + M.U_ACTION, self.g.obj(M.ACT_BLAST, 0x100))
        return out


# --- the hook ------------------------------------------------------------------------------------------------------

def test_detonate_clears_only_the_armed_bit_and_names_his_placed_bombs():
    g, p, units = bomb_guest(bombs=2)
    ad = Adapter(g)
    out = M.detonate(ad)
    assert out["verified"] and out["count"] == 2 and out["detonated"] == units
    assert out["armed_before"] is True and out["armed_after"] is False
    assert g.rd(p + M.ARMED_BYTE, 1)[0] == 0x41                               # bit 0x20 alone cleared
    assert ad.writes == [(p + M.ARMED_BYTE, bytes([0x41]))]                    # one byte written, nothing else
    assert M.ORIG[id(ad)]["mind_detonations"] == 1


def test_detonate_waits_for_the_games_own_blast():
    g, p, units = bomb_guest()
    ad = GameAdapter(g, p, units)
    out = M.detonate(ad, wait_s=0.2)
    assert out["verified"] and out["went_off"] == units and out["pending"] == []


@pytest.mark.parametrize("case, reason", [
    ("unarmed", "not armed"), ("none", "no remote bomb"), ("theirs", "no remote bomb"),
    ("results", "no round playing"), ("dead", "not alive"), ("chosen", "not one of his")])
def test_detonate_refuses_and_writes_nothing(case, reason):
    g, p, units = bomb_guest(armed=case != "unarmed", bombs=0 if case == "none" else 1,
                             owner=0x5D00099990 if case == "theirs" else None)
    if case == "results":
        g.i32(R.u64(g, BASE + R.S_GAMEMAN) + R.GM_PHASE, R.PHASE_OVER)
    if case == "dead":
        g.put(p + R.P_HP, struct.pack("<h", 0))
    ad = Adapter(g)
    out = M.detonate(ad, unit=0x1234 if case == "chosen" else None)
    assert not out["verified"] and reason in out["reason"] and ad.writes == []


def test_detonate_refuses_a_snapshot_of_another_life():
    g, p, units = bomb_guest()
    ad = Adapter(g)
    snap = R.snapshot(g)
    snap["player"]["generation"] = (snap["player"]["generation"] or 0) + 1   # the snapshot's life is not this one
    out = M.detonate(ad, snap)
    assert not out["verified"] and "changed" in out["reason"] and ad.writes == []


def test_the_snapshot_reads_the_detonators_flag_with_the_slot():
    g, p, units = bomb_guest()
    assert R.snapshot(g)["player"]["bomb"] == {"count": 4, "out": True, "armed": True}
    g.put(p + M.ARMED_BYTE, bytes([0x41]))
    assert R.snapshot(g)["player"]["bomb"]["armed"] is False


def test_settle_remote_puts_the_games_own_zero_back_only_with_nothing_out():
    g, p, units = bomb_guest(bombs=0, armed=False)
    ad = Adapter(g)
    out = M.settle_remote(ad, p)
    assert out["settled"] and g.rd(out["slot"], 1) == b"\0"
    M._UNIT_NAMES.clear()                                                     # (another fake boot, same base)
    g2, p2, _ = bomb_guest(armed=False)                                       # a bomb still lying: nothing
    ad2 = Adapter(g2)
    assert not M.settle_remote(ad2, p2)["settled"] and ad2.writes == []


def test_run_routes_the_detonate_and_bomb_mind_ops(monkeypatch):
    monkeypatch.setattr(R, "BOMB_MIND", True)
    g, p, units = bomb_guest()
    ad = GameAdapter(g, p, units)
    out = M.run(ad, "remote_detonate")
    assert out["verified"] and out["count"] == 1 and out["went_off"] == units
    assert M.run(ad, "bomb_mind", on=False)["bomb_mind"] is False and R.BOMB_MIND is False
    assert M.run(ad, "status")["bomb_mind"] is False
    M.run(ad, "bomb_mind", on=True)
    assert M.run(ad, "status")["bot"]["bomb_mind"] is True


def test_throw_and_magnum_speed_run_without_fire_rate():
    """Operator 2026-11-10: the grenades' throw at 20x and the magnum's fire / recoil at 20x, fire_rate set or not."""
    g = round_guest()
    ad = Adapter(g)
    p = player_of(g)
    g.f32(p + M.UNIT_DELTA, 1.0)
    g.put(p + R.P_SLOTS + 8, bytes([1, 0]) + struct.pack("<H", 0x107))       # the magnum in slot 0, equipped
    g.i32(p + R.P_EQUIPPED, 0)
    g.q(p + M.UNIT_ACTION, g.obj("cPlAction_pl_act_weapon_fire", 0x100))
    M.run(ad, "status")                                                       # this boot's state, no fire_rate
    M.maintain(ad, R.snapshot(g), clock=lambda: 10.0)
    assert struct.unpack("<f", g.rd(p + M.UNIT_DELTA, 4))[0] == M.MAGNUM_SPEED_X == 20.0
    g.put(p + R.P_SLOTS + 8, bytes([1, 0]) + struct.pack("<H", 0x113))       # a hand grenade's throw
    M.maintain(ad, R.snapshot(g), clock=lambda: 10.0)
    assert struct.unpack("<f", g.rd(p + M.UNIT_DELTA, 4))[0] == M.THROW_SPEED_X == 20.0
    assert M.run(ad, "status")["throw_speed_x"] == 20.0 and M.run(ad, "status")["magnum_speed_x"] == 20.0


def test_the_profile_runs_the_magnum_at_20x_and_its_records_at_the_shotguns_multiplier():
    prof = json.loads((Path(__file__).parents[1] / "profiles" / "gamedata" / "01002A000CD48000-ram.json").read_text())
    ops = dict((op, args) for op, args in prof["mercs"]["playing_ops"])
    assert ops["magnum_speed"]["multiplier"] == 20
    assert ops["fire_rate"]["magnum"] == ops["fire_rate"]["multiplier"]      # the shotguns' (the play cap FIRE_MAX)


# --- the bot ------------------------------------------------------------------------------------------------------

class FakeMind:
    def __init__(self, ok=True):
        self.ok, self.calls, self.settles = ok, [], []

    def ready(self, stats=None):
        return True

    def __call__(self, snap):
        self.calls.append(snap.get("kills"))
        return {"verified": True, "count": 1} if self.ok else {"verified": False, "reason": "flag read back set"}

    def settle(self, player):
        self.settles.append(player)
        return {"verified": True, "settled": True}


def mind_bot(enemies, ok=True):
    clock = [0.0]
    bridge, mind = NativeBridge(), FakeMind(ok)
    bot = R.Bot(stats={}, clock=lambda: clock[0], equip=bridge, mind=mind)
    snap = R.snapshot(round_guest(enemies=enemies))
    snap["player"].update(equipped=R.BOMB_INDEX, bomb={"count": 5, "out": True, "armed": True},
                          guns={0x107: 0, 0x104: 1}, gun_ammo={0: 7, 1: 8})
    bot.held = lambda p, now: False
    bot.bomb_at, bot.bomb_since, bot.bomb_from, bot.bomb_phase = (0.0, R.BOMB_AHEAD), 0.0, (0.0, 0.0), "wait"
    return bot, bridge, mind, clock, snap


def test_with_a_bomb_out_the_gun_comes_back_at_once_and_the_hook_sets_it_off_under_the_rules(monkeypatch):
    monkeypatch.setattr(R, "BOMB_MIND", True)
    far = ((0.0, 0.0, 2500.0, 700),)                                          # nobody near: nothing due yet
    bot, bridge, mind, clock, snap = mind_bot(far)
    snap["player"]["pos"] = (0.0, 0.0, R.BOMB_AHEAD - bot.book.safe - 100.0)  # clear of its reach
    acts = run(bot, snap, clock, 2)
    assert bot.stats["bomb_gun_backs"] >= 1 and bridge.targets and bridge.targets[0] == 0   # the magnum, by the hook
    assert all(not ({a.get("tap")} | set(a.get("hold") or ())) & R.DPAD_KEYS for a in acts)
    snap["player"]["equipped"] = 0                                            # the gun in hand
    run(bot, snap, clock, 4)
    assert mind.calls == [] and bot.bomb_phase == "wait"                      # he fights on: nothing on it yet
    snap["enemies"][0]["pos"] = (40.0, 0.0, R.BOMB_AHEAD + 30.0)              # one walks onto it
    run(bot, snap, clock, 1)
    assert mind.calls and bot.stats["bombs_mind_detonated"] == 1 and bot.bomb_phase == "mind"
    assert bot.stats["bomb_det_cm"] == [round(bot.book.safe + 100.0)]
    snap["player"]["bomb"] = {"count": 5, "out": True, "armed": False}       # the flag clear: the blast
    run(bot, snap, clock, 1)
    assert bot.stats["bombs_detonated"] == 1 and bot.bomb_phase is None and bot.stats["bomb_mind_failures"] == 0
    run(bot, snap, clock, int(R.MIND_SETTLE_S / 0.05) + 2)                   # the slot stuck at "out": put back
    assert mind.settles and bot.stats["remote_settles"] >= 1
    assert bot.stats["wheel_presses"] == 0


def test_never_inside_the_learned_reach_whatever_is_on_it(monkeypatch):
    monkeypatch.setattr(R, "BOMB_MIND", True)
    bot, bridge, mind, clock, snap = mind_bot(((40.0, 0.0, R.BOMB_AHEAD + 30.0, 700),))
    snap["player"].update(equipped=0, pos=(0.0, 0.0, R.BOMB_AHEAD - bot.book.safe + 150.0))   # inside the rule
    run(bot, snap, clock, 6)
    assert mind.calls == []


def test_a_hook_that_fails_falls_back_to_the_detonator_press(monkeypatch):
    monkeypatch.setattr(R, "BOMB_MIND", True)
    bot, bridge, mind, clock, snap = mind_bot(((40.0, 0.0, R.BOMB_AHEAD + 30.0, 700),), ok=False)
    snap["player"].update(equipped=0, pos=(0.0, 0.0, R.BOMB_AHEAD - bot.book.safe - 100.0))
    run(bot, snap, clock, 1)
    assert bot.stats["bomb_mind_failures"] == 1 and "flag" in bot.stats["bomb_mind_reason"]
    assert bot.bomb_phase == "det_aim"                                        # ZL + ZR with the remote, for a while
    assert bot.mind_fail_until > clock[0]


def test_a_hook_blast_that_never_shows_is_a_failure_and_the_press_follows(monkeypatch):
    monkeypatch.setattr(R, "BOMB_MIND", True)
    bot, bridge, mind, clock, snap = mind_bot(((40.0, 0.0, R.BOMB_AHEAD + 30.0, 700),))
    snap["player"].update(equipped=0, pos=(0.0, 0.0, R.BOMB_AHEAD - bot.book.safe - 100.0))
    run(bot, snap, clock, 1)
    assert bot.bomb_phase == "mind"
    run(bot, snap, clock, int(R.MIND_CONFIRM_S / 0.05) + 2)                  # still armed, still out
    assert bot.stats["bomb_mind_failures"] == 1 and bot.bomb_phase in ("det_aim", "det", "det_wait", "wait")


def test_the_remote_bomb_in_hand_unasked_is_placed_not_put_away(monkeypatch):
    """Live 2026-11-10: the game re-equipped the selected item after every native gun request; with the remote bomb
    that was 594 gun backs a round and no bomb out. With the hook bound he places it, and the gun comes back after."""
    monkeypatch.setattr(R, "BOMB_MIND", True)
    bot, bridge, mind, clock, snap = mind_bot(((0.0, 0.0, 800.0, 700), (100.0, 0.0, 900.0, 700)))
    bot.bomb_phase, bot.bomb_at, bot.bomb_last = None, None, -1e9
    snap["player"]["bomb"] = {"count": 5, "out": False, "armed": False}       # in his hand, none out
    acts = run(bot, snap, clock, int((R.BOMB_FACE_S + R.BOMB_AIM_S) / 0.05) + 4)
    assert bot.stats["held_bomb_places"] == 1 and bot.stats["item_gun_backs"] == 0
    assert any({"zl", "zr"} <= set(a.get("hold") or ()) for a in acts)        # thrown
    snap["player"]["bomb"] = {"count": 5, "out": True, "armed": True}         # out: the gun back by the hook
    run(bot, snap, clock, 2)
    assert bot.stats["bombs_placed"] == 1 and bot.stats["bomb_gun_backs"] >= 1 and 0 in bridge.targets


def test_with_the_hook_bound_no_dpad_key_ever_leaves_the_bot():
    bot = R.Bot(stats={}, equip=NativeBridge())
    assert bot._no_wheel({"tap": "right"}) == {"hold": ()}
    assert bot._no_wheel({"hold": ("up", "zl")}) == {"hold": ("zl",)}
    assert bot._no_wheel({"tap": "r"}) == {"tap": "r"}
    assert bot.stats["wheel_presses_blocked"] == 2 and bot.stats["wheel_presses"] == 0


def test_a_grenade_at_one_in_range_and_thrown_on_the_move_away_from_the_pursuers(monkeypatch):
    # (the throw's mechanics with fire-first off: since 2026-11-10 14:30 the gun answers the one at 3 m first, below)
    monkeypatch.setattr(R, "NADES", True)
    monkeypatch.setattr(R, "FIRE_FIRST", False)
    foes = ((0.0, 0.0, 300.0, 700), (0.0, 0.0, 700.0, 700))                   # one on his heels, one in range
    clock = [0.0]
    bridge = NativeBridge()
    bot = R.Bot(stats={}, clock=lambda: clock[0], equip=bridge)
    snap = R.snapshot(round_guest(enemies=foes, cam_yaw=0.0))
    bot.held = lambda p, now: False
    bot.melee_at = bot.qshot_at = 100.0
    snap["player"].update(equipped=0, nades={0x113: (9, 5)}, guns={0x107: 0}, gun_ammo={0: 7})
    run(bot, snap, clock, 2)
    assert bot.nade is not None and bot.nade["kind"] == "frag" and 9 in bridge.targets   # by the hook
    snap["player"]["equipped"] = 9
    acts = run(bot, snap, clock, int((R.NADE_FACE_S + R.NADE_AIM_S + R.NADE_THROW_S) / 0.05) + 4)
    thrown = [a for a in acts if {"zl", "zr"} <= set(a.get("hold") or ())]
    assert thrown and all("ldown" in a["hold"] for a in thrown)               # backing away from the one at 3 m
    assert bot.stats["nade_flee_throws"] == 1 and bot.stats["frags"] >= 1   # (the in-hand burst may add more)
    assert all(not ({a.get("tap")} | set(a.get("hold") or ())) & R.DPAD_KEYS for a in acts)


def test_fire_first_no_grenade_cycle_at_one_in_clear_sight_up_close(monkeypatch):
    """The operator 2026-11-10 14:30: "the RE6 bot is not proactive enough at shooting" (t_nade 331 s against t_fire 9 s):
    with one in clear sight within FIRE_FIRST_R no grenade cycle starts - the gun answers him."""
    monkeypatch.setattr(R, "NADES", True)
    foes = ((0.0, 0.0, 300.0, 700), (0.0, 0.0, 700.0, 700))
    clock = [0.0]
    bot = R.Bot(stats={}, clock=lambda: clock[0], equip=NativeBridge())
    snap = R.snapshot(round_guest(enemies=foes, cam_yaw=0.0))
    bot.held = lambda p, now: False
    bot.melee_at = bot.qshot_at = 100.0
    snap["player"].update(equipped=0, nades={0x113: (9, 5)}, guns={0x107: 0}, gun_ammo={0: 7})
    run(bot, snap, clock, 6)
    assert bot.nade is None and bot.stats.get("nade_fire_first_skips", 0) >= 1


# --- the coached moment (request 5482, note 7) ---------------------------------------------------------------------

def coach_snapshot():
    fx = json.loads(FIXTURE.read_text())
    me = fx["player"]
    px, py, pz = me["pos"]
    g = round_guest(enemies=(), cam_yaw=me["facing"])
    snap = R.snapshot(g)
    snap["player"].update(pos=(0.0, 0.0, 0.0), rot=me["facing"], hp=me["hp"], hp_max=me["hp_max"], equipped=0,
                          guns={0x107: 0, 0x104: 1}, gun_ammo={0: 7, 1: 8},
                          nades={0x113: (9, 5), 0x114: (10, 5), 0x115: (11, 5)},
                          bomb={"count": 5, "out": False, "armed": False})
    snap["enemies"] = [{"slot": i, "ptr": 0x5D10000000 + 0x1000 * i, "pos": (x - px, y - py, z - pz), "hp": e["hp"],
                        "hp_max": e["hp_max"], "class": e["cls"]}
                       for i, e in enumerate(fx["enemies"]) for x, y, z in [e["pos"]]]
    snap["kills"], snap["combo"] = fx["clock"]["kills"], fx["clock"]["combo"]
    return fx, snap


def test_coach_5482_7_the_pack_gets_the_ring_and_the_grenades_never_the_pillar(monkeypatch):
    """Operator 04:13: "Flawed handling ... running into a wall or corner, or failing to deal with a threat" - he faced
    a pillar on his left with his arm raised while a pack of J'avo, two 1500-health uEm1370 and a uEm3000 came from
    the right at 4-6.5 m. Now: the ring's rule (gbox.mercs.grenade_ring) fires for the dangerous ones within its
    danger_cm, the grenades go at the pack by the hook (no item wheel), and nothing turns him to his left."""
    from gbox.mercs import grenade_ring as GR
    monkeypatch.setattr(R, "NADES", True)
    monkeypatch.setattr(R, "FLASH", True)
    fx, snap = coach_snapshot()
    decision = GR.decide(snap, {"bomb_safe_cm": 700}, 500.0, GR.policy(R), title=R.TITLE_ID)
    # since 2026-11-10 14:3x a flash ring only for a tight surround, and never for the big ones (a flash does not stop
    # them: "Some enemies can't be beaten by a flash and must be killed with weapons")
    assert not decision["fire"] and "not tight" in decision["reason"]
    open_gate = dict(GR.policy(R), flash_tight_n=None, flash_gap_s=None)
    decision = GR.decide(snap, {"bomb_safe_cm": 700}, 500.0, open_gate, title=R.TITLE_ID)
    assert decision["fire"] and "dangerous" in decision["reason"] and decision["radius_cm"] >= 700 + 250
    # fire first (2026-11-10 14:30): a J'avo stands 2.4 m off in the clear - the gun answers him, no grenade cycle yet
    clock = [500.0]
    bot = R.Bot(stats={}, clock=lambda: clock[0], equip=NativeBridge())
    bot._round_started = 400.0
    bot.held = lambda p, now: False
    run(bot, snap, clock, 3)
    assert bot.nade is None and bot.stats.get("nade_fire_first_skips", 0) >= 1
    # the grenade's own handling of the pack (fire-first off): at them, by the hook, never the pillar
    monkeypatch.setattr(R, "FIRE_FIRST", False)
    clock = [500.0]
    bridge = NativeBridge()
    bot = R.Bot(stats={}, clock=lambda: clock[0], equip=bridge)
    bot._round_started = 400.0
    bot.held = lambda p, now: False
    yaw = fx["player"]["facing"]
    acts = run(bot, snap, clock, 3)
    assert bot.nade is not None                                               # a grenade at them at once
    tx, tz = bot.nade["to"]
    rel = R.wrap(R.heading(tx, tz) - yaw)
    assert -math.radians(150) <= rel <= math.radians(20)                     # at the pack (ahead / to his right)
    assert set(bridge.targets) <= {9, 10, 11}                                 # equipped by the hook ...
    snap["player"]["equipped"] = bot.nade["index"]
    acts += run(bot, snap, clock, int((R.NADE_FACE_S + R.NADE_AIM_S + R.NADE_THROW_S + 0.4) / 0.05))
    assert any({"zl", "zr"} <= set(a.get("hold") or ()) for a in acts)        # ... and thrown
    assert all(not ({a.get("tap")} | set(a.get("hold") or ())) & R.DPAD_KEYS for a in acts)   # never the wheel
    assert not any("rleft" in (a.get("hold") or ()) for a in acts)            # never turned to the pillar side
