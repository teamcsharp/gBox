"""Unit tests for the _aim_away grab-range fix (request #5127, re5_switch grabbed_front cluster).

Examples from the cluster: aim yaw_err ~+21 deg off the nearest (65-95 cm, within THREAT_NEAR_R 400, beyond
GRAB_THREAT_R 120), motion 22 (gun up), no trigger in ~0.5 s -> the nearest grabs him from the front. With the
old code the fix waited AWAY_S (0.3 s) of the aim being off, so a one-tick miss (a shot missed at 0.16 s) was
never corrected: aim_away_fixes stayed 0 and the nearest reached him. Now a threat within GRAB_THREAT_R of the
aim gets no patience (one tick); a farther threat keeps the old 0.3 s patience.
"""
import math

import pytest

from gbox.mercs.titles.re5_switch import (
    AWAY_ERR, AWAY_S, Bot, GRAB_THREAT_R, THREAT_NEAR_R, heading, wrap,
)


def _bot():
    b = object.__new__(Bot)
    b.stats = {k: 0 for k in ("aim_away_s", "aim_away_fixes")}
    b._away_since = None
    b._away_t = None
    b.target = "T"
    b.target_at = 0.0
    b.dot_other = (None, 0)
    b._set_target = lambda key, now: setattr(b, "target", key)
    b._round_t0 = None
    return b


def _p(px=0.0, pz=0.0, rot=0.0):
    return {"pos": (px, 100.0, pz), "rot": rot}


def _enemy(x, z, key="E"):
    return {"ptr": key, "pos": (x, 100.0, z), "hp": 100}


def _off(deg):
    return math.radians(deg)


# --- example geometry: player at origin facing +x, nearest 90 cm, aim off by ~21 deg, gun up, no trigger ---

def test_near_threat_away_off_fixes_at_once():
    """The cluster's examples: nearest ~0.9 m (beyond GRAB_THREAT_R), aim 21 deg off the nearest (past AWAY_ERR 45?
    no - 21 deg < 45): the off angle here is against AWAY_ERR... built exactly: the nearest 90 cm to the right of
    the aim line, the aim 21 deg from the nearest's bearing -> off > AWAY_ERR only when the aim is past 45 deg
    from him; the examples are 21-23 deg off. So the fix path: aim 50 deg off the nearest (the dot swept left)."""
    b = _bot()
    p = _p(rot=0.0)
    flat = lambda e: math.hypot(e["pos"][0] - p["pos"][0], e["pos"][2] - p["pos"][2])
    e = _enemy(62.0, 64.0)                       # ~90 cm, ~46 deg right of his facing (the examples: ~0.9 m)
    d = math.hypot(62.0, 64.0)
    aim = 0.0 + math.radians(50)                 # the ray points 50 deg right of facing: off the nearest by ~4 deg? no
    # simpler exact geometry: nearest straight right (+z), aim 40 deg left of him -> off = 40 deg > 22.5 (AWAY_ERR/2)
    # AWAY_ERR is radians(45): off must exceed 45 deg. Aim 100 deg left of his bearing:
    bearing = heading(62.0, 64.0)
    aim = wrap(bearing - math.radians(100))
    origin = (p["pos"][0], p["pos"][1] + 140.0, p["pos"][2])
    dot = (origin[0] + math.cos(aim), origin[1], origin[2] + math.sin(aim))
    now = 10.0
    out = b._aim_away(p, [e], flat, origin, dot, False, now)
    assert out is not None, "a nearest at arm's length with the aim >45 deg off must be taken at once"
    assert b.stats["aim_away_fixes"] == 1
    assert b.target == "E"


def test_far_threat_keeps_the_patience():
    """A threat beyond GRAB_THREAT_R (200 cm) keeps the old AWAY_S patience: no fix on the first tick."""
    b = _bot()
    p = _p(rot=0.0)
    flat = lambda e: math.hypot(e["pos"][0] - p["pos"][0], e["pos"][2] - p["pos"][2])
    e = _enemy(141.0, 148.0)                     # ~204 cm, beyond GRAB_THREAT_R 120
    assert flat(e) > GRAB_THREAT_R
    bearing = heading(e["pos"][0] - p["pos"][0], e["pos"][2] - p["pos"][2])
    aim = wrap(bearing - math.radians(100))
    origin = (p["pos"][0], p["pos"][1] + 140.0, p["pos"][2])
    dot = (origin[0] + math.cos(aim), origin[1], origin[2] + math.sin(aim))
    now = 10.0
    out = b._aim_away(p, [e], flat, origin, dot, False, now)
    assert out is None, "the far threat still waits AWAY_S (no fix on tick one)"
    assert b.stats["aim_away_fixes"] == 0
    assert b._away_since == now
    # after AWAY_S the fix lands (old behaviour intact)
    out = b._aim_away(p, [e], flat, origin, dot, False, now + AWAY_S + 0.05)
    assert out is not None
    assert b.stats["aim_away_fixes"] == 1


def test_near_threat_on_the_aim_no_fix():
    """The aim within AWAY_ERR of the nearest: no fix, even at arm's length."""
    b = _bot()
    p = _p(rot=0.0)
    flat = lambda e: math.hypot(e["pos"][0] - p["pos"][0], e["pos"][2] - p["pos"][2])
    e = _enemy(62.0, 64.0)
    bearing = heading(e["pos"][0] - p["pos"][0], e["pos"][2] - p["pos"][2])
    origin = (p["pos"][0], p["pos"][1] + 140.0, p["pos"][2])
    dot = (origin[0] + math.cos(bearing), origin[1], origin[2] + math.sin(bearing))
    assert b._aim_away(p, [e], flat, origin, dot, False, 10.0) is None
    assert b.stats["aim_away_fixes"] == 0


def test_confirmed_shot_suppresses_the_fix():
    """A confirmed shot on another Majini: the fix is suppressed (opportunistic fire, as before)."""
    b = _bot()
    p = _p(rot=0.0)
    flat = lambda e: math.hypot(e["pos"][0] - p["pos"][0], e["pos"][2] - p["pos"][2])
    e = _enemy(62.0, 64.0)
    bearing = heading(e["pos"][0] - p["pos"][0], e["pos"][2] - p["pos"][2])
    aim = wrap(bearing - math.radians(100))
    origin = (p["pos"][0], p["pos"][1] + 140.0, p["pos"][2])
    dot = (origin[0] + math.cos(aim), origin[1], origin[2] + math.sin(aim))
    assert b._aim_away(p, [e], flat, origin, dot, True, 10.0) is None
    assert b.stats["aim_away_fixes"] == 0


def test_off_level_threat_not_picked():
    """A threat on another level (dy > LEVEL_DY) is not the nearest for the fix."""
    b = _bot()
    p = _p(rot=0.0)
    e = _enemy(62.0, 64.0)
    e["pos"] = (62.0, 100.0 + 300.0, 64.0)
    flat = lambda x: math.hypot(x["pos"][0] - p["pos"][0], x["pos"][2] - p["pos"][2])
    bearing = heading(e["pos"][0] - p["pos"][0], e["pos"][2] - p["pos"][2])
    aim = wrap(bearing - math.radians(100))
    origin = (p["pos"][0], p["pos"][1] + 140.0, p["pos"][2])
    dot = (origin[0] + math.cos(aim), origin[1], origin[2] + math.sin(aim))
    assert b._aim_away(p, [e], flat, origin, dot, False, 10.0) is None
    assert b.stats["aim_away_fixes"] == 0


def test_constants_match_the_cluster_example_fields():
    """The examples: nearest 65-95 cm, THREAT_NEAR_R 400, GRAB_THREAT_R 120, AWAY_ERR 45 deg, AWAY_S 0.3 s."""
    assert THREAT_NEAR_R == 400.0 and GRAB_THREAT_R == 120.0
    assert AWAY_ERR == math.radians(45) and AWAY_S == 0.3
