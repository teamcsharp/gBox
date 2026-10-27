"""RE5 Switch phase 1, the time bonuses (operator 2026-10-27 16:45 / 16:52: "capturing every time bonus" - "the only
way to grab a time bonus is to walk up to it and melee it"): the statues read from the unit lines, the run to the
next one, the facing and the knife (L + ZR) until it breaks, only a Majini in his way fought first, and the counters."""
import math
import struct

import pytest

from gbox.mercs.titles import re5_switch as R


@pytest.fixture(autouse=True)
def _switch_fight(monkeypatch):
    monkeypatch.setattr(R, "PS3_BRAIN", False)
    monkeypatch.setattr(R, "HEAL_ENABLED", False)
    R._BONUS_SCAN.update(at=-1e9, list=None, line=None, full_at=-1e9)


def at(dist, deg, y=0.0):
    a = math.radians(deg)
    return (dist * math.sin(a), y, dist * math.cos(a))


def snap(enemies=(), bonuses=(), timer=100.0):
    return {"player": {"ptr": 0x5D00001000, "pos": (0.0, 0.0, 0.0), "rot": 0.0, "hp": 1000, "hp_max": 1000,
                       "motion": 0},
            "enemies": [{"ptr": 10 + i, "pos": x, "hp": 800, "hp_max": 800} for i, x in enumerate(enemies)],
            "inventory": [], "timer": timer,
            "bonuses": [{"ptr": 0x5D4A000000 + i, "pos": x, "secs": 60} for i, x in enumerate(bonuses)],
            "laser": {"from": (0, 0, 0), "at": (0, 0, 0), "up": False}}


def bot():
    clock = [0.0]
    return R.Bot(stats={}, clock=lambda: clock[0]), clock


def test_he_runs_to_the_nearest_statue():
    b, clock = bot()
    act = b.tick(snap(bonuses=[at(1000, 5), at(2500, -40)]))
    assert b.doing == "walk" and "time bonus" in b.why and {"lup", "b"} <= set(act["hold"])
    assert b.stats["bonus_runs"] == 1 and b.stats["bonuses_seen"] == 2 and b.stats["bonuses_left"] == 2


def test_at_the_statue_he_faces_it_and_swings_the_knife():
    b, clock = bot()
    act = b.tick(snap(bonuses=[at(70, 60)]))
    assert b.doing == "turn" and set(act["hold"]) & {"rleft", "rright"}
    b2, clock2 = bot()
    acts = []
    for t in (0.0, 0.2, 0.4, 0.6, 0.8):
        clock2[0] = t
        acts.append(b2.tick(snap(bonuses=[at(70, 3)]))["hold"])
    assert ("l",) in acts and ("l", "zr") in acts and b2.doing == "melee" and b2.stats["knife_swings"] >= 1


def test_a_majini_in_his_way_is_fought_first_then_the_run_goes_on():
    b, clock = bot()
    b.tick(snap(enemies=[at(150, 0)], bonuses=[at(1000, 5)]))
    assert "time bonus" not in b.why
    clock[0] = 0.5
    b.tick(snap(enemies=[at(900, 120)], bonuses=[at(1000, 5)]))
    assert "time bonus" in b.why


def test_a_statue_gone_is_taken_and_the_round_time_of_the_last_kept():
    b, clock = bot()
    b._round_started = 0.0
    b.tick(snap(bonuses=[at(70, 3)], timer=100.0))
    clock[0] = 12.0
    b.tick(snap(bonuses=[], timer=160.0))
    assert b.stats["bonuses_taken"] == 1 and b.stats["bonuses_left"] == 0 and b.stats["bonus_time_s"] == 12.0
    assert b.stats["time_gained"] == 60.0


def test_the_statues_are_read_from_the_unit_lines():
    base = 0x3CA7C04000
    su, unit = 0x5D00100000, 0x5D4A9800A0
    mem = {}
    mem[base + R.S_UNIT] = struct.pack("<Q", su)
    mem[su + R.UNIT_LINES + R.LINE_STRIDE * 13] = struct.pack("<Q", unit)
    mem[unit] = struct.pack("<Q", base + R.BONUS_VT)
    mem[unit + R.E_POS] = struct.pack("<3f", 35.0, 303.0, 29.0)
    mem[unit + R.E_HP] = struct.pack("<h", 60)

    class M:
        def rd(self, a, n):
            return (mem.get(a) or bytes(n))[:n].ljust(n, b"\0")
    got = R.time_bonuses(M(), base, now=0.0)
    assert got == [{"ptr": unit, "pos": (35.0, 303.0, 29.0), "secs": 60}] and R._BONUS_SCAN["line"] == 13
    assert R.time_bonuses(M(), base, now=0.5) is got                  # (at most every BONUS_SCAN_S)
