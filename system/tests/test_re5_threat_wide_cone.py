"""Unit tests for the ranged-threat gate in re5_ps3 Bot._threat (request #5127, cluster fca1f514287750be).

The cluster: a ranged shooter (laser rifle) hits the bot at 5-20 m while it is walking, pursuing or clearing a
closer target; within_2m=0 (nobody close), laser=0, combo=0. The previous close-cone attempt widened the cone for
close (2.5 m) rear/side enemies - the reviewer rejected it as the wrong target (the cluster is ranged, 5-20 m).

The corrected single change: an enemy on the bot's level, within RANGED_THREAT_R (4000 cm) and facing it
(inside FIGHT_CONE = 40 deg), is a threat. That makes the bot stop walking (pursue / clear_nearby) and turn to face
and fire the shooter instead of marching past it while getting hit - the most incidents in this cluster.
Farther than RANGED_THREAT_R, behind it, or off-level it is not a threat (the tour goes on; pursuit handles melee).

Geometry: player at origin facing +x (rot = pi/2; heading(dx,dz) = atan2(dx,dz)). An enemy `off_deg` off the
heading is at bearing 90+off from +x, i.e. pos (d*cos(90+off), d*sin(90+off)).

- 200 cm in front (off=0)            -> threat (was threat: d < FIGHT_R=350, off < FIGHT_CONE)
- 200 cm at 50 deg off               -> threat (was NOT: off=50>40; the reverted close-cone hack is gone)
- 3000 cm in front (off=0)           -> threat (ranged: d <= 4000, off=0 < 40)
- 3000 cm at 50 deg off (off=50>40)  -> not a threat (outside FIGHT_CONE)
- 4100 cm in front (off=0)           -> not a threat (beyond RANGED_THREAT_R)
- 2000 cm behind (off=180)           -> not a threat (off=180 > 40, the gate is front-facing)
- 3000 cm in front, 300 cm up        -> not a threat (off-level, |dy| >= LEVEL_DY)
- 100 cm anywhere (d < ON_TOP_R)     -> threat (on top, any side, unchanged)
- 200 cm at 80 deg off               -> threat (grab-front, unchanged)
"""
import math

import pytest

from gbox.mercs.titles.re5_ps3 import (
    Bot,
    RANGED_THREAT_R,
    FIGHT_R,
    FIGHT_CONE,
    ON_TOP_R,
    LEVEL_DY,
    GRAB_FRONT_R,
    GRAB_FRONT_CONE,
    heading,
    wrap,
)


def _bot():
    b = object.__new__(Bot)
    b.stats = {}
    return b


def _p(px=0.0, pz=0.0, py=100.0, rot=None):
    """rot defaults to pi/2 = facing +x (the heading convention: heading(dx,dz) = atan2(dx,dz))."""
    if rot is None:
        rot = math.pi / 2
    return {"pos": (px, py, pz), "rot": rot}


def _enemy_off_axis(off_deg, dist_cm, key="E", level_dy=0.0):
    """Enemy `off_deg` off the player's heading. The player faces +x (rot = pi/2, heading(dx,dz) = atan2(dx,dz)),
    so 'in front' is +x and 90 deg off is +z. Enemy position:
      x = d*cos(off)  (off=0 -> +x, in front)
      z = d*sin(off)  (off=90 -> +z, to the right)
    The off-axis angle the bot computes is |wrap(heading(dx,dz) - rot)| = |off|."""
    off = math.radians(off_deg)
    x = dist_cm * math.cos(off)
    z = dist_cm * math.sin(off)
    return {"ptr": key, "slot": key, "pos": (x, 100.0 + level_dy, z), "hp": 100}


# --- Constants: the new gate ---

def test_ranged_constants_match_cluster():
    """RANGED_THREAT_R = 4000 cm (40 m) brackets the cluster's in-range shooter band; it is well past the close range."""
    assert RANGED_THREAT_R == 4000.0
    assert RANGED_THREAT_R > FIGHT_R          # the ranged band starts past the close block range
    assert RANGED_THREAT_R > ON_TOP_R


# --- Ranged gate: an in-front in-range shooter is now a threat ---

def test_ranged_in_front_is_threat():
    """A shooter 3000 cm in front, on level: d=3000 <= RANGED_THREAT_R(4000), off=0 < FIGHT_CONE(40) -> threat.
    Old code: d=3000 > FIGHT_R=350, not on top, not grab-front -> False (the bot walked past it)."""
    b = _bot()
    p = _p()
    e = _enemy_off_axis(0.0, 3000.0)
    assert b._threat(p, e) is True, \
        "a ranged shooter 3000 cm in front is a threat: the bot stops walking and fires it"


def test_ranged_boundary_inclusive():
    """A shooter exactly at RANGED_THREAT_R in front: d == 4000, off=0 -> threat (<= is inclusive)."""
    b = _bot()
    p = _p()
    e = _enemy_off_axis(0.0, RANGED_THREAT_R)
    assert b._threat(p, e) is True, "exactly at RANGED_THREAT_R in front is a threat (<= inclusive)"


def test_ranged_just_beyond_not_threat():
    """4100 cm in front (d > RANGED_THREAT_R=4000), off=0: not a threat. The gate is bounded, not infinite."""
    b = _bot()
    p = _p()
    e = _enemy_off_axis(0.0, RANGED_THREAT_R + 100.0)
    assert b._threat(p, e) is False, "4100 cm in front is beyond RANGED_THREAT_R: not a threat"


def test_ranged_off_cone_not_threat():
    """A shooter 3000 cm at 50 deg off the heading: off=50 > FIGHT_CONE(40) -> not a threat, even in range.
    The gate requires the enemy facing the bot; an angled side shooter is handled by pursuit, not stop-and-fire."""
    b = _bot()
    p = _p()
    e = _enemy_off_axis(50.0, 3000.0)
    assert b._threat(p, e) is False, \
        "3000 cm at 50 deg off is outside FIGHT_CONE: the ranged gate requires it facing him"


def test_ranged_cone_edge_strict():
    """A shooter 3000 cm at exactly FIGHT_CONE (40 deg) off: off=40 is not < 40 -> not a threat (strict <)."""
    b = _bot()
    p = _p()
    e = _enemy_off_axis(math.degrees(FIGHT_CONE), 3000.0)
    assert b._threat(p, e) is False, "exactly at FIGHT_CONE off is not a threat (strict <)"


def test_ranged_behind_not_threat():
    """A shooter 2000 cm directly behind (off=180): off=180 > 40 -> not a threat. The gate is front-facing only;
    a rear shot at that range is a turn/escape problem, not a stop-and-fire one (no rear homing)."""
    b = _bot()
    p = _p()
    e = _enemy_off_axis(180.0, 2000.0)
    assert b._threat(p, e) is False, "2000 cm behind (off=180 deg) is not in FIGHT_CONE: not a threat"


# --- Off-level: the gate ignores enemies on another floor ---

def test_ranged_off_level_not_threat():
    """A shooter 3000 cm in front but 300 cm up (a roof): |dy|=300 >= LEVEL_DY(150) -> not a threat, even in range."""
    b = _bot()
    p = _p()
    e = _enemy_off_axis(0.0, 3000.0, level_dy=300.0)
    assert b._threat(p, e) is False, "3000 cm in front but 300 cm up (off-level) is not a threat"


def test_ranged_level_boundary():
    """A shooter 3000 cm in front at exactly LEVEL_DY (150 cm up): |dy|=150 >= LEVEL_DY -> not a threat (>=)."""
    b = _bot()
    p = _p()
    e = _enemy_off_axis(0.0, 3000.0, level_dy=LEVEL_DY)
    assert b._threat(p, e) is False, "at exactly LEVEL_DY up it is another level, not a threat"


# --- Close behaviour unchanged (regression: the reverted hack is gone) ---

def test_close_in_front_still_threat():
    """A Majini 200 cm in front (d < FIGHT_R=350, off=0): threat, as before (the close block range is unchanged)."""
    b = _bot()
    p = _p()
    e = _enemy_off_axis(0.0, 200.0)
    assert b._threat(p, e) is True, "200 cm in front is a threat (close block range, unchanged)"


def test_close_off_cone_still_not_threat():
    """A Majini 300 cm at 50 deg off (d < FIGHT_R but off=50 > FIGHT_CONE=40): NOT a threat.
    The reverted close-cone hack (CLOSE_THREAT_R/REAR_WIDE_CONE) would have flagged this; the narrow cone says no."""
    b = _bot()
    p = _p()
    e = _enemy_off_axis(50.0, 300.0)
    assert b._threat(p, e) is False, \
        "300 cm at 50 deg off: the reverted close-cone hack is gone; the narrow cone does not flag it"


def test_on_top_still_threat():
    """A Majini 100 cm at any side (d < ON_TOP_R=160): threat from any side, unchanged."""
    b = _bot()
    p = _p()
    for off in (0.0, 45.0, 90.0, 180.0):
        e = _enemy_off_axis(off, 100.0)
        assert b._threat(p, e) is True, f"100 cm at {off} deg off: on top, threat from any side"


def test_grab_front_still_threat():
    """A Majini 200 cm at 80 deg off (d < GRAB_FRONT_R=250, off=80 <= GRAB_FRONT_CONE=90): threat (grab-front), unchanged."""
    b = _bot()
    p = _p()
    e = _enemy_off_axis(80.0, 200.0)
    assert b._threat(p, e) is True, "200 cm at 80 deg off is grab-front: threat, unchanged"


# --- The cluster's far examples (out of the gate's band) ---

def test_far_shooter_out_of_band_not_threat():
    """A shooter 20 m (20000 cm) in front is beyond RANGED_THREAT_R(4000): not flagged by the gate. The gate is a
    bounded in-range band (0-4000 cm); an out-of-range shooter is handled by the approach/pursuit logic, not
    stop-and-fire. This documents the band, not an infinite rear-homing."""
    b = _bot()
    p = _p()
    e = _enemy_off_axis(0.0, 20000.0)
    assert b._threat(p, e) is False, "20000 cm in front is beyond RANGED_THREAT_R: the gate does not flag it"


# --- Replay: the incident_replay bot drives through a snapshot without crashing ---

def test_replay_cluster_fixture_runs_cleanly():
    """A fresh re5_ps3 Bot (via incident_replay.bot, title BLUS30491) runs through a recorded-style snapshot and
    produces ticks without an exception, exercising the decision logic - including the new ranged gate - on data.
    A synthetic snapshot matching the cluster's fields: player facing +x, a ranged enemy in front at 3000 cm."""
    from gbox.mercs import incident_replay

    fx = {
        "schema": incident_replay.SCHEMA,
        "title": "BLUS30491",
        "event_id": "ranged-5127",
        "observed_at": 1793223866930,
        "hp_before": 800,
        "hp_after": 500,
        "hp_max": 800,
        "loss": 300,
        "held": [],
        "snapshot": {
            "player": {"pos": (0.0, 100.0, 0.0), "rot": math.pi / 2, "hp": 800, "action": 1},
            "enemies": [{"slot": 0, "ptr": 1, "pos": (0.0, 100.0, 3000.0), "hp": 800}],
            "bonuses": [],
        },
        "counters": {},
        "decision": {"act": 1, "phase": "pursue"},
        "preceding_history": [],
    }
    result = incident_replay.replay(fx, ticks=5)
    assert "ticks" in result and len(result["ticks"]) == 5, \
        f"replay should produce 5 ticks, got {len(result.get('ticks', []))}"
    assert "bot" in result and "stats" in result, "replay result should include bot and stats"


if __name__ == "__main__":
    import sys
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("ok  " + name)
            except Exception as e:
                fails += 1
                print("FAIL " + name + ": " + repr(e))
    sys.exit(1 if fails else 0)
