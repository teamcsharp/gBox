"""RE4 Switch's actual Garrador damage sphere, read without game writes.

Pinned c8e8f22f image: 0008f470 doubles damage to part 0x25 for native
model types 0x0a/0x0d. 001cea50 transforms its YARARE_INFO offset through
getPartsPtr(parts_no-1)->mat. 002b4f90 supplies the two part-list layouts.
The target follows the live rig; a bind-pose chest height is not a weakpoint.
"""
from __future__ import annotations

import math
import struct

ENEMY_CLASS = 0xAE7050
TYPE, PARTS, FLAGS = 0x119, 0x108, 8
HIT_ROOT, HIT_NEXT, HIT_SIZE = 0x3E8, 0x30, 0x38
PART_STRIDE, PART_NEXT, MATRIX = 0x1F0, 0x108, 0x18
WEAK_PART, MAX_HITS, MAX_PARTS = 0x25, 16, 64
MAX_REACH_MM = 6000.


def _ptr(n):
    return type(n) is int and 0x10000 <= n < 1 << 48 and n % 4 == 0


def _q(m, a):
    return struct.unpack('<Q', m.rd(a, 8))[0]


def native_type(m, base, enemy):
    """Native model type, independently of the HP-derived display name."""
    try:
        unit = enemy['ptr']
        if not _ptr(unit):
            return None
        raw = bytes(m.rd(unit, 0x11A))
        if struct.unpack_from('<Q', raw)[0] != base+ENEMY_CLASS \
                or struct.unpack_from('<I', raw, FLAGS)[0] & 0x201 != 1:
            return None
        if enemy.get('id') is not None and struct.unpack_from('<I', raw, 0x110)[0] != enemy['id']:
            return None
        enemy['routine'] = list(raw[0x114:0x118])
        return raw[TYPE]
    except (KeyError, TypeError, ValueError, OSError, struct.error):
        return None


def _part(m, root, flags, index):
    if not _ptr(root) or not 0 <= index < MAX_PARTS:
        return None
    if flags & 0x2000:
        return root + PART_STRIDE * index, ()
    seen, links, at = set(), [], root
    for _ in range(index):
        if not _ptr(at) or at in seen:
            return None
        seen.add(at)
        nxt = _q(m, at + PART_NEXT)
        links.append((at, nxt))
        at = nxt
    return (at, tuple(links)) if _ptr(at) and at not in seen else None


def read(m, base, enemy):
    """Detached native sphere or None for an unknown, disabled or torn rig.

    HP-based names never authorize a part read. Native class and model type,
    active collider, finite current matrix, and unchanged ownership are required.
    This is an aiming coordinate, never proof of a bullet hit.
    """
    try:
        unit, foot = enemy['ptr'], enemy['pos']
        if not _ptr(unit) or len(foot) != 3 or not all(math.isfinite(v) for v in foot):
            return None
        head = bytes(m.rd(unit, 0x11A))
        vt, flags = struct.unpack_from('<QI', head)
        native_type, model_id = head[TYPE], head[TYPE-1]
        identity = struct.unpack_from('<I', head, 0x110)[0]
        if enemy.get('id') is not None and enemy['id'] != identity:
            return None
        if vt != base + ENEMY_CLASS or (flags & 0x201) != 1 or native_type not in (0xA, 0xD):
            return None
        root = struct.unpack_from('<Q', head, PARTS)[0]
        seen, hit_links, at, selected = set(), [], unit + HIT_ROOT, None
        for _ in range(MAX_HITS):
            if not _ptr(at) or at in seen:
                return None
            seen.add(at)
            raw = bytes(m.rd(at, HIT_SIZE))
            on, part_no = struct.unpack_from('<Hh', raw, 0x24)
            if part_no == WEAK_PART:
                if selected is not None or not on & 1 or on & 8:
                    return None
                selected = at, raw
            nxt = struct.unpack_from('<Q', raw, HIT_NEXT)[0]
            hit_links.append((at, nxt))
            if nxt == 0:
                break
            at = nxt
        else:
            return None
        if selected is None:
            return None
        collider, raw = selected
        offset = struct.unpack_from('<3f', raw)
        radius, height = struct.unpack_from('<2f', raw, 0x18)
        if not all(math.isfinite(v) for v in (*offset, radius, height)) \
                or not 1 <= radius <= 1000 or abs(height) > 1000:
            return None
        resolved = _part(m, root, flags, WEAK_PART-1)
        if resolved is None:
            return None
        part, links = resolved
        matrix = struct.unpack('<12f', m.rd(part + MATRIX, 48))
        if not all(math.isfinite(v) for v in matrix):
            return None
        # Native sphere radius is transformed along local Z (001cea50).
        scale = math.sqrt(sum(matrix[i]**2 for i in (2, 6, 10)))
        if not .05 <= scale <= 10:
            return None
        local = list(offset)
        on = struct.unpack_from('<H', raw, 0x24)[0]
        axis = 0 if on & 2 else 2 if on & 4 else 1
        local[axis] += height * .5
        point = tuple(sum(matrix[r*4+c]*local[c] for c in range(3)) + matrix[r*4+3] for r in range(3))
        if math.dist(point, foot) > MAX_REACH_MM:
            return None
        # Reject reuse or a relink during the read; animation matrices themselves
        # naturally change and are read as one contiguous native matrix.
        after = bytes(m.rd(unit, 0x11A))
        if (struct.unpack_from('<Q', after)[0] != vt or (struct.unpack_from('<I', after, FLAGS)[0] & 0x201) != 1
                or after[TYPE-1:TYPE+1] != head[TYPE-1:TYPE+1]
                or after[0x110:0x114] != head[0x110:0x114]
                or struct.unpack_from('<Q', after, PARTS)[0] != root
                or bytes(m.rd(collider, 12)) != raw[:12]
                or bytes(m.rd(collider+0x18, 0x10)) != raw[0x18:0x28]
                or any(_q(m, a+HIT_NEXT) != nxt for a, nxt in hit_links)
                or any(_q(m, a+PART_NEXT) != nxt for a, nxt in links)):
            return None
        return {'point': point, 'radius_mm': radius*scale, 'native_type': native_type,
                'model_id': model_id, 'part_no': WEAK_PART, 'part': part, 'collider': collider,
                'owner': unit, 'owner_id': identity, 'source': 'native Garrador damage sphere',
                'matrix': matrix, 'local': tuple(local)}
    except (KeyError, TypeError, ValueError, OSError, OverflowError, struct.error):
        return None


def point(enemy):
    """Validate the detached reader result again at the aim boundary."""
    w = enemy.get('weakpoint') if isinstance(enemy, dict) else None
    try:
        p = tuple(w['point'])
        if (w['owner'] != enemy['ptr'] or w['source'] != 'native Garrador damage sphere'
                or w['native_type'] not in (0xA, 0xD) or w['part_no'] != WEAK_PART
                or (enemy.get('id') is not None and w.get('owner_id') != enemy['id'])
                or len(p) != 3 or not all(math.isfinite(v) for v in p)
                or math.dist(p, enemy['pos']) > MAX_REACH_MM):
            return None
        return p
    except (KeyError, TypeError, ValueError):
        return None


def required(enemy):
    # A known display identity may require a weakpoint, but cannot authorize a
    # native bone read. Missing native identity therefore refuses body fallback.
    return enemy.get('native_type') in (0xA, 0xD) or enemy.get('key') in ('garrador', 'garrador_armored')


def fresh(enemy, now):
    try:
        return point(enemy) is not None and 0 <= now-float(enemy['weakpoint']['at']) <= .35
    except (KeyError, TypeError, ValueError):
        return False


def pose(enemy):
    return 'garrador_back_sphere' if point(enemy) else 'garrador_unavailable' if required(enemy) else (
        'native:' + ':'.join(str(x) for x in enemy['routine']) if enemy.get('routine') else None)


def reposition(bot, player, enemy, snap, now, reason):
    """Bounded rear attempt only along an actual mesh route, then reassess.

    This does not bypass the Walker's collision guard or the title's hit/QTE
    reactions. No map means no speculative run through the boss or a wall.
    """
    from .re4_switch import AIM_REQUEST
    AIM_REQUEST.clear()  # a gun-facing lock must not fight the verified walking heading
    state = bot.__dict__.get('_weakpoint_reposition')
    identity = (enemy.get('ptr'), enemy.get('id'))
    if state is None or state['identity'] != identity:
        state = {'identity': identity, 'started': now, 'until': now+1.5, 'goal': None}
        bot.__dict__['_weakpoint_reposition'] = state
    if now >= state['until']:
        if now < state['until']+.4:
            bot.stats['weakpoint_aim'] = {'state': 'recheck', 'reason': reason, 'target': enemy.get('ptr')}
            bot.doing, bot.why = 'aim', 'rechecking the native Garrador weakpoint'
            return {'hold': {'ZL'}}
        state.update(started=now, until=now+1.5, goal=None)
    walker = getattr(bot, 'walker', None)
    mesh = getattr(walker, 'mesh', None)
    route = getattr(mesh, 'route', None)
    if callable(route):
        goals = (state['goal'],) if state['goal'] is not None else sorted(
            rear_goals(enemy), key=lambda q: math.dist(player['pos'], q))
        for goal in goals:
            try:
                path = route(tuple(player['pos']), tuple(goal))
                if not path:
                    continue
                points = [tuple(player['pos'])] + [tuple(q) for q in path]
                if not _avoids_body(points, enemy['pos']):
                    continue
                keys = set(walker.approach(goal, run=True, now=now) or ())
                if keys:
                    state['goal'] = goal
                    bot.stats['weakpoint_aim'] = {'state': 'rear_reposition', 'reason': reason,
                        'target': enemy.get('ptr'), 'goal': list(goal), 'until': state['until']}
                    bot.doing, bot.why = 'flank', 'verified floor route toward the Garrador back'
                    return {'hold': keys}
            except (TypeError, ValueError, AttributeError, IndexError):
                continue
    bot.stats['weakpoint_aim'] = {'state': 'unavailable', 'reason': reason,
                                'target': enemy.get('ptr'), 'route': 'no verified rear route'}
    bot.doing, bot.why = 'aim', 'Garrador weakpoint unavailable; rechecking before a shot'
    return {'hold': {'ZL'}}


def _avoids_body(points, enemy):
    for a, b in zip(points, points[1:]):
        if len(a) != 3 or len(b) != 3 or not all(math.isfinite(v) for v in (*a, *b, *enemy)):
            return False
        dx, dz = b[0]-a[0], b[2]-a[2]
        length2 = dx*dx+dz*dz
        t = max(0., min(1., ((enemy[0]-a[0])*dx+(enemy[2]-a[2])*dz)/max(length2, 1.)))
        near = math.hypot(a[0]+t*dx-enemy[0], a[2]+t*dz-enemy[2])
        initial = math.hypot(a[0]-enemy[0], a[2]-enemy[2])
        if near < min(initial-1., 1600.):
            return False
    return True


def rear_visible(enemy, origin):
    """Whether the shooter is on the enemy's rear half, from native facing.

    This facing test is a tactical hint; it does not claim an unobstructed shot.
    """
    try:
        rot, pos = enemy['rot'], enemy['pos']
        if not math.isfinite(rot):
            return None
        return (origin[0]-pos[0])*math.sin(rot) + (origin[2]-pos[2])*math.cos(rot) < 0
    except (KeyError, TypeError, ValueError):
        return None


def contact(origin, end, enemy):
    """Finite observed laser intersects the native weakpoint sphere (not a hit)."""
    target = point(enemy)
    if target is None:
        return None
    try:
        radius = float(enemy['weakpoint']['radius_mm'])
        delta = tuple(end[i]-origin[i] for i in range(3))
        length2 = sum(v*v for v in delta)
        if not 1 <= radius <= 10000 or length2 < 1 or not math.isfinite(length2):
            return False
        along = max(0., min(1., sum((target[i]-origin[i])*delta[i] for i in range(3))/length2))
        closest = tuple(origin[i]+along*delta[i] for i in range(3))
        return math.dist(target, closest) <= radius
    except (KeyError, TypeError, ValueError, OverflowError):
        return None


def rear_goals(enemy, distance=3000.):
    """Policy goals in the rear arc; callers must prove floor/route clearance."""
    try:
        rot, pos = enemy['rot'], enemy['pos']
        if not math.isfinite(rot) or len(pos) != 3 or not all(math.isfinite(v) for v in pos):
            return ()
        return tuple((pos[0]+distance*math.sin(rot+math.pi+angle), pos[1],
                      pos[2]+distance*math.cos(rot+math.pi+angle))
                     for angle in (0., math.pi/4, -math.pi/4))
    except (KeyError, TypeError, ValueError):
        return ()
