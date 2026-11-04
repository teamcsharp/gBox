"""Pursuit front-approach guard (damage cluster #5128): while pursuing an out-of-sight Majini, a close, in-front
Majini blocks the way - the bot stops (empty hold) instead of closing to him through the fight, so the combat layer
fights it from where the bot stands (no more pursuit-walk straight onto the front approacher)."""
import math

import pytest

from gbox.mercs.titles import re5_ps3 as R


class FakeMem:
    def __init__(self, b=None):
        self.b = b or bytearray(0x8000)

    def rd(self, a, n):
        return bytes(self.b[a:a + n]) if a + n <= len(self.b) else b"\x00" * n

    def write(self, a, data):
        for i, v in enumerate(data):
            if a + i < len(self.b):
                self.b[a + i] = v

    def put(self, a, fmt, *v):
        import struct
        self.write(a, struct.pack(fmt, *v))


def at(dist, deg, y=0.0):
    a = math.radians(deg)
    return (dist * math.sin(a), y, dist * math.cos(a))


def mkbot(tmp_path):
    bot = R.Bot(FakeMem(), clock=lambda: 0.0, learn_dir=tmp_path, lessons=lambda e: None)
    bot.stats = bot.stats or {}
    return bot


def test_pursue_stops_when_a_front_approacher_is_in_the_fight_cone(tmp_path):
    """A Majini 150 cm ahead, right in front: the guard stops the pursuit."""
    b = mkbot(tmp_path)
    # Enemy at 150 cm directly in front (within FIGHT_R=350, within FIGHT_CONE=40 deg, same level)
    e = {"slot": 7, "ptr": 1007, "pos": at(150.0, 0.0), "hp": 800, "hp_max": 800}
    p = {"pos": (0.0, 0.0, 0.0), "rot": 0.0}
    act = b._pursue(p, e, None, None, 0.0)
    assert act == {"hold": set()} and b.stats.get("phase") == "pursue_guarded"


def test_pursue_stops_when_the_approacher_is_on_tops_of_him(tmp_path):
    """A Majini right on top of the player (within ON_TOP_R=160 from any side): the guard stops."""
    b = mkbot(tmp_path)
    # Enemy at 150 cm but player is facing away (200 deg): still on top, guard stops
    e = {"slot": 7, "ptr": 1007, "pos": at(150.0, 0.0), "hp": 800, "hp_max": 800}
    p = {"pos": (0.0, 0.0, 0.0), "rot": math.radians(200.0)}
    act = b._pursue(p, e, None, None, 0.0)
    assert act == {"hold": set()}


def test_pursue_keeps_walking_to_a_far_enemy_with_no_front_approacher(tmp_path):
    """A far enemy (1500 cm) with no close foe: the bot keeps walking (no guard)."""
    b = mkbot(tmp_path)
    e = {"slot": 7, "ptr": 1007, "pos": at(1500.0, 0.0), "hp": 800, "hp_max": 800}
    p = {"pos": (0.0, 0.0, 0.0), "rot": 0.0}
    act = b._pursue(p, e, None, None, 0.0)
    assert act["hold"]  # the walk input (no guard)
    assert b.stats.get("phase") == "pursue"


def test_pursue_keeps_walking_to_a_far_enemy_with_only_a_distant_foe(tmp_path, monkeypatch):
    """A far enemy (1500 cm) with only a distant foe (beyond FIGHT_R): no guard, keep walking."""
    b = mkbot(tmp_path)
    e = {"slot": 7, "ptr": 1007, "pos": at(1500.0, 0.0), "hp": 800, "hp_max": 800}
    near = {"slot": 8, "ptr": 1008, "pos": at(400.0, 0.0), "hp": 800, "hp_max": 800}  # beyond FIGHT_R=350
    p = {"pos": (0.0, 0.0, 0.0), "rot": 0.0}
    act = b._pursue(p, e, None, None, 0.0)
    assert act["hold"] and b.stats.get("phase") == "pursue"
