"""Grenades at packs (gbox.mercs.core.combat.ThrowPolicy; the operator 2026-11-10: grenades at the enemies all the time,
also while fleeing): the shared policy, and each title's own path - RE5 Switch's D-pad slot (the native attach),
_mastery's throw and _gun_back; RE4 Switch's in-hand swap (re4_switch_mods, asked through HAND_REQUEST) and its aim +
fire. RE6 has only the profile's hook (its grenades are another branch's)."""
import math
import struct

import pytest

from gbox.mercs.core import combat as C
from gbox.mercs.titles import re4_switch as D
from gbox.mercs.titles import re4_switch_mods as M
from gbox.mercs.titles import re4_weapons as W
from gbox.mercs.titles import re5_switch as R5
from gbox.mercs.titles import re6_switch as R6

P = C.TitleProfile(title="t", throw_kinds=("hand", "fire", "flash"), grab_r_cm=120.0)
ME = {"pos": (0.0, 0.0, 0.0), "rot": 0.0}


def foe(ptr, x, z, **kw):
    return dict({"ptr": ptr, "pos": (x, 0.0, z), "hp": 300, "hp_max": 300}, **kw)


def pack(n=3, z=800.0, spread=60.0, first=10):
    return [foe(first + i, spread * (i - 1), z) for i in range(n)]


# --- the policy ----------------------------------------------------------------------------------------------------------
def test_a_pack_in_range_gets_a_grenade_at_its_centre():
    t = C.ThrowPolicy({}).decide(P, 10.0, ME, pack(), {"hand", "flash"})
    assert t.kind == "hand" and t.n == 3 and t.point == pytest.approx((0.0, 0.0, 800.0)) and not t.fleeing
    assert C.ThrowPolicy({}).decide(P, 10.0, ME, pack(), {"fire"}).kind == "fire", "the incendiary when no hand one"
    assert C.ThrowPolicy({}).decide(P, 10.0, ME, pack(2), {"hand"}) is None, "two are no pack"
    assert C.ThrowPolicy({}).decide(P, 10.0, ME, pack(), set()) is None, "nothing in his kit"
    assert C.ThrowPolicy({}).decide(C.TitleProfile(title="none"), 10.0, ME, pack(), {"hand"}) is None, "no path"


def test_never_into_his_own_blast_nor_past_the_throws_reach():
    assert C.ThrowPolicy({}).decide(P, 10.0, ME, pack(z=400.0), {"hand"}) is None, "the centre inside his blast"
    assert C.ThrowPolicy({}).decide(P, 10.0, ME, pack(z=1500.0), {"hand"}) is None, "out of reach"


def test_a_boss_alone_is_worth_a_grenade_and_the_bigger_pack_comes_first():
    tiered = C.TitleProfile(title="t", throw_kinds=("hand",), tier=C.hp_tier(boss_hp=3000))
    t = C.ThrowPolicy({}).decide(tiered, 10.0, ME, [foe(1, 0.0, 900.0, hp_max=5000)], {"hand"})
    assert t is not None and t.target["ptr"] == 1 and "boss" in t.why
    big, small = pack(4, z=1000.0, first=20), pack(3, z=700.0, spread=40.0, first=30)
    small = [dict(e, pos=(e["pos"][0] + 600.0, 0.0, e["pos"][2])) for e in small]
    assert C.ThrowPolicy({}).decide(P, 10.0, ME, big + small, {"hand"}).n == 4


def test_a_flash_at_a_wind_up_or_a_grab_and_never_more_often_than_the_gap():
    wind = C.TitleProfile(title="t", throw_kinds=("hand", "flash"), windup=lambda e: e.get("motion") == 81)
    near = [foe(1, 0.0, 250.0, motion=81)]
    t = C.ThrowPolicy({}).decide(wind, 10.0, ME, near, {"hand", "flash"})
    assert t.kind == "flash" and "winding up" in t.why
    t = C.ThrowPolicy({}).decide(P, 10.0, ME, [foe(1, 0.0, 100.0)], {"flash"})
    assert t.kind == "flash" and "arm's length" in t.why
    pol = C.ThrowPolicy({})
    pol.started(10.0)
    assert pol.decide(P, 10.0 + P.throw_gap_s - 0.1, ME, pack(), {"hand"}) is None
    assert pol.decide(P, 10.0 + P.throw_gap_s, ME, pack(), {"hand"}) is not None


def test_fleeing_throws_count_and_the_kills_after_a_throw_are_its_own():
    pol = C.ThrowPolicy({})
    t = pol.decide(P, 10.0, ME, pack(), {"hand"}, fleeing=True)
    assert t.fleeing and "as he runs" in t.why
    pol.thrown(11.0, fleeing=True, kills=5)
    pol.observe(P, 12.0, 7)
    pol.observe(P, 13.5, 8)
    pol.observe(P, 20.0, 12)                                            # long after: the gun's, not the grenade's
    assert pol.stats["grenade_throws"] == 1 and pol.stats["throws_while_fleeing"] == 1
    assert pol.stats["grenade_kills"] == 3


def test_every_title_has_the_profile_hook():
    p6 = R6.combat_profile()
    assert p6.throw_kinds == () and (p6.pack_n, p6.throw_min_cm, p6.throw_max_cm) == (R6.NADE_N, R6.NADE_MIN_R,
                                                                                      R6.NADE_MAX_R), \
        "RE6: the hook only, with its own grenade distances (its grenades are another branch's)"
    assert R5.combat_profile().throw_kinds == ("hand", "fire", "flash")
    assert D.combat_profile().throw_kinds == (), "RE4: off until a watched round"


# --- RE5 Switch: its own path ------------------------------------------------------------------------------------------
def re5_bot():
    clock = [0.0]
    return R5.Bot(stats={}, clock=lambda: clock[0]), clock


def re5_inv(grenade_in_hand=False, rounds=5):
    return [{"slot": 0, "id": 0x103, "item": 0x03, "type": 1, "rounds": 15, "cap": 15, "grid": 3,
             "hand": not grenade_in_hand},
            {"slot": 1, "id": 0x106, "item": 0x06, "type": 1, "rounds": rounds, "cap": 5, "grid": 1,
             "hand": grenade_in_hand}]


def re5_snap(inv, kills=0):
    p = {"ptr": 1, "pos": (0.0, 0.0, 0.0), "rot": 0.0, "hp": 1000, "hp_max": 1000, "motion": 0, "aim_pitch": None}
    return p, {"player": p, "enemies": [dict(e, **{"class": "uEm10", "motion": 4}) for e in pack(z=800.0)],
               "inventory": inv, "kills": kills, "laser": {"up": False}, "mercenaries_phase": R5.PHASE_PLAYING}


def test_re5_equips_the_grenade_by_its_slot_throws_it_and_the_gun_comes_back():
    b, _ = re5_bot()
    p, s = re5_snap(re5_inv())
    live, flat = s["enemies"], lambda e: math.hypot(e["pos"][0], e["pos"][2])
    act = b._throw_core(p, s, live, flat, 1.0)
    assert act == {"tap": "dup"} and b.doing == "rearm" and b.stats["throw_starts"] == 1, "the D-pad slot: no item screen"
    assert b._throw_core(p, s, live, flat, 1.1) == {"hold": ()}, "the tap paced, the gun down"
    p, s = re5_snap(re5_inv(grenade_in_hand=True))
    act = b._throw_core(p, s, live, flat, 1.3)                          # in hand: _mastery's throw controller
    assert act is not None and b._uc_throw["phase"] == "throw"
    b.stats["shots"] += 1                                              # the controller's ZR edge
    assert b._throw_core(p, s, live, flat, 1.5) == {"hold": ()} and b.stats["grenade_throws"] == 1
    assert b._throw_core(p, s, live, flat, 1.5 + R5.THROW_SETTLE_S + 0.01) is None and b._uc_throw is None
    assert b._gun_back(s, 2.2) == {"tap": "dleft"}, "the gun's own D-pad slot right after"
    assert b._throw_core(p, s, live, flat, 2.5) is None, "the next only after THROW_GAP_S"


def test_re5_throws_back_at_the_pursuers_while_he_runs_and_gives_up_a_grenade_that_never_comes():
    b, _ = re5_bot()
    p, s = re5_snap(re5_inv())
    live, flat = s["enemies"], lambda e: math.hypot(e["pos"][0], e["pos"][2])
    b.escape = (math.pi, 10.0)                                         # an escape run under way
    b._throw_core(p, s, live, flat, 1.0)
    assert b._uc_throw["plan"].fleeing
    assert b._throw_core(p, s, live, flat, 1.0 + R5.THROW_EQUIP_S + 0.1) is None
    assert b.stats["throw_aborts"] == 1 and "never came" in b.stats["throw_abort_last"]


def test_re5_s_tick_starts_the_throw_and_the_flag_turns_it_off(monkeypatch):
    for k, v in (("PS3_BRAIN", False), ("HEAL_ENABLED", False), ("MINES", False)):
        monkeypatch.setattr(R5, k, v)
    b, clock = re5_bot()
    _p, s = re5_snap(re5_inv())
    clock[0] = 1.0
    act = b.tick(s)
    assert b.stats.get("throw_starts") == 1 and act.get("tap") == "dup"
    monkeypatch.setattr(R5, "THROWS", False)
    b2, clock2 = re5_bot()
    clock2[0] = 1.0
    b2.tick(s)
    assert not b2.stats.get("throw_starts")


# --- RE4 Switch: the in-hand swap and the aim + fire -------------------------------------------------------------------
def r4snap(enemies):
    return {"player": {"pos": (0.0, 0.0, 0.0), "rot": 0.0, "hp": 1000, "ptr": 1},
            "enemies": [dict(e, pos=tuple(v * D.MM_PER_CM for v in e["pos"])) for e in enemies]}


def answer(item):
    """re4_switch_mods.maintain's answer to the last ask."""
    D.HAND_STATE.update(seq=D.HAND_REQUEST.get("seq"), item=item, verified=True, error="")


def test_re4_asks_for_the_grenade_aims_throws_and_asks_for_the_gun_back(monkeypatch):
    monkeypatch.setattr(D, "THROWS", True)
    b = D.Bot(stats={}, director=False)
    s = r4snap(pack(z=800.0))
    act = b.tick(s, now=1.0)
    assert D.HAND_REQUEST["item"] == 0x01 and b.doing == "throw" and act["hold"] == set()
    answer(0x01)
    acts = [b.tick(s, now=1.0 + 0.05 * k) for k in range(1, 12)]
    assert any(a.get("tap") == D.FIRE_BTN and D.AIM_BTN in a["hold"] for a in acts), "ZL, then ZR: the throw"
    assert b.stats["grenade_throws"] == 1
    for k in range(12, 40):
        b.tick(s, now=1.0 + 0.05 * k)
        if D.HAND_REQUEST.get("item") is None:
            break
    assert D.HAND_REQUEST["item"] is None, "the gun back after the follow-through"
    answer(None)
    b.tick(s, now=3.5)
    assert b.__dict__.get("_uc_throw") is None


def test_re4_drops_a_blast_throw_with_one_at_arms_length_and_a_swap_that_did_not_take(monkeypatch):
    monkeypatch.setattr(D, "THROWS", True)
    b = D.Bot(stats={}, director=False)
    b.tick(r4snap(pack(z=800.0)), now=1.0)
    hug = r4snap(pack(z=800.0) + [foe(99, 0.0, 100.0)])
    b.tick(hug, now=1.05)
    assert D.HAND_REQUEST["item"] is None and b.stats["throw_aborts"] == 1
    b2 = D.Bot(stats={}, director=False)
    b2.tick(r4snap(pack(z=800.0)), now=1.0)
    D.HAND_STATE.update(seq=D.HAND_REQUEST["seq"], item=None, verified=False, error="no weapon row")
    b2.tick(r4snap(pack(z=800.0)), now=1.1)
    assert D.HAND_REQUEST["item"] is None and "no weapon row" in b2.stats["throw_abort_last"]


# --- RE4 Switch: re4_switch_mods' side, on a fake guest memory -----------------------------------------------------------
BASE, ITEM, GUN = 0x3CA7C04000, 0x5D50020000, 0x27


class Guest:
    def __init__(self):
        self.mem = bytearray(0)
        self.at: dict = {}

    def put(self, a, b):
        for i, v in enumerate(b):
            self.at[a + i] = v

    def read_memory(self, a, n):
        return bytes(self.at.get(a + i, 0) for i in range(n))

    def write_memory(self, a, b):
        self.put(a, bytes(b))


def guest():
    g = Guest()
    gobj = BASE + W.GAME_OBJ
    g.put(BASE + W.GAME_PTR_VAR, struct.pack("<Q", gobj))
    g.put(BASE + W.ITEM_MGR + W.M_EQUIPPED, struct.pack("<Q", ITEM))
    g.put(BASE + W.ITEM_MGR + W.M_EQUIPPED_ID, struct.pack("<H", GUN))
    g.put(ITEM, struct.pack("<HHBBHHBBBB", GUN, 1, 1, 0, 0x2114, 13 << 3, 2, 3, 0, 1))
    g.put(gobj + W.G_CLASS, bytes([0x04, 0, 0, 4, 1, 2]))
    g.put(gobj + W.G_RELOAD, bytes([1]))
    rows = bytearray(W.WEAPON_N * W.WEAPON_SZ)
    struct.pack_into("<HBBBBH7H", rows, 0, GUN, 0, 0x04, 0, 0, 0x04, 10, 12, 14, 16, 18, 20, 0)
    struct.pack_into("<HBBBBH7H", rows, W.WEAPON_SZ, 0x01, 0, 0x13, 0, 0, 0, 1, 1, 1, 1, 1, 1, 0)
    g.put(BASE + W.WEAPON_TBL, bytes(rows))
    return g


def test_re4_mods_hold_the_grenade_then_write_the_gun_back_byte_for_byte(monkeypatch):
    import time
    g = guest()
    before = g.read_memory(ITEM, W.ITEM_SZ), g.read_memory(BASE + W.GAME_OBJ + W.G_CLASS, 6)
    D.HAND_REQUEST.update(item=0x01, seq=1, at=time.monotonic())
    assert M._hand(g, {"module_base": BASE}) == 1
    assert D.HAND_STATE == {"seq": 1, "item": 0x01, "verified": True, "error": ""}
    assert struct.unpack("<H", g.read_memory(ITEM, 2))[0] == 0x01
    assert struct.unpack("<H", g.read_memory(BASE + W.ITEM_MGR + W.M_EQUIPPED_ID, 2))[0] == 0x01
    assert g.read_memory(BASE + W.GAME_OBJ + W.G_CLASS, 1)[0] == 0x13
    assert M._hand(g, {"module_base": BASE}) == 0, "answered once"
    D.HAND_REQUEST.update(item=None, seq=2, at=time.monotonic())
    assert M._hand(g, {"module_base": BASE}) == 1 and D.HAND_STATE["verified"] and D.HAND_STATE["item"] is None
    assert (g.read_memory(ITEM, W.ITEM_SZ), g.read_memory(BASE + W.GAME_OBJ + W.G_CLASS, 6)) == before
    assert struct.unpack("<H", g.read_memory(BASE + W.ITEM_MGR + W.M_EQUIPPED_ID, 2))[0] == GUN


def test_re4_mods_put_the_gun_back_when_the_ask_goes_stale_and_never_swap_an_empty_hand():
    g = guest()
    D.HAND_REQUEST.update(item=0x01, seq=1, at=0.0)                    # a bot gone mid-throw: long stale
    assert M._hand(g, {"module_base": BASE}) == 0 and D.HAND_STATE["item"] is None
    import time
    empty = Guest()
    empty.put(BASE + W.GAME_PTR_VAR, struct.pack("<Q", BASE + W.GAME_OBJ))
    empty.put(BASE + W.ITEM_MGR + W.M_EQUIPPED_ID, struct.pack("<H", W.NO_WEAPON))
    D.HAND_REQUEST.update(item=0x01, seq=3, at=time.monotonic())
    M._hand(empty, {"module_base": BASE})
    assert D.HAND_STATE["verified"] is False and "nothing in his hand" in D.HAND_STATE["error"]
