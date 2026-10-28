"""RE5 Switch aim measured (the coordinator 19:06): each pull's aim error (mean / p90), the seconds from acquiring a
target to the first pull on him, and the hit rate by distance band, in the round's stats (aim_report)."""
import math

import pytest

from gbox.mercs.titles import re5_switch as R

MUZZLE = (0.0, 140.0, 30.0)


@pytest.fixture(autouse=True)
def _switch_fight(monkeypatch):
    monkeypatch.setattr(R, "PS3_BRAIN", False)
    monkeypatch.setattr(R, "HEAL_ENABLED", False)
    monkeypatch.setattr(R, "MINES", False)
    monkeypatch.setattr(R, "CALM", False)


def at(dist, deg, y=0.0):
    a = math.radians(deg)
    return (dist * math.sin(a), y, dist * math.cos(a))


def chest(foot):
    return (foot[0], foot[1] + R.CHEST_H, foot[2])


def snap(enemies, dot=None, motion=26, hp=800):
    return {"player": {"ptr": 0x5D00001000, "pos": (0.0, 0.0, 0.0), "rot": 0.0, "hp": 1000, "hp_max": 1000,
                       "motion": motion, "aim_pitch": None},
            "enemies": [{"ptr": 10 + i, "pos": x, "hp": hp, "hp_max": 800} for i, x in enumerate(enemies)],
            "inventory": [], "kills": 0,
            "laser": {"from": MUZZLE, "at": dot, "up": True} if dot else {"from": (0, 0, 0), "at": (0, 0, 0), "up": False}}


def test_a_pull_is_measured_its_hit_banded_and_the_round_reported():
    clock = [0.0]
    b = R.Bot(stats={}, clock=lambda: clock[0])
    foe = at(600, 0)
    b.tick(snap([foe], motion=22))                                 # acquired, the gun coming up
    clock[0] = 0.4
    b.tick(snap([foe], dot=chest(foe)))                            # on him: the pull
    assert b.stats["aim_err_n"] == 1 and b.stats["aim_err_mean_deg"] < 2 and b.stats["acquire_n"] == 1
    assert 0.3 <= b.stats["acquire_to_shot_s"] <= 0.5
    clock[0] = 0.5
    b.tick(snap([foe], dot=chest(foe), hp=600))                    # his health falls: a hit
    clock[0] = 0.6
    b.tick(snap([foe], dot=(3000.0, 140.0, 3000.0), hp=600))      # the aim off him: the pull ends
    clock[0] = 1.2
    b.tick(snap([foe], dot=(3000.0, 140.0, 3000.0), hp=600))
    assert b.stats["pulls_3to8m"] == 1 and b.stats["hits_3to8m"] == 1
    assert "3-8 m 100 % (1)" in b.stats["aim_report"] and "first shot" in b.stats["aim_report"]
