"""Read RE5's posed human joints for aim; never infer posture from a motion byte.

Native EBFFDB22: 00eccf90 traverses uModel+8c8 with count+8c0 and stride c0;
00e14290 resolves animation IDs through +8d0 and uses Joint+50 as world XYZ.
Joint+a8 owns the uModel (00ece3c0). See re5-posed-aim.md for live corroboration.
These joints locate a conservative torso/head aiming proxy, not a verified hit.
"""
from __future__ import annotations

import math
import struct

COUNT, JOINTS, CONVERSION, ACTION = 0x8C0, 0x8C8, 0x8D0, 0x1B60
STRIDE, WORLD, OWNER = 0xC0, 0x50, 0xA8
MODEL, GENERATION = 0x118, 0x1A00
# Only layouts measured from these classes' native models. Creature animation
# IDs do not share human meanings; a dog/chicken must retain its class profile.
HUMANOIDS = frozenset({'uEm10', 'uEm11', 'uEm12', 'uEm13', 'uEm14', 'uEm1d', 'uEm1e',
                       'uEm20', 'uEm21', 'uEm22', 'uEm23', 'uEm24', 'uEm26', 'uEm92'})
IDS = (2, 4, 6, 11, 16, 20, 17, 21)  # spine, head, upper arms, thighs, knees
MAX_JOINTS, MAX_REACH_CM = 255, 500.
RADIUS, HEAD_RADIUS = 36., 22.


def read(m, enemy):
    """A detached selected-target pose, or None on absent/torn/foreign geometry."""
    from . import re5_switch as R
    if enemy.get('class') not in HUMANOIDS:
        return None
    try:
        e, foot = enemy['ptr'], enemy['pos']
        if not R.ptr_ok(e):
            return None
        identity = R.u64(m, e), R.u64(m, e + GENERATION)
        if enemy.get('generation', identity[1]) != identity[1]:
            return None
        model, joints, conv = (R.u64(m, e + off) for off in (MODEL, JOINTS, CONVERSION))
        count = struct.unpack('<I', m.rd(e + COUNT, 4))[0]
        if not all(R.ptr_ok(p) for p in (model, joints, conv)) or not 1 <= count <= MAX_JOINTS:
            return None
        mapping = bytes(m.rd(conv, max(IDS) + 1))
        indices = [mapping[i] for i in IDS]
        if any(i >= count or i == 255 for i in indices) or len(set(indices)) != len(indices):
            return None
        action_ptr = R.u64(m, e + ACTION)
        action_vt = R.u64(m, action_ptr) if R.ptr_ok(action_ptr) else 0
        action = R.enemy_class(m, action_ptr) if R.ptr_ok(action_ptr) else None
        points = {}
        for anim_id, index in zip(IDS, indices):
            raw = m.rd(joints + index * STRIDE, STRIDE)
            point = struct.unpack_from('<3f', raw, WORLD)
            if struct.unpack_from('<Q', raw, OWNER)[0] != e or not all(math.isfinite(v) for v in point) \
                    or math.dist(point, foot) > MAX_REACH_CM:
                return None
            points[anim_id] = point
        # The same allocation may survive a costume/model swap or an action
        # transition. Repeat the capabilities after reading the eight joints.
        if ((R.u64(m, e), R.u64(m, e + GENERATION)) != identity
                or (R.u64(m, e + MODEL), R.u64(m, e + JOINTS), R.u64(m, e + CONVERSION)) != (model, joints, conv)
                or struct.unpack('<I', m.rd(e + COUNT, 4))[0] != count
                or bytes(m.rd(conv, len(mapping))) != mapping
                or R.u64(m, e + ACTION) != action_ptr
                or (action_vt and R.u64(m, action_ptr) != action_vt)):
            return None
        hips = tuple((points[16][i] + points[20][i]) / 2 for i in range(3))
        shoulders = tuple((points[6][i] + points[11][i]) / 2 for i in range(3))
        knees = tuple((points[17][i] + points[21][i]) / 2 for i in range(3))
        # Reject collapsed/uninitialised joints and corrupt human mappings,
        # regardless of the current orientation (lying down is valid).
        if not 10 <= math.dist(hips, shoulders) <= 200 \
                or not 3 <= math.dist(points[2], points[4]) <= 150:
            return None
        return {'aim': points[2], 'head': points[4], 'hips': hips, 'shoulders': shoulders, 'knees': knees,
                'radius': RADIUS, 'head_radius': HEAD_RADIUS, 'action': action,
                'action_ptr': action_ptr, 'owner': e, 'generation': identity[1]}
    except (KeyError, TypeError, ValueError, IndexError, OSError, OverflowError, struct.error):
        return None


def _sub(a, b):
    return tuple(x-y for x, y in zip(a, b))


def _dot(a, b):
    return sum(x*y for x, y in zip(a, b))


def segment_distance(a, b, c, d):
    """Shortest finite-segment distance, including parallel/degenerate segments."""
    u, v, w = _sub(b, a), _sub(d, c), _sub(a, c)
    aa, bb, cc, dd, ee = _dot(u, u), _dot(u, v), _dot(v, v), _dot(u, w), _dot(v, w)
    clamp = lambda n: max(0., min(1., n))
    if aa < 1e-9:
        s, t = 0., clamp(ee/cc) if cc > 1e-9 else 0.
    else:
        if cc < 1e-9:
            s, t = clamp(-dd/aa), 0.
        else:
            denom = aa*cc-bb*bb
            s = clamp((bb*ee-cc*dd)/denom) if denom > 1e-9 else 0.
            t = (bb*s+ee)/cc
            if t < 0.:
                s, t = clamp(-dd/aa), 0.
            elif t > 1.:
                s, t = clamp((bb-dd)/aa), 1.
    return math.dist(tuple(a[i]+s*u[i] for i in range(3)), tuple(c[i]+t*v[i] for i in range(3)))


def dot_on(point, pose):
    if math.dist(point, pose['head']) <= pose['head_radius']:
        return 'head'
    if any(segment_distance(point, point, a, b) <= pose['radius'] for a, b in
           ((pose['hips'], pose['shoulders']), (pose['knees'], pose['hips']))):
        return 'body'
    return None


def contact(origin, dot, pose):
    """Only the observed finite ray; a wall ending before the body cannot hit it."""
    return bool(dot_on(dot, pose)
                or segment_distance(origin, dot, pose['head'], pose['head']) <= pose['head_radius']
                or any(segment_distance(origin, dot, a, b) <= pose['radius'] for a, b in
                       ((pose['hips'], pose['shoulders']), (pose['knees'], pose['hips']))))


def aim_point(pose, requested_height, profile):
    """Preserve head/stagger preference, mapped onto the actual current pose."""
    if requested_height >= profile.chest:
        lo, hi = pose['aim'], pose['head']
        t = (requested_height-profile.chest)/max(1., profile.head-profile.chest)
    else:
        lo, hi = pose['knees'], pose['aim']
        t = (requested_height-profile.knee)/max(1., profile.chest-profile.knee)
    t = max(0., min(1., t))
    return tuple(lo[i]+t*(hi[i]-lo[i]) for i in range(3))


def spread(origin, dot, pose, cone, wall_slack):
    reach, distance = math.dist(origin, dot), math.dist(origin, pose['aim'])
    if min(reach, distance) < 1. or reach < distance-wall_slack:
        return False
    cosine = _dot(_sub(dot, origin), _sub(pose['aim'], origin)) / (reach*distance)
    return math.acos(max(-1., min(1., cosine))) <= cone
