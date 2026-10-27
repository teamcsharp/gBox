"""A target's anatomy and the laser ray's geometry, shared by every title (moved here from the RE5 PS3 combat layer,
gbox/mercs/titles/re5_combat.py, which re-exports every name: its behaviour and tests are unchanged).

World units are the games' own: centimetres, y up. A heading follows the atan2(dx, dz) convention (forward = (sin, 0,
cos)); a positive yaw error turns left (a larger heading), a positive pitch error aims up.

The body model is a standing humanoid at foot (his position): a head sphere HEAD_R wide at HEAD_H, a body capsule BODY_R
wide from KNEE_H to SHOULDER_H, thighs THIGH_R wide from THIGH_LO to THIGH_HI (the leg-stun zone), aimed at CHEST_H by
default. The knowledge hook (knowledge.dispatch_plan) may move the aim point per enemy class and state.
"""
from __future__ import annotations

import math

HEAD_H, HEAD_R = 160.0, 22.0           # a Majini's head: a sphere this far above his feet, this wide (cm)
KNEE_H, SHOULDER_H, BODY_R = 45.0, 145.0, 36.0   # his body: a capsule between these heights, this wide
THIGH_LO, THIGH_HI, THIGH_R, THIGH_H = 45.0, 95.0, 26.0, 72.0   # his thighs: the leg-stun zone, aimed at THIGH_H
CHEST_H = 110.0                         # the default aim point: centre mass, past helmets and around shields
STEER_RAY_CM = 50.0                   # near-muzzle endpoints amplify animation/read skew into large angular errors
# Fire only down a measured line to him (operator 2026-10-22: "Right now he is shooting at nonsense"; live the same day
# 11.6 of 36 s aiming with the dot on no Majini, much of it 1-2 m off the muzzle): the dot on him, or a ray that reaches
# at least his distance within FIRE_CONE of him (tracking a moving Majini). A dot short of him or at the muzzle (a
# wall, the ground, a fence) holds the trigger.
FIRE_CONE, FIRE_SLACK = math.radians(4), 60.0   # the ray this close in angle, ending no more than this short of him
BOW_TOL_MIN, BOW_TOL_MAX = math.radians(1.5), math.radians(8)   # the longbow's release window, whatever the range
AIM_FIRE_YAW, AIM_FIRE_PITCH = math.radians(7), math.radians(5)   # fire only with the dot this close to the aim point


def wrap(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


def heading(dx: float, dz: float) -> float:
    return math.atan2(dx, dz)


def bow_tolerance(distance):
    """Release while the aim is on his body (the full centre-mass capsule), never narrower than BOW_TOL_MIN.
    Operator 2026-10-24: "have Sheva rapid firing these arrows at foes. She is sitting there not even fighting back"
    - inside half the body, capped at 2 deg, she aligned for seconds and loosed 5 arrows a round."""
    distance = max(float(distance), 1.)
    return min(BOW_TOL_MAX, max(BOW_TOL_MIN, math.atan2(BODY_R, distance))), \
        min(BOW_TOL_MAX, max(BOW_TOL_MIN, math.atan2((SHOULDER_H-KNEE_H)*.5, distance)))


def line_to(ray, aim_at, foot=None, cone=None) -> bool:
    """Whether the laser ray (origin, dot) runs to him: it ends no more than FIRE_SLACK short of the aim point, within
    cone (FIRE_CONE; the calibration widens it for a band that hits) or his body's half width, close up, of it - or,
    given his feet, it passes through his head or body on the way to a dot beyond him."""
    if ray is None:
        return False
    origin, dot = ray
    want = math.dist(origin, aim_at)
    have = math.dist(origin, dot)
    if want < 1.0 or have < want - FIRE_SLACK:
        return False
    cos = sum((dot[k] - origin[k]) * (aim_at[k] - origin[k]) for k in range(3)) / (have * want)
    if math.acos(max(-1.0, min(1.0, cos))) <= max(FIRE_CONE if cone is None else cone, math.atan2(BODY_R, want)):
        return True
    if foot is None:
        return False
    direction = tuple((dot[k] - origin[k]) / have for k in range(3))
    for h in (HEAD_H, 110.0, THIGH_H):                         # his head, chest and thighs
        along = sum((foot[k] + (h if k == 1 else 0.0) - origin[k]) * direction[k] for k in range(3))
        if 0.0 < along <= have and dot_on(tuple(origin[k] + along * direction[k] for k in range(3)),
                                                      foot) is not None:
            return True
    return False


def dot_on(dot, foot, head_r: float = HEAD_R, body_r: float = BODY_R) -> str | None:
    """Where the laser dot sits on a Majini standing at foot: "head" (inside the head sphere), "leg" (the thighs),
    "body" (inside the body capsule), else None (the ray ends somewhere else: short of him, past him, beside him)."""
    dx, dy, dz = dot[0] - foot[0], dot[1] - foot[1], dot[2] - foot[2]
    if math.sqrt(dx * dx + (dy - HEAD_H) ** 2 + dz * dz) <= head_r:
        return "head"
    flat = math.hypot(dx, dz)
    if flat <= THIGH_R and THIGH_LO <= dy <= THIGH_HI:
        return "leg"
    if flat <= body_r and KNEE_H - 10 <= dy <= SHOULDER_H + 20:
        return "body"
    return None


def ray_error(origin, dot, target) -> tuple[float, float]:
    """(yaw, pitch) radians to turn the ray origin -> dot onto target (+ yaw = left, + pitch = up)."""
    ox, oy, oz = origin
    want_yaw = heading(target[0] - ox, target[2] - oz)
    have_yaw = heading(dot[0] - ox, dot[2] - oz)
    want_pitch = math.atan2(target[1] - oy, max(math.hypot(target[0] - ox, target[2] - oz), 1.0))
    have_pitch = math.atan2(dot[1] - oy, max(math.hypot(dot[0] - ox, dot[2] - oz), 1.0))
    return wrap(want_yaw - have_yaw), want_pitch - have_pitch


def line_of_sight_aim(ray, aim_at, where, foot, scale=1.0) -> bool:
    """Whether the shot may leave the gun: the dot sits on him, or the ray points at the aim point within a few
    degrees (AIM_FIRE_YAW / AIM_FIRE_PITCH, times scale) and does not end on the floor short of him. Coaching note 3:
    R1 held while the dot was on the ground (turning toward him, or aimed below him) fired the magazine into the floor
    and lost time."""
    if where is not None:
        return True
    if ray is None:
        return False
    origin, dot = ray
    yaw, pitch = ray_error(origin, dot, aim_at)
    if abs(yaw) > AIM_FIRE_YAW * scale or abs(pitch) > AIM_FIRE_PITCH * scale:
        return False
    flat_dot, flat_tgt = math.hypot(dot[0] - origin[0], dot[2] - origin[2]), math.hypot(foot[0] - origin[0], foot[2] - origin[2])
    short_on_floor = flat_dot < flat_tgt - BODY_R * 2 and dot[1] < foot[1] + KNEE_H
    return not short_on_floor


def valid_ray(origin, dot):
    """Keep endpoint evidence separate from whether its short baseline can guide the stick."""
    try:
        origin, dot = tuple(origin), tuple(dot)
        if (len(origin) == len(dot) == 3 and any(origin)
                and all(math.isfinite(v) for v in (*origin, *dot)) and math.dist(origin, dot) >= 5.0):
            return origin, dot
    except (TypeError, ValueError, OverflowError):
        pass
    return None


def steering_ray(ray, target):
    """A defensive direction baseline, reduced for genuinely close targets; not a visibility test.

    Run9 contains 6 cm rays reversing elevation by 139 degrees while the player's reported pitch barely changes.
    Endpoints can still prove an overlap/obstruction, but a tiny muzzle-to-dot vector must not drive full stick.
    """
    return math.dist(*ray) >= min(STEER_RAY_CM, math.dist(ray[0], target) * 0.5)


def aim_point(foot, offset=(0.0, CHEST_H, 0.0)) -> tuple:
    """The point on him to aim at: his position plus the dispatch plan's offset (knowledge.DispatchPlan.aim_offset)."""
    return (foot[0] + offset[0], foot[1] + offset[1], foot[2] + offset[2])
