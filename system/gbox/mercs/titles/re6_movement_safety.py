"""Final RE6 floor exclusion after combat, recovery, and governor rewrites.

This certifies native navigation floor, not unparsed lethal scene volumes.
Mandatory grab/QTE inputs and an already active native traversal are distinct
from free walking and retain their controls.
"""
from __future__ import annotations

import math

from .re6_floor import floor_at
from .re6_walk_floor import triangle_walkable_all_directions, walk_segment
from .re6_switch_wall import STICK_REL, stick_heading
from ..re6_traversal import TRAVERSAL_ACTIONS

LOOKAHEAD_CM = 150.
#: When no 150 cm step is on verified floor, retry the same eight pad directions with this shorter step (see
#: guard()): a narrow catwalk corner can leave the 150 cm lookahead off-mesh while 60 cm is still solid floor.
LOOKAHEAD_FALLBACK_CM = 60.
#: A bomb inside the planning margin used to forbid ANY step with a component toward it ("never decrease
#: clearance"), which froze the bot outright when the only walkable floor out of a spot ran past a bomb:
#: live 2026-11-13, a single trail bomb at 427 cm held it in place for 183 s with floor_safety_why
#: "no verified floor escape direction" 930+ times, the gun down, the combo gone and the 5 s deadline missed.
#: Movement may now cross the planning margin but never come within this of a bomb; the blast itself is still
#: decided only by re6_switch_mods.detonate, which rereads every live bomb and refuses the flag below the full
#: detonate_safe_cm. Remote bombs have no proximity trigger - the flag is the only fuse - so walking past one
#: cannot set it off, while standing trapped next to it cost every round that placed a bomb at a dead end.
BOMB_TRAVEL_MIN_CM = 250.
LEFT = frozenset(('lup', 'ldown', 'lleft', 'lright'))
MOVEMENT = LEFT | {'b', 'rleft', 'rright'}
MANDATORY = frozenset(('break_free', 'held_auto_qte', 'grab_detonate', 'prompt_stick',
                       'quick_turn', 'quick_turn_settle', 'grab_panic'))


def _segment_distance(point, a, b):
    dx, dz = b[0] - a[0], b[2] - a[2]
    d2 = dx * dx + dz * dz
    t = max(0., min(1., ((point[0] - a[0]) * dx + (point[2] - a[2]) * dz) / d2)) if d2 else 0.
    return math.hypot(point[0] - a[0] - t * dx, point[2] - a[2] - t * dz)


def _all_headings_on_floor(mesh, pos):
    """Prove the whole lookahead disk has no boundary in this floor component.

    A native camera write invalidates the old snapshot yaw. It is still safe
    to keep moving where *every* heading stays on floor; near a boundary wait
    for a fresh camera sample instead of inventing a new world heading.
    """
    here = floor_at(mesh, pos, 30.)
    if here is None or not hasattr(mesh, 'edge_nb'):
        return False
    todo, seen = [here[0]], set()
    while todo and len(seen) < 128:
        k = todo.pop()
        if k in seen:
            continue
        seen.add(k)
        if not triangle_walkable_all_directions(mesh, k):
            return False
        triangle = mesh.T[k]
        for i in range(3):
            a, b = triangle[i], triangle[(i + 1) % 3]
            if _segment_distance(pos, mesh.V[a], mesh.V[b]) > LOOKAHEAD_CM:
                continue
            neighbor = mesh.edge_nb[k].get(tuple(sorted((a, b))))
            if neighbor is None:
                return False
            if neighbor not in seen:
                todo.append(neighbor)
    return not todo


def _bomb_clear(bot, snap, start, end):
    """Preserve each external bomb's safety margin, or depart it monotonically."""
    from ..remote_mines import policy
    sites = list(bot.stats.get('mine_avoid_positions') or ())
    sites += [u['pos'] for u in snap.get('throwables') or () if u.get('kind') == 'remote' and u.get('pos')]
    if not sites:
        return True
    # A confirmed ring's centre is known from its native constructor order.
    # Its remote bombs do not contact-trigger: leaving the middle necessarily
    # approaches some bombs first. Allow radial escape from any identified ring
    # still around him (a later travel receipt overwrites mine_ring_last, so the
    # ring geometry kept in mine_rings is used too); all external bombs keep
    # their nondecreasing clearance requirement.
    dx, dz = end[0] - start[0], end[2] - start[2]
    rings = [r for r in (bot.stats.get('mine_rings') or ()) if isinstance(r, dict)]
    receipt = bot.stats.get('mine_ring_last') or {}
    if isinstance(receipt, dict) and receipt.get('op') == 'bomb_ring':
        rings = [receipt] + [r for r in rings if r is not receipt]
    for ring in rings:
        units, radius = ring.get('units') or (), ring.get('radius_cm')
        if not (isinstance(units, (list, tuple)) and units
                and isinstance(radius, (int, float)) and math.isfinite(radius) and 0 < radius <= 600.):
            continue
        first = units[0].get('pos') if isinstance(units[0], dict) else None
        if not (isinstance(first, (list, tuple)) and len(first) == 3 and units[0].get('armed') is True):
            continue
        offset = math.pi / 4 if ring.get('requested') == 4 else 0.
        center = (first[0] - radius * math.cos(offset), first[2] - radius * math.sin(offset))
        radial = start[0] - center[0], start[2] - center[1]
        if (math.hypot(*radial) <= radius + 20. and radial[0] * dx + radial[1] * dz >= 0
                and math.hypot(end[0] - center[0], end[2] - center[1]) > math.hypot(*radial)):
            own = [u['pos'] for u in units if isinstance(u, dict) and u.get('armed') is True and u.get('pos')]
            sites = [p for p in sites if not any(math.dist(p, q) < 2. for q in own)]
            if not sites:
                return True
    margin = policy(bot.stats)['detonate_safe_cm']
    required = bot.stats.get('mine_required_clearance_cm')
    if isinstance(required, (int, float)) and math.isfinite(required):
        margin = max(margin, required)
    for p in sites:
        rx, rz = start[0] - p[0], start[2] - p[2]
        before = math.hypot(rx, rz)
        if before >= margin:
            if _segment_distance(p, start, end) < margin:
                return False
        elif before >= BOMB_TRAVEL_MIN_CM:
            # Inside the planning margin walking is allowed (only the flag gate detonates, and it rereads the live
            # clearance for every bomb); a step may cross the margin but must not end within BOMB_TRAVEL_MIN_CM
            # of a bomb.
            if math.hypot(end[0] - p[0], end[2] - p[2]) < BOMB_TRAVEL_MIN_CM:
                return False
        elif rx * dx + rz * dz < 0:
            # Already closer than the no-step floor (a bomb dropped at his feet): only a step that does not
            # approach it further may go, so he climbs out instead of standing on it.
            return False
    return True


def guard(bot, snap, action, now):
    from . import re6_switch as R
    p, mesh, held = snap.get('player') or {}, snap.get('navmesh'), tuple(action.get('hold') or ())
    if (snap.get('mercenaries_phase') != R.PHASE_PLAYING or (p.get('hp') or 0) <= 0
            or not set(held) & LEFT or not p.get('pos') or mesh is None
            or not all(hasattr(mesh, key) for key in ('V', 'T', 'grid', 'clear'))
            or bot.stats.get('operator_control') or getattr(bot, 'in_hold', False) or getattr(bot, 'down', False)
            or bot.stats.get('act') in MANDATORY or p.get('action') in TRAVERSAL_ACTIONS
            or p.get('action') == 'cPlAction_pl_act_land'):
        return action
    pos = tuple(p['pos'])
    rest = tuple(k for k in held if k not in MOVEMENT)
    heading_written = getattr(bot, '_floor_heading_written_at', None) == now
    heading_written = heading_written or getattr(bot, 'lock_write_at', None) == now
    escaping = bool(bot.stats.get('mine_escape_required'))
    if heading_written:
        if not escaping and _all_headings_on_floor(mesh, pos):
            return action
        why = ('native camera changed; bomb escape requires a fresh heading' if escaping else
               'native camera changed; floor boundary requires a fresh heading')
        result = dict(action, hold=rest)
    else:
        yaw = (snap.get('camera') or {}).get('yaw', p.get('rot'))
        if not isinstance(yaw, (float, int)) or not math.isfinite(yaw):
            why, result = 'camera heading unavailable at floor boundary', dict(action, hold=rest)
        else:
            heading = stick_heading(held, yaw)
            if heading is None:
                return action
            def safe(keys, *, detour=False, lookahead=LOOKAHEAD_CM):
                way = stick_heading(keys, yaw)
                end = (pos[0] + lookahead * math.sin(way), pos[1], pos[2] + lookahead * math.cos(way))
                return (mesh.clear(pos, end) is True and walk_segment(mesh, pos, end)
                        and (not (detour or escaping) or _bomb_clear(bot, snap, pos, end)))
            if safe(held):
                return action
            # Evaluate the exact eight pad directions; do not validate a
            # continuous heading and then quantize it back toward the ledge.
            options = sorted(STICK_REL, key=lambda keys: abs(R.wrap(stick_heading(keys, yaw) - heading)))
            keys = next((keys for keys in options if safe(keys, detour=True)), ())
            short = False
            if not keys and LOOKAHEAD_FALLBACK_CM > 0:
                # A 150 cm lookahead can leave the mesh from a narrow walkway/railing corner while a short step is
                # still on verified floor. Without this the guard stripped every movement for the rest of a round
                # (live 2026-11-13: floor_safety_why "no verified floor escape direction" held the bot in place
                # fighting for 140+ s). Never a longer step than before, so no new ledge is exposed.
                keys = next((keys for keys in options if safe(keys, detour=True, lookahead=LOOKAHEAD_FALLBACK_CM)), ())
                short = bool(keys)
            result = dict(action, hold=rest + keys)
            why = (('redirecting to verified floor and bomb clearance' if escaping else 'redirecting to verified floor')
                   if keys else 'no verified floor escape direction')
            if short:
                why += ' (short verified step)'
    bot.stats['floor_safety_blocks'] = int(bot.stats.get('floor_safety_blocks', 0)) + 1
    # The telemetry mirror keeps scalars only; this scalar carries the why (and the directive of the applied hold)
    # to the live panel and the round audit instead of the nested floor_safety_last object.
    bot.stats['floor_safety_why'] = why
    bot.stats['floor_safety_applied'] = ''.join(sorted(k for k in result['hold'] if k in MOVEMENT))[:24]
    bot.stats['floor_safety_last'] = dict(at=now, mesh=getattr(mesh, 'name', None), pos=list(pos),
                                        requested_hold=list(held), applied_hold=list(result['hold']), reason=why,
                                        native_heading_write=heading_written)
    bot.nav_path = None
    stand = getattr(bot, '_stand', None)
    if stand is not None:
        stand['until'] = -math.inf
    return result
