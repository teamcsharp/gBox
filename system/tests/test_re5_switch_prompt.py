"""RE5 Switch: the game's own prompts (re5_switch_prompt, the sActionButton system, found 2026-10-27 and read live):
the reader over a fake guest, and the bot taking them the moment they show (operator 17:39: "seeing them miss QTE
events"; the hourglass is label 112 press:y on the statue, never pressed before: bonuses_taken 0)."""
import math
import struct

import pytest

from gbox.mercs.titles import re5_switch as R
from gbox.mercs.titles import re5_switch_prompt as P

BASE = 0x3CA7C04000
AB, MGR_BTN, PLAYER = 0x5D10000000, 0x5D20000000, 0x5D30000000


class Guest:
    """A sparse little-endian guest: writes by address, reads zero elsewhere."""

    def __init__(self):
        self.mem = {}

    def put(self, a, data):
        for i, b in enumerate(data):
            self.mem[a + i] = b

    def q(self, a, v):
        self.put(a, struct.pack("<Q", v))

    def rd(self, a, n):
        return bytes(self.mem.get(a + i, 0) for i in range(n))


def guest(kind=1, mode=1, key=1, label=112, shown=True, owner=0x5D40000000, player=4, hp=1000, muted=False):
    g = Guest()
    g.put(BASE + P.KEY_TABLE, struct.pack("<32I", *P.MASKS))
    g.q(BASE + P.S_ACTION, AB)
    g.q(AB, BASE + P.AB_VT)
    g.put(AB + P.AB_ENABLED, b"\x01")
    mgr = AB + P.AB_MGR
    g.put(mgr + P.MGR_ENABLED, b"\x01")
    g.put(mgr + P.MGR_INDEX, struct.pack("<i", 0))
    unit = mgr + P.MGR_UNITS[0]
    g.put(unit + P.UNIT_SHOWN, b"\x01" if shown else b"\x00")
    g.q(unit + P.UNIT_BTN, MGR_BTN)
    g.put(unit + P.UNIT_MODE, struct.pack("<I", mode))
    g.q(MGR_BTN, BASE + P.BTN_VT)
    g.q(MGR_BTN + P.BTN_OWNER, owner)
    g.put(MGR_BTN + P.BTN_MUTED, b"\x01" if muted else b"\x00")
    g.put(MGR_BTN + P.BTN_PLAYER, struct.pack("<6I", player, kind, mode, 33, key, label))
    g.put(PLAYER + 0x1EB8, struct.pack("<h", hp))
    return g


# --- the reader ----------------------------------------------------------------------------------------------------
def test_the_hourglass_prompt_reads_as_press_y():
    g = guest()
    assert P.table_ok(g, BASE)
    pr = P.selected_prompt(g, BASE, PLAYER)
    assert pr["token"] == "press:y" and pr["keys"] == ("y",) and pr["label"] == 112 and pr["kind"] == 1
    assert pr["owner"] == 0x5D40000000


def test_break_free_and_resuscitate():
    pr = P.selected_prompt(guest(kind=0, mode=6, key=20, label=28, player=0), BASE, PLAYER)
    assert pr["token"] == "mash:wiggle" and pr["keys"] == ()
    pr = P.selected_prompt(guest(kind=2, mode=5, key=25, label=55, player=0, hp=1), BASE, PLAYER)
    assert pr["token"] == "mash:a" and pr["keys"] == ("a",)


@pytest.mark.parametrize("kw", [dict(shown=False), dict(muted=True), dict(player=2), dict(hp=0), dict(key=0)])
def test_nothing_shown_or_not_his_reads_none(kw):
    assert P.selected_prompt(guest(**kw), BASE, PLAYER) is None


def test_a_wrong_key_table_is_refused():
    g = guest()
    g.put(BASE + P.KEY_TABLE, b"\x00" * 128)
    assert not P.table_ok(g, BASE)


# --- the bot ---------------------------------------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _switch_fight(monkeypatch):
    monkeypatch.setattr(R, "PS3_BRAIN", False)
    monkeypatch.setattr(R, "HEAL_ENABLED", False)
    monkeypatch.setattr(R, "MINES", False)


def at(dist, deg, y=0.0):
    a = math.radians(deg)
    return (dist * math.sin(a), y, dist * math.cos(a))


def prompt(label=112, kind=1, token="press:y", keys=("y",), mode=1, button=0x5D20000000, owner=0x5D40000000,
           target=0):
    return {"token": token, "keys": keys, "button": button, "kind": kind, "mode": mode, "priority": 33,
            "key_index": 1, "label": label, "owner": owner, "target": target}


def snap(enemies=(), pr=None, motion=0, hp=1000, pos=(0.0, 0.0, 0.0), bonuses=None, mines=None):
    s = {"player": {"ptr": 0x5D00001000, "pos": pos, "rot": 0.0, "hp": hp, "hp_max": 1000, "motion": motion,
                    "aim_pitch": None},
         "enemies": [{"ptr": 10 + i, "pos": x, "hp": 800, "hp_max": 800} for i, x in enumerate(enemies)],
         "inventory": [], "kills": 0, "laser": {"from": (0, 0, 0), "at": (0, 0, 0), "up": False},
         "prompt": pr, "prompt_read": True}
    if bonuses is not None:
        s["bonuses"] = [{"ptr": 900 + i, "pos": b, "secs": 30} for i, b in enumerate(bonuses)]
    if mines is not None:
        s["ground_mines"] = [{"ptr": 700 + i, "pos": m_} for i, m_ in enumerate(mines)]
    return s


def bot():
    clock = [0.0]
    return R.Bot(stats={}, clock=lambda: clock[0]), clock


def test_the_hourglass_prompt_is_taken_at_once_ahead_of_the_fight():
    b, clock = bot()
    act = b.tick(snap([at(600, 0)], pr=prompt()))
    assert act["hold"] == ("y",) and b.doing == "prompt" and b.stats["prompts_seen_bonus"] == 1
    clock[0] = 0.05
    assert b.tick(snap([at(600, 0)], pr=prompt()))["hold"] == ()            # let go: the next press is a fresh one
    clock[0] = 0.1
    assert b.tick(snap([at(600, 0)], pr=prompt()))["hold"] == ("y",)
    clock[0] = 0.4
    b.tick(snap([at(600, 0)]))                                               # gone: taken
    assert b.stats["prompts_taken"] == 1 and b.stats["prompts_seen"] == 1 and b.stats["prompt_latency_s"] == 0


def test_break_free_shakes_the_left_stick_and_counts_the_hold():
    b, clock = bot()
    pr = prompt(label=28, kind=0, token="mash:wiggle", keys=(), mode=6, owner=10)
    seen = set()
    for k in range(4):
        clock[0] = 0.05 * k
        seen.add(b.tick(snap([at(30, 0)], pr=pr, motion=107))["hold"])
    assert seen == {("lleft",), ("lright",)} and b.stats["holds"] == 1 and b.stats["prompts_seen_enemy"] == 1


def test_resuscitate_mashes_a():
    b, clock = bot()
    pr = prompt(label=55, kind=2, token="mash:a", keys=("a",), mode=5, owner=0x5D00001000)
    holds = []
    for k in range(4):
        clock[0] = 0.05 * k
        holds.append(b.tick(snap([at(80, 0)], pr=pr, hp=1, motion=40))["hold"])
    assert holds.count(("a",)) == 2 and holds.count(()) == 2 and b.stats["dying"] == 1


def test_a_finisher_naming_a_majini_is_taken():
    b, clock = bot()
    act = b.tick(snap([at(120, 0)], pr=prompt(label=14, kind=2, target=10, owner=0x5D00001000)))
    assert act["hold"] == ("y",) and b.stats["prompts_seen_enemy"] == 1


def test_item_pickups_are_skipped_even_when_the_area_is_clear():
    b, clock = bot()
    pick = prompt(label=1, kind=2, owner=0x5D00001000)
    act = b.tick(snap([at(150, 0)], pr=pick))
    assert act["hold"] != ("y",) and b.stats["prompts_seen_pickup"] == 1
    b2, _ = bot()
    act = b2.tick(snap([at(900, 0)], pr=pick, mines=[(50.0, 0.0, 60.0)]))
    assert act["hold"] != ("y",)
    b3, _ = bot()
    assert b3.tick(snap([at(900, 0)], pr=pick))["hold"] != ("y",)
    b4, _ = bot()
    assert b4.tick(snap([], pr=pick))["hold"] != ("y",)


def test_an_item_pickup_does_not_interrupt_firing_on_a_crowd():
    b, clock = bot()
    ring = [at(300, 0), at(350, 70), at(300, -100)]
    b.tick(snap(ring))
    clock[0] = 0.3
    sample = snap(ring, pr=prompt(label=1, kind=2, owner=0x5D00001000), motion=26)
    sample["laser"] = {"from": (0.0, 140.0, 30.0), "at": (0.0, R.CHEST_H, 300.0), "up": True}
    act = b.tick(sample)
    assert {"zl", "zr"} <= set(act["hold"]) and "y" not in act["hold"]
    assert b.doing == "fire" and b.stats["prompts_seen_pickup"] == 1


def test_the_bombs_place_and_area_pickups_are_never_pressed():
    b, clock = bot()
    act = b.tick(snap([at(900, 0)], pr=prompt(label=100, kind=2, token="press:zl", keys=("zl",))))
    assert act["hold"] != ("zl",) or b.doing != "prompt"
    b2, _ = bot()
    act = b2.tick(snap([at(900, 0)], pr=prompt(label=12, kind=3)))
    assert b2.doing != "prompt"


def test_a_ledge_prompt_only_on_the_way_to_a_statue_off_his_level_and_its_spot_logged():
    b, clock = bot()
    ledge = prompt(label=9, kind=2, owner=0x5D00001000)
    act = b.tick(snap([], pr=ledge, bonuses=[at(1200, 0)]))               # a statue on his level: not now
    assert b.doing != "prompt" and b.stats["traverse_spots"].startswith("9@")
    b2, clock2 = bot()
    b2.tick(snap([], bonuses=[at(1200, 0, y=-300.0)]))                    # a statue 3 m below
    clock2[0] = 0.05
    act = b2.tick(snap([], pr=ledge, bonuses=[at(1200, 0, y=-300.0)]))
    assert act["hold"] == ("y",) and b2.doing == "prompt"
    clock2[0] = 0.3
    b2.tick(snap([], bonuses=[at(1200, 0, y=-300.0)], pos=(0.0, -300.0, 100.0)))   # down: gone, a level change
    assert b2.stats["ledge_jumps"] == 1 and b2.stats["level_changes"] == 1


def test_no_blind_y_at_a_ledge_with_the_prompt_read():
    b, clock = bot()
    statue = at(1200, 0, y=-300.0)
    for k in range(40):
        clock[0] = 0.05 * k
        act = b.tick(snap([], bonuses=[statue]))
        assert "y" not in act["hold"]
    assert b.stats["bonus_jumps"] == 0


def test_at_the_statue_he_walks_into_it_for_its_prompt_not_the_knife():
    b, clock = bot()
    act = b.tick(snap([], bonuses=[at(60, 2)]))
    assert "lup" in act["hold"] and "zr" not in act["hold"] and b.stats["knife_swings"] == 0


def test_a_stage_objects_kind_0_prompt_is_not_taken_as_a_majinis():
    b, clock = bot()
    b.tick(snap([at(900, 0)], pr=prompt(label=256, kind=0, owner=0x5D50000000)))   # the start's box (uOm088a)
    assert b.doing != "prompt" and b.doing != "held" and b.stats["prompts_seen_other"] == 1
