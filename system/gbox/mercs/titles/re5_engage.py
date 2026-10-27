"""RE5 Mercenaries engagement rules: one straight sequence per Majini, as pure functions (no RAM, no pad).

Operator 2026-10-26, watching MercMode: "he should basically raise his gun, aim it at the target, and shoot the target, but
instead he's waving the gun around randomly and then sometimes shooting the target"; "she lowered her gun, shot at his
feet, circled around him and then shot him. This is an absurd way to behave"; "They are shooting at walls and just
sitting here amongst foes."

The data behind them (gbox-data/mercs/round_maps/BLUS30491, the player-damage moments, 2026-10-26 16:00-19:30): at 162
hits he took while turning with the gun down, a Majini stood within 4 m and 35 deg in front of him in 94 (the target was
another one, off to the side or behind); the shots fired while the gun was still coming up hit 13 of 141; half of the
time with a Majini within 3.5 m went on neither shooting nor moving. So:

  * pick(): the Majini under the laser dot first (the gun is on him: shoot him, whoever was the target); then the
    nearest threat inside the gun's own sector (FRONT_CONE) within FRONT_CLEAR_R; then one at arm's length anywhere
    (CONTACT_R: turn to him); then the nearest in front within FRONT_R; then the cheapest by distance and bearing. The
    held target stays while he is still the right kind of choice (KEEP_RATIO / SWITCH_COST): no swinging between two;
  * front_threat(): the gun comes down to turn only when nothing threatening stands within FRONT_CLEAR_R in front;
  * window(): how far off his chest a shot still lands (his half width plus WINDOW_PAD_CM, seen from the gun): the
    trigger is down inside it, up outside it, and the stick slews with a deadband inside it (no waving);
  * plausible(): a laser read is the shot's ray only when it starts at his gun and points roughly where he faces
    (a torn read - an origin metres away, a ray pointing behind him or straight into the ground - never steers or fires);
  * dot_class(): what the dot is on, for "look at the bot": a Majini ("target"), a wall or the floor short of him,
    nothing near him ("none"), no ray ("off").

Distances are cm (RE5 world units); angles radians; a bearing is RE5's heading sense (+ = to his left: the right stick's
rleft turns toward it) unless a name says _right.
"""
from __future__ import annotations

import math

FRONT_CONE = math.radians(35)       # the gun's sector: a Majini this close to his heading is brought on by aiming
FRONT_CLEAR_R = 350.0               # a threat this near inside FRONT_CONE: the gun never comes down to turn away
FRONT_R = 500.0                     # a Majini this near in front is fought before one outside the cone (no swing)
CONTACT_R = 150.0                   # a Majini this near anywhere: turned to (the quick turn when he is behind)
LEVEL_DY = 150.0                    # this far above / below: another level (a roof, a pit)
KEEP_RATIO = 1.5                    # in front: the held target stays while within this times the nearest one's distance
SWITCH_COST = 0.75                  # elsewhere: a new target must cost under this share of the held one's cost
BEARING_WEIGHT = 2.0                # cost = distance * (1 + BEARING_WEIGHT * |bearing| / pi): one behind costs 3x
BODY_R = 36.0                       # re5_combat.BODY_R: a Majini's half width
WINDOW_PAD_CM = 15.0                # the fire window: his half width plus this, seen from the gun
WINDOW_MIN = math.radians(3.0)      # never narrower than this (far Majini: the laser line gate decides there)
PITCH_PAD_CM = 55.0                 # vertically: chest height to shoulder / knee is about 35-65 cm, plus the pad
DEADBAND_SHARE = 0.35               # inside the window the stick waits until the error is over this share of it
SWING_TURN = math.radians(45)       # re5_combat.SWING_TURN: further off than this, the gun comes down to turn
SWING_DONE = math.radians(15)       # a gun-down swing goes on until he is this close to the heading, then the gun rises
CLOSE_R = 500.0                     # within this the fire window rules (the laser line gate beyond)
RAY_ORIGIN_R = 160.0                # a laser origin further than this from his feet (on the ground) is not his gun
RAY_ORIGIN_DY = (0.0, 250.0)        # ... or outside these heights above his feet
RAY_YAW_MAX = math.radians(60)      # a ray pointing further than this off his heading is not where his gun points
                                    # (the upper body aims a little off the heading, 2-14 deg in the shot records) ...
RAY_YAW_ON_MAJINI = math.radians(100)   # ... unless its dot sits on a Majini (a measured body hit), up to this; never
                                        # behind him
RAY_PITCH_MAX = math.radians(70)    # ... nor one steeper than this (straight into the ground at his feet: the aim
                                    # stops near -20 deg, re5_ps3.BONUS_STEEP; the muzzle-to-dot line is steeper)
SHORT_RAY_CM = 50.0                 # re5_combat.STEER_RAY_CM: a ray shorter than this gives no direction to check
FLOOR_DOT_DY = 30.0                 # a dot this close to the floor (his feet or the Majini's): the floor
SHORT_CM = 60.0                     # a dot this much short of the Majini: something in between (re5_combat.FIRE_SLACK)


def wrap(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


def heading(dx: float, dz: float) -> float:
    return math.atan2(dx, dz)


def flat(a, b) -> float:
    return math.hypot(b[0] - a[0], b[2] - a[2])


def bearing(p: dict, pos) -> float:
    """The bearing of pos from his heading (+ = to his left)."""
    return wrap(heading(pos[0] - p["pos"][0], pos[2] - p["pos"][2]) - (p.get("rot") or 0.0))


def key(e: dict):
    return e.get("ptr", e.get("slot"))


def living(e: dict) -> bool:
    return (e.get("hp") or 0) > 0 and (e.get("hp_max") or 2) > 1


def on_level(p: dict, e: dict, dy: float = LEVEL_DY) -> bool:
    return abs(e["pos"][1] - p["pos"][1]) < dy


def front_threat(p: dict, enemies, *, exclude=None, r: float = FRONT_CLEAR_R, cone: float = FRONT_CONE):
    """The nearest living Majini on his level within r and inside cone of his heading (not exclude), else None: while one
    stands there the gun stays up on him (operator: lower the gun to turn only when nothing threatening is in front)."""
    best, best_d = None, math.inf
    for e in enemies or ():
        if not living(e) or key(e) == exclude or not on_level(p, e):
            continue
        d = flat(p["pos"], e["pos"])
        if d <= r and abs(bearing(p, e["pos"])) <= cone and d < best_d:
            best, best_d = e, d
    return best


def cost(p: dict, e: dict) -> float:
    return flat(p["pos"], e["pos"]) * (1.0 + BEARING_WEIGHT * abs(bearing(p, e["pos"])) / math.pi)


def pick(p: dict, enemies, *, held=None, dotted=None, extra_ok=None):
    """(the Majini to fight, why) from enemies (living, open: the caller drops measured cover), or (None, why).

    dotted: the one under the laser dot (a measured line: shot first, unless a Majini at arm's length stands in front);
    held: the current target's key (kept while he is still the right kind of choice); extra_ok(e): whether one off his
    level may still be chosen outside the dot (a front camera sector, the caller's)."""
    pool = [e for e in enemies or () if living(e)]
    if not pool:
        return None, "no living Majini"
    level = [e for e in pool if on_level(p, e)]
    held_e = next((e for e in pool if held is not None and key(e) == held), None)

    def near(cands):
        return min(cands, key=lambda e: flat(p["pos"], e["pos"]))

    def keep(cands, best):
        if held_e is not None and held_e is not best and held_e in cands \
                and flat(p["pos"], held_e["pos"]) <= KEEP_RATIO * flat(p["pos"], best["pos"]):
            return held_e
        return best

    dotted = dotted if dotted is not None and living(dotted) else None
    contact_front = [e for e in level if flat(p["pos"], e["pos"]) <= CONTACT_R
                     and abs(bearing(p, e["pos"])) <= FRONT_CONE]
    if dotted is not None and flat(p["pos"], dotted["pos"]) <= FRONT_CLEAR_R:
        if contact_front and dotted not in contact_front:
            return near(contact_front), "a Majini at arm's length in front before the one under the dot"
        return dotted, "laser first hit on him"
    front_close = [e for e in level if flat(p["pos"], e["pos"]) <= FRONT_CLEAR_R and abs(bearing(p, e["pos"])) <= FRONT_CONE]
    if front_close:
        return keep(front_close, near(front_close)), "the nearest threat in front (the gun stays up)"
    contact = [e for e in level if flat(p["pos"], e["pos"]) <= CONTACT_R]
    if contact:
        return near(contact), "a Majini at arm's length: turn to him"
    if dotted is not None:                      # a farther one under the dot: no closer threat stands in front
        return dotted, "laser first hit on him"
    front = [e for e in level if flat(p["pos"], e["pos"]) <= FRONT_R and abs(bearing(p, e["pos"])) <= FRONT_CONE]
    if front:
        return keep(front, near(front)), "the nearest Majini in front"
    rest = level + [e for e in pool if e not in level and extra_ok is not None and extra_ok(e)]
    if not rest:
        return None, "none on his level in sight"
    best = min(rest, key=lambda e: cost(p, e))
    if held_e is not None and held_e in rest and best is not held_e and cost(p, best) > SWITCH_COST * cost(p, held_e):
        best = held_e
    return best, "near and in front first"


def window(dist: float) -> tuple[float, float]:
    """(yaw, pitch) half windows (radians) around his chest within which a shot from the gun still lands on him."""
    d = max(float(dist), 1.0)
    return max(WINDOW_MIN, math.atan2(BODY_R + WINDOW_PAD_CM, d)), max(WINDOW_MIN, math.atan2(PITCH_PAD_CM, d))


def deadband(dist: float) -> tuple[float, float]:
    """The slew's deadband: inside it the stick is left alone (on him: no waving)."""
    wy, wp = window(dist)
    return max(math.radians(0.6), DEADBAND_SHARE * wy), max(math.radians(0.5), DEADBAND_SHARE * wp)


def plausible(ray, p: dict, *, on_majini: bool = False):
    """(True, None) when the laser ray (origin, dot) can be his gun's: it starts near him and points roughly where he
    faces (RAY_YAW_MAX; RAY_YAW_ON_MAJINI when its dot sits on a Majini), not steeper than RAY_PITCH_MAX; else (False,
    why). No player pose: plausible (nothing to check against)."""
    if ray is None:
        return False, "no ray"
    if not p or not p.get("pos"):
        return True, None
    origin, dot = ray
    pos = p["pos"]
    if flat(pos, origin) > RAY_ORIGIN_R or not RAY_ORIGIN_DY[0] <= origin[1] - pos[1] <= RAY_ORIGIN_DY[1]:
        return False, f"origin {flat(pos, origin):.0f} cm off his feet, {origin[1] - pos[1]:+.0f} high"
    if math.dist(origin, dot) < SHORT_RAY_CM:
        return True, None                   # a dot at the muzzle: its length is evidence (something right there), its
                                            # direction is noise (6 cm rays flip 139 deg) - nobody steers by it
    run = math.hypot(dot[0] - origin[0], dot[2] - origin[2])
    pitch = math.atan2(dot[1] - origin[1], max(run, 1e-6))
    if abs(pitch) > RAY_PITCH_MAX:
        return False, f"ray pitch {math.degrees(pitch):+.0f}"
    rot = p.get("rot")
    if isinstance(rot, (int, float)) and run >= 5.0:
        off = wrap(heading(dot[0] - origin[0], dot[2] - origin[2]) - rot)
        if abs(off) > (RAY_YAW_ON_MAJINI if on_majini else RAY_YAW_MAX):
            return False, f"ray yaw {math.degrees(off):+.0f} off his heading"
    return True, None


def under_dot(ray, enemies, dot_on, *, exclude=None):
    """The living Majini whose body holds the laser dot (dot_on: re5_combat.dot_on), nearest the muzzle; else None."""
    if ray is None:
        return None
    origin, dot = ray
    hits = [e for e in enemies or () if living(e) and key(e) != exclude and dot_on(dot, e["pos"]) is not None]
    return min(hits, key=lambda e: math.dist(origin, e["pos"])) if hits else None


def dot_class(ray, foot, p: dict, enemies, dot_on) -> str:
    """What the laser dot is on at the trigger: "target" (a living Majini - the target or another), "wall" / "floor"
    (short of the target: the shot cannot reach him), "none" (beside or past him: nothing near), "off" (no ray read)."""
    if ray is None:
        return "off"
    if under_dot(ray, enemies, dot_on) is not None:
        return "target"
    if foot is None:
        return "none"
    origin, dot = ray
    chest = (foot[0], foot[1] + 110.0, foot[2])
    if math.dist(origin, dot) < math.dist(origin, chest) - SHORT_CM:
        floor = max(foot[1], (p.get("pos") or foot)[1])
        return "floor" if dot[1] <= floor + FLOOR_DOT_DY else "wall"
    return "none"


def bearing_right_deg(p: dict, pos) -> float:
    """The shared look's bearing: degrees, + = to his right."""
    return -math.degrees(bearing(p, pos))
