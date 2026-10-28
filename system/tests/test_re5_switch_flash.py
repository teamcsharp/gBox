"""RE5 Switch flash grenades (operator 2026-10-27 21:0x: "Have them throw flashbangs all the time ... throw flashbangs,
use shotguns to force them out of the way, and use flashbangs to disarm them and work their way through with melee";
21:1x: "throw flash grenades and then drop mines and leave the area"): re5_switch_mods.flash_loadout puts the flash on a
D-pad grid of every loadout (composed with the bombs, the gun draw and the rampage gun), re5_switch_nades throws it when
he is overwhelmed, drops a bomb once clear of them and leaves, the gun back after."""
import math
import struct

import pytest

from gbox.mercs.titles import re5_switch as R
from gbox.mercs.titles import re5_switch_mines as MN
from gbox.mercs.titles import re5_switch_mods as SM
from gbox.mercs.titles import re5_switch_nades as N
from tests.test_re5_switch_mods import Adapter
from tests.test_re5_switch_parity import ids, parity_guest, rec

POOL = ["0x1B", "0x1A", "0x0B", "0x19", "0x16", "0x15", "0x1D"]
STRONG = {0x11B, 0x11A, 0x10B, 0x119, 0x116}


@pytest.fixture(autouse=True)
def _fresh_state():
    SM.ORIG.clear()
    yield
    SM.ORIG.clear()


def quick(g, i):
    return {rec(g, i, k)[5]: rec(g, i, k)[0] for k in range(12) if rec(g, i, k)[0] not in (0, 0x100)
            and rec(g, i, k)[5] in (1, 3, 5, 7)}


# --- the loadout ---------------------------------------------------------------------------------------------------------
def test_chris_gets_the_flash_at_d_pad_down_in_place_of_the_spray_with_the_bombs_and_the_drawn_guns():
    g = parity_guest()
    ad = Adapter(g)
    SM.run(ad, "mine_loadout", on=True)
    SM.tool_run(ad, "loadout", None, True, seed=3, each_round=True, weapons=POOL)
    SM.tool_run(ad, "rampage_loadout", None, True)
    out = SM.run(ad, "flash_loadout", on=True)
    assert out["verified"] and out["flash_loadout"] and out["status"]["flash_loadout"]
    for i in (14, 24):                                                     # both banks
        assert ids(g, i)[1] == SM.MINE_ID and ids(g, i)[7] == SM.FLASH_ID   # the bombs up, the flash down
        r = rec(g, i, 7)
        assert r[1] == SM.FLASH_COUNT and r[5] == 7 and r[6] == 0 and r[7] == 0   # x5 at grid 7, not in hand
        assert ids(g, i)[3] in STRONG | {0x115, 0x11D} and ids(g, i)[5] in STRONG | {0x115, 0x11D}
        assert any(w in STRONG for w in quick(g, i).values())             # a shotgun or magnum kept
    assert ids(g, 20)[7] == SM.FLASH_ID                                    # an empty D-pad grid takes it
    q = quick(g, 15)                                                       # four guns: a spare one gives way
    assert list(q.values()).count(SM.FLASH_ID) == 1 and q[3] != SM.FLASH_ID   # never the gun in hand
    assert any(w in STRONG for w in q.values())
    SM.maintain(ad, {"player": {"ptr": 0x1000}})                           # this round's player
    for n in range(2, 6):                                                  # each round's new draw keeps it
        assert SM.maintain(ad, {"player": {"ptr": 0x1000 * n}})["loadout_redrawn"] is True
        assert ids(g, 14)[7] == SM.FLASH_ID and ids(g, 14)[1] == SM.MINE_ID
    SM.tool_run(ad, "flash_loadout", None, False)                          # off: the spray back
    assert ids(g, 14)[7] == 0x304 and ids(g, 14)[1] == SM.MINE_ID
    SM.run(ad, "flash_loadout", on=True)
    assert SM.tool_run(ad, "revert_all")["verified"]
    assert ids(g, 14)[7] == 0x304 and ids(g, 14)[1] == SM.GRENADE_ID and not SM.ORIG[id(ad)].get("flash_loadout")


def test_without_the_draw_a_rocket_gives_way_and_the_shotgun_stays():
    g = parity_guest()
    SM.tool_run(Adapter(g), "flash_loadout", None, True)
    assert ids(g, 15)[1] == SM.FLASH_ID and ids(g, 15)[5] == 0x116 and ids(g, 15)[7] == 0x10D   # Safari: rocket at 1
    assert ids(g, 14)[7] == SM.FLASH_ID and ids(g, 14)[1] == SM.GRENADE_ID                     # Chris: the spray's


def block(rows):
    t = bytearray()
    for k in range(12):
        idw, count, grid, hand = rows.get(k, (0, -1, k, 0))
        t += struct.pack("<Ii3iIIII", idw, count, -1, -1, -1, grid, hand, 0x0A000005 if hand else 0, 0) + bytes(0xC)
    return t


def test_the_slot_order_on_the_template_bytes():
    own = block({1: (0x108, 3, 1, 0), 3: (0x119, -1, 3, 1), 5: (0x11B, -1, 5, 0), 7: (0x304, -1, 7, 0)})
    assert SM._flash_block(own) and struct.unpack_from("<Ii", own, 0x30)[:2] == (0x108, 5)    # its own, x5
    assert struct.unpack_from("<I", own, 0x30 * 7)[0] == 0x304 and not SM._flash_block(own)   # nothing else moves
    nade = block({1: (0x106, 3, 1, 0), 3: (0x119, -1, 3, 1), 5: (0x11B, -1, 5, 0), 7: (0x11A, -1, 7, 0)})
    assert SM._flash_block(nade) and struct.unpack_from("<I", nade, 0x30)[0] == 0x108          # a grenade before a gun
    last = block({1: (0x10A, 5, 1, 0), 3: (0x115, -1, 3, 1), 5: (0x11B, -1, 5, 0), 7: (0x101, -1, 7, 0)})
    assert not SM._flash_block(last)                  # the bomb, the gun in hand, the only magnum, the knife: none
    two = block({1: (0x10A, 5, 1, 0), 3: (0x115, -1, 3, 1), 5: (0x11B, -1, 5, 0), 7: (0x11A, -1, 7, 0)})
    assert SM._flash_block(two) and struct.unpack_from("<I", two, 0x30 * 5)[0] == 0x108        # a duplicate magnum
    assert struct.unpack_from("<III", two, 0x30 * 5 + 0x18) == (0, 0, 0)


def test_the_profile_plays_the_flash_loadout():
    import json
    from pathlib import Path
    prof = json.loads((Path(__file__).resolve().parents[1] / "profiles/gamedata/010018100CD46000-ram.json").read_text())
    assert ["flash_loadout", {"on": True}] in prof["mercs"]["playing_ops"]


# --- the throw, the bomb and out -----------------------------------------------------------------------------------------
def at(dist, deg, origin=(0.0, 0.0, 0.0)):
    a = math.radians(deg)
    return (origin[0] + dist * math.sin(a), 0.0, origin[2] + dist * math.cos(a))


def foe(i, pos, motion=4):
    return {"ptr": 10 + i, "pos": pos, "hp": 800, "hp_max": 800, "motion": motion, "act": 0}


def inv(hand="gun"):
    rows = [(0x10A, 1), (0x119, 3), (0x11D, 5), (0x108, 7)]
    held = {"gun": 0x119, "flash": 0x108, "bomb": 0x10A, "ak": 0x11D}[hand]
    return [{"slot": k, "id": idw, "type": 1, "item": idw & 0xFF, "rounds": 5, "cap": 5, "grid": grid,
             "hand": idw == held} for k, (idw, grid) in enumerate(rows)]


def snap(enemies, pos=(0.0, 0.0, 0.0), hand="gun", motion=0, hp=1000, mines=(), prompt=None, bonuses=None):
    return {"player": {"ptr": 0x5D00001000, "pos": pos, "rot": 0.0, "hp": hp, "hp_max": 1000, "motion": motion,
                       "aim_pitch": None},
            "enemies": enemies, "inventory": inv(hand), "kills": 0, "ground_mines": list(mines), "prompt": prompt,
            "bonuses": bonuses}


def step(n, s, now, mines=None, winding=None):
    n.watch(s["player"], s, now)
    return n.tick(s["player"], s, s["enemies"], now, mines=mines, winding=winding)


def crowd(origin=(0.0, 0.0, 0.0)):
    return [foe(0, at(200, 0, origin)), foe(1, at(250, 120, origin)), foe(2, at(220, -120, origin))]


def test_overwhelmed_he_throws_the_flash_drops_a_bomb_clear_of_them_and_leaves_with_the_gun_back():
    stats = {}
    n, mines = N.Nades(stats), MN.Mines(stats)
    acts = []
    acts.append(step(n, snap(crowd()), 0.0, mines))
    assert acts[-1] == {"hold": ()} and n.state == "neutral" and stats["flash_attempts"] == 1
    acts.append(step(n, snap(crowd()), 0.25, mines))
    assert acts[-1] == {"tap": "ddown"}                                    # the flash's D-pad grid
    acts.append(step(n, snap(crowd(), hand="flash"), 0.3, mines))
    assert acts[-1] == {"hold": ("zl", "rdown")}                           # all round: at his feet
    acts.append(step(n, snap(crowd(), hand="flash", motion=22), 0.7, mines))
    assert acts[-1] == {"hold": ("zl", "zr")} and n.flashed == {10, 11, 12}
    acts.append(step(n, snap(crowd(), hand="flash", motion=29), 0.75, mines))
    assert acts[-1] == {"hold": ()} and stats["pushthroughs"] == 1          # let go at once
    acts.append(step(n, snap(crowd(), hand="flash", motion=29), 0.8, mines))
    assert stats["flashes"] == 1 and "b" in acts[-1]["hold"]                # confirmed; running out
    away = (0.0, 0.0, -400.0)                                              # clear of them: the bomb
    acts.append(step(n, snap(crowd(), pos=away, hand="flash"), 1.2, mines))
    assert acts[-1] == {"tap": "dup"} and n.state == "bomb_equip"
    acts.append(step(n, snap(crowd(), pos=away, hand="bomb"), 1.3, mines))
    assert acts[-1] == {"hold": ("zl",)}
    bomb = {"ptr": 0x777, "pos": (0.0, 0.0, -340.0)}
    acts.append(step(n, snap(crowd(), pos=away, hand="bomb", motion=29, mines=[bomb]), 1.4, mines))
    assert stats["flash_mines"] == 1 and mines.bombs == {0x777: (0.0, 0.0, -340.0)} and mines.last_at == 1.4
    acts.append(step(n, snap(crowd(), pos=away, hand="bomb", motion=29, mines=[bomb]), 1.6, mines))
    assert acts[-1] == {"hold": ()}                                        # the placing motion plays out
    acts.append(step(n, snap(crowd(), pos=away, hand="bomb", mines=[bomb]), 3.1, mines))
    assert "b" in acts[-1]["hold"] and n.state == "away"
    far = (0.0, 0.0, -1300.0)
    acts.append(step(n, snap(crowd(), pos=far, hand="bomb", mines=[bomb]), 3.3, mines))
    assert acts[-1] == {"hold": ()} and n.state == "rearm"
    acts.append(step(n, snap(crowd(), pos=far, hand="bomb", mines=[bomb]), 3.6, mines))
    assert acts[-1] == {"tap": "dleft"}                                    # the shotgun (Hydra) back
    acts.append(step(n, snap(crowd(), pos=far, mines=[bomb]), 3.7, mines))
    assert acts[-1] is None and n.state == "idle"
    assert all("zr" not in (a or {}).get("hold", ()) for a in acts if a != {"hold": ("zl", "zr")})
    assert step(n, snap(crowd(far), pos=far), 4.5, mines) is None          # the gap
    assert step(n, snap(crowd(far), pos=far), 5.3, mines) == {"hold": ()} and stats["flash_attempts"] == 2


def test_never_the_trigger_without_the_flash_in_hand():
    stats = {}
    n = N.Nades(stats)
    step(n, snap(crowd()), 0.0)
    step(n, snap(crowd()), 0.25)
    step(n, snap(crowd(), hand="flash"), 0.3)
    act = step(n, snap(crowd(), hand="gun"), 0.7)                          # the flash left his hand
    assert act == {"hold": ()} and stats["flash_aborts"] == 1 and n.state == "rearm" and stats["flashes"] == 0


def test_what_counts_as_overwhelmed():
    n = N.Nades({})
    two = [foe(0, at(200, 0)), foe(1, at(250, 90))]
    assert step(n, snap(two), 0.0) is None                                 # two near: not yet
    winding = lambda e: e.get("motion") == 80
    assert step(N.Nades({}), snap([foe(0, at(200, 0), motion=80)]), 0.0, winding=winding) == {"hold": ()}
    n2 = N.Nades({})
    n2.watch(snap(two)["player"], snap(two), 0.0)
    assert step(n2, snap(two, hp=900), 0.2) == {"hold": ()}                # hit with two close
    far = [foe(i, at(600, 40 * i)) for i in range(5)]
    assert step(N.Nades({}), snap(far), 0.0) is None
    nf = N.Nades({})
    s = snap(crowd())
    s["inventory"] = [x for x in s["inventory"] if x["id"] != 0x108]
    assert step(nf, s, 0.0) is None                                        # no flash on a D-pad grid


def test_the_melee_prompts_on_the_flashed_ones_count_and_the_run_heads_for_the_statue():
    stats = {}
    n = N.Nades(stats)
    for t, hand in ((0.0, "gun"), (0.25, "gun"), (0.3, "flash"), (0.7, "flash"), (0.75, "flash")):
        step(n, snap(crowd(), hand=hand), t)
    pr = {"button": 0xB1, "label": 41, "owner": 11, "target": 0, "token": "press:a", "keys": ("a",)}
    s = snap(crowd(), hand="flash", prompt=pr)
    n.watch(s["player"], s, 1.0)
    n.watch(s["player"], s, 1.05)                                          # the same prompt: once
    grab = dict(pr, button=0xB2, label=N.LABEL_BREAK_FREE)
    s2 = snap(crowd(), hand="flash", prompt=grab)
    n.watch(s2["player"], s2, 1.1)
    assert stats["flash_melees"] == 1
    statue = [{"ptr": 1, "pos": (-900.0, 0.0, 300.0), "secs": 60}]          # to his left (a smaller heading)
    act = step(n, snap(crowd(), hand="flash", motion=29, bonuses=statue), 1.2)
    assert act["hold"] == ("b", "lup", "rright")                           # the flashed ones are no wall: the statue
    s3 = snap(crowd(), hand="flash")
    n.watch(s3["player"], s3, 1.8)                                         # a second after the throw
    assert stats["flash_motions"] == "4:3"


def test_the_bot_throws_before_it_fights_when_swarmed(monkeypatch):
    for name, value in (("PS3_BRAIN", False), ("HEAL_ENABLED", False), ("MINES", False), ("CALM", False)):
        monkeypatch.setattr(R, name, value)
    b = R.Bot(stats={}, clock=lambda: 0.0)
    s = snap(crowd())
    s["laser"] = {"from": (0, 0, 0), "at": (0, 0, 0), "up": False}
    act = b.tick(s)
    assert b.doing == "flash" and act == {"hold": ()} and b.stats["flash_attempts"] == 1
    assert "flashes" in R.RE5Switch.round_counters and "overwhelmed_s" in R.RE5Switch.round_counters
