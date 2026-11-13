"""Final native-mine movement priority, after aim and wall postprocessors.

A departure is complete only outside every observed/retained mine's margin.
Routes use actual linked floor and collision, never a straight ray through a
wall or a successful clearance from only the most recent placement batch.
"""
from __future__ import annotations

import heapq
import math
import struct
import time

from . import re5_movement_safety as movement, re5_stage_hazards as hazards
from .re5_nav import FloorWaypoint, STEP_DY
from .re5_switch_mines import RETREAT_CM, flat

REPLAN_S, MAX_TRAVEL_CM, MAX_NODES = .75, 6000., 6000


def _sites(bot, snap):
    mines = getattr(bot, 'mines', None)
    return mines.native_sites(snap) if mines is not None else {}


def _veto(bot, snap, a, b):
    """The first actual exclusion, not a guessed reason for failing to move."""
    mesh, room = snap.get('nav'), getattr(bot, '_sm', None)
    if mesh is None or not callable(getattr(mesh, 'floor_segment', None)):
        return 'floor'
    if not mesh.floor_segment(a, b):
        return 'floor'
    if not movement._mine_clear(bot, snap, a, b):
        return 'mine'
    if hazards.blocked_segment(mesh, a, b, departing=True) is not None:
        return 'stage'
    if room is not None:
        from .re5_switch import ROOM_BRUSH_CM
        if room.walk_block(a, b, end_r=0., body_r=ROOM_BRUSH_CM) is not None:
            return 'room'
    return None


def _clear(bot, snap, a, b):
    return _veto(bot, snap, a, b) is None


def _route(bot, snap, start):
    """Search native triangle portals; None if their centres offer no safe exit."""
    mesh, sites = snap.get('nav'), _sites(bot, snap)
    if not sites:
        return []
    if all(flat(start, site) >= RETREAT_CM for site in sites.values()):
        return []
    if mesh is None or not callable(getattr(mesh, 'find', None)):
        return None
    source = mesh.find(start, floor_only=True, height_slack=61.)
    if source is None:
        return None
    costs, previous, queue = {source: 0.}, {}, [(0., source)]
    blocked = getattr(bot, 'blocked_links', ())
    best, endpoint, visited = None, None, 0
    while queue and visited < MAX_NODES:
        cost, u = heapq.heappop(queue)
        if cost != costs[u] or cost > MAX_TRAVEL_CM:
            continue
        visited += 1
        origin = start if u == source else mesh.centre[u]
        candidates = [mesh.centre[u]]
        for index in mesh.tris[u]:
            vertex, center = mesh.points[index], mesh.centre[u]
            inset = min(1., 75. / max(math.dist(vertex, center), 1.))
            candidates.append(tuple(vertex[k] + inset * (center[k] - vertex[k]) for k in range(3)))
        clear = [q for q in candidates if all(flat(q, site) >= RETREAT_CM for site in sites.values())
                 and cost + math.dist(origin, q) <= MAX_TRAVEL_CM and _clear(bot, snap, origin, q)]
        if clear:
            best, endpoint = u, min(clear, key=lambda q: math.dist(origin, q))
            break
        for v, edge, _ in mesh.links[u]:
            if ((u, v) in blocked or not 0 <= v < len(mesh.tris) or not 0 <= edge < 3
                    or mesh.steep[u] or mesh.steep[v]
                    or abs(mesh.centre[u][1] - mesh.centre[v][1]) >= STEP_DY):
                continue
            if not {mesh.tris[u][edge], mesh.tris[u][(edge + 1) % 3]} <= set(mesh.tris[v]):
                continue
            portal = mesh._portal(u, edge)
            if not _clear(bot, snap, origin, portal) or not _clear(bot, snap, portal, mesh.centre[v]):
                continue
            distance = cost + math.dist(origin, portal) + math.dist(portal, mesh.centre[v])
            if distance < costs.get(v, math.inf) and distance <= MAX_TRAVEL_CM:
                costs[v], previous[v] = distance, (u, edge)
                heapq.heappush(queue, (distance, v))
    if best is None:
        return None
    hops, node = [], best
    while node != source:
        u, edge = previous[node]
        hops.append((u, edge, node))
        node = u
    path = []
    for u, edge, v in reversed(hops):
        path.extend((FloorWaypoint(mesh._portal(u, edge), (u, v)), mesh.centre[v]))
    if not path or math.dist(path[-1], endpoint) > 1e-6:
        path.append(endpoint)
    return path if all(_clear(bot, snap, a, b) for a, b in zip([start] + path, path)) else None


def route(bot, snap, start):
    """A supported route clear of all mines, or None; no action-link shortcuts.

    Between two overlapping mine margins, the initial safe direction can be a
    narrow sideways gap that misses all triangle portals. A short floor-checked
    step can reach that gap before the native portal search resumes.
    """
    path = _route(bot, snap, start)
    if path is not None:
        return path
    mesh, sites = snap.get('nav'), _sites(bot, snap)
    if mesh is None or not sites or not callable(getattr(mesh, 'find', None)):
        return None
    probes = []
    for i in range(16):
        end = start
        for _ in range(4):
            end = movement._end(mesh, end, i * math.tau / 16)
            if not _clear(bot, snap, start, end):
                break
            probes.append((min(flat(end, p) for p in sites.values()), end))
    for _, end in sorted(probes, reverse=True)[:4]:
        tail = _route(bot, snap, end)
        if tail is not None:
            result = [end] + tail
            if sum(math.dist(a, b) for a, b in zip([start] + result, result)) <= MAX_TRAVEL_CM:
                return result
    return None


def _active_traversal(bot, snap, now):
    """Preserve an already owned native action, never grant a new traversal."""
    from . import re5_switch as config, re5_traversal as traversal
    player, obs = snap['player'], bot.stats.get('traversal_observation') or {}
    owner = [bot.stats.get('round_evidence_id'), player.get('ptr'), player.get('generation')]
    at, m = obs.get('at'), getattr(bot, '_m', None)
    if (not owner[0] or obs.get('state') != 'native' or obs.get('active') is not True
            or obs.get('owner') != owner or obs.get('name') not in traversal.TRAVERSALS
            or type(at) not in (int, float) or not 0 <= now-at <= .5 or m is None):
        return False
    started = time.monotonic()
    try:
        action = obs['action']
        # The snapshot fact was validated by the exact native class reader.
        # Check that its player/action still owns it before preserving input.
        return (config.u64(m, player['ptr']+traversal.ACTION) == action
                and config.u64(m, action) == obs['action_vtable']
                and config.u64(m, action+traversal.ACTOR_OWNER) == player['ptr']
                and config.u64(m, player['ptr']+0x1A00) == player['generation']
                and time.monotonic()-started <= .05)
    except (KeyError, OSError, ValueError, TypeError, struct.error, OverflowError):
        return False


def _mandatory(bot, snap, now):
    from . import re5_switch as config
    player = snap['player']
    if player.get('motion') in config.MOTION_HELD or bot.doing == 'held':
        return 'native grab/QTE recovery'
    if bot.doing == 'prompt' and snap.get('prompt'):
        kind = bot._prompt_type(snap['prompt'], snap)
        if kind in ('enemy', 'dying', 'other'):
            return 'mandatory prompt input'
    if bot.doing in ('native_equip', 'heal', 'flashbang'):
        return 'native equipment/healing synchronization'
    if _active_traversal(bot, snap, now):
        return 'verified active native traversal'
    if player.get('motion') == config.MOTION_SHOT:
        return 'boosted shot animation movement lock'
    if now < getattr(bot, '_shot_until', -math.inf):
        return 'boosted shot tail movement lock'
    return None


def assess(bot, snap, now):
    """Recheck eight physical steps each snapshot; cache only within this tick."""
    from . import re5_switch as config
    player, mines = snap.get('player') or {}, getattr(bot, 'mines', None)
    if (mines is None or mines.native is None or not player.get('pos')
            or (player.get('hp') or 0) <= config.DYING_HP
            or snap.get('mercenaries_phase') != config.PHASE_PLAYING
            or bot.stats.get('operator_control')):
        return None
    sites = _sites(bot, snap)
    if not sites:
        return None
    pos = tuple(player['pos'])
    nearest = min(flat(pos, site) for site in sites.values())
    mesh = snap.get('nav')
    fingerprint = (getattr(mesh, 'sig', None), tuple(sorted((str(k), tuple(v)) for k, v in sites.items())),
                   tuple(sorted(getattr(bot, 'blocked_links', ()))))
    key = (now, id(snap), pos, player.get('rot'), id(getattr(bot, '_sm', None)), fingerprint)
    assessment = getattr(bot, '_native_escape_assessment', None)
    if assessment is not None and assessment['key'] == key:
        return assessment
    cache = getattr(bot, '_native_final_route', None)
    if cache is None or cache['key'] != fingerprint or now - cache['at'] >= REPLAN_S:
        cache = bot._native_final_route = {'key': fingerprint, 'at': now, 'pts': route(bot, snap, pos)}
    points = cache['pts']
    while points and len(points) > 1 and flat(pos, points[0]) <= 70. and _clear(bot, snap, pos, points[1]):
        points.pop(0)
    waypoint = points[0] if points else None
    if waypoint is not None and not _clear(bot, snap, pos, waypoint):
        cache['at'], cache['pts'], waypoint = -math.inf, None, None
    nearest_site = min(sites.values(), key=lambda q: flat(pos, q))
    desired = (math.atan2(waypoint[0] - pos[0], waypoint[2] - pos[2]) if waypoint is not None
               else math.atan2(pos[0] - nearest_site[0], pos[2] - nearest_site[2]))
    rot = player.get('rot') or 0.
    candidates, vetoes = [], dict.fromkeys(('floor', 'room', 'mine', 'stage'), 0)
    for i in range(8):
        rel = config.wrap(i * math.pi / 4)
        end = movement._end(mesh, pos, rot + rel)
        veto = _veto(bot, snap, pos, end)
        if veto:
            vetoes[veto] += 1
            continue
        # Do not waive every mine's margin just because the recent batch is clear.
        gain = min(flat(end, site) for site in sites.values()) - nearest
        angle = abs(config.wrap(rot + rel - desired))
        candidates.append((angle, -gain, rel, end))
    safe = min(candidates) if candidates else None
    assessment = {'key': key, 'required': nearest < RETREAT_CM, 'pos': pos,
                  'nearest': nearest, 'sites': sites, 'safe': safe, 'points': points,
                  'waypoint': waypoint, 'vetoes': vetoes}
    bot._native_escape_assessment = assessment
    return assessment


def blocked(bot, snap, now):
    assessment = assess(bot, snap, now)
    return bool(assessment and assessment['required'] and assessment['safe'] is None)


def defend(bot, snap, live, now):
    """Acquire a real target while trapped. apply() alone may add the trigger."""
    from . import re5_switch as config, re5_switch_aim as aim, re5_weapons
    if not blocked(bot, snap, now):
        return None
    gun = next((row for row in snap.get('inventory') or () if row.get('hand')), {})
    spec = re5_weapons.WEAPONS.get(gun.get('item'))
    if not spec or spec.family not in aim.GUN_FAMILIES:
        return None                         # ordinary rearm/weapon handling remains responsible
    player = snap['player']
    live = [e for e in live if (e.get('hp') or 0) > 0 and e.get('pos')
            and flat(player['pos'], e['pos']) <= config.ENGAGE_R]
    if not live:
        bot._trigger(False, now)
        bot.doing, bot.why = 'no_foes', 'mine escape blocked; no living target in gun range'
        return {'hold': ()}
    target = bot._choose(player, live, now)
    bot._set_target(target.get('ptr', target.get('slot')), now)
    if bot.aim_since is None:
        bot.aim_since = bot._raise_t = now
        bot.stats['raises'] = bot.stats.get('raises', 0) + 1
    bot.doing, bot.why = 'aim', 'mine escape blocked; acquiring threat without unsafe movement'
    bot.stats['native_mine_defense_target'] = bot.target
    return {'hold': ('zl',)}


def guard(bot, action, snap, now, *, before_aim=False, combat_action=None):
    """Escape if a safe step exists; otherwise retain independently gated combat."""
    from . import re5_switch as config
    assessment = assess(bot, snap, now)
    bot.stats['native_mine_defending'] = False
    if assessment is None:
        return action
    player, held = snap['player'], tuple(action.get('hold') or ())
    pos, nearest, sites = assessment['pos'], assessment['nearest'], assessment['sites']
    heading = movement._travel_heading(player, held)
    proposed = movement._end(snap.get('nav'), pos, heading) if heading is not None else None
    bot.stats['native_mine_escape_required'] = assessment['required']
    unsafe = proposed is not None and not movement._mine_clear(bot, snap, pos, proposed)
    if not assessment['required'] and not unsafe:
        return action
    pause = _mandatory(bot, snap, now)
    bot.stats['native_mine_escape_pause'] = pause
    if pause and not pause.startswith('boosted shot'):
        return action
    safe, points, waypoint = assessment['safe'], assessment['points'], assessment['waypoint']
    if safe is None:
        # No safe movement exists: dropping the gun cannot make departure any
        # more possible. A shot/tail is only a movement lock, not a combat veto.
        # Late wall/idle processors may have replaced combat with a movement
        # plan; recover ONLY the gun keys accepted by this tick's aim feedback.
        source = combat_action if combat_action is not None else action
        keys = tuple(k for k in source.get('hold') or () if k not in movement.MOVEMENT)
        result = dict(source, hold=keys)
        state = 'blocked: no verified floor escape from all mines; defending in place'
        bot.stats['native_mine_defending'] = True
        bot._aim_wait = None
        if combat_action is not None and 'zl' in keys:
            bot.doing = 'fire' if 'zr' in keys else 'aim'
        bot.why = state
    else:
        if pause:
            # Once a lane exists, releasing ZR lets the actual shot/tail expire
            # instead of perpetually renewing the boosted movement lock.
            bot._gun_down()
            bot.doing, bot.why = 'mine', pause + '; releasing trigger before departure'
            return {'hold': ()}
        if not before_aim and bot.stats.get('target_feedback_ram') is True:
            bot._gun_down()
            bot.doing, bot.why = 'mine', 'native aim changed heading; wait for fresh pose before escape movement'
            bot.stats['native_mine_escape_pause'] = 'fresh player heading after native aim write'
            return {'hold': ()}
        _, _, rel, end = safe
        keys = config.Bot._stick_toward(rel)
        if abs(rel) <= math.radians(22.5):
            keys += ('b',)
        elif abs(rel) < math.pi - .01:
            keys += ('rleft',) if rel > 0 else ('rright',)
        result = {'hold': keys}
        state = 'departing every observed mine on verified floor'
        bot._gun_down()
        bot._aim_wait = None
        bot.doing, bot.why = 'mine', state
    bot.stats['native_mine_escape_final_overrides'] = bot.stats.get('native_mine_escape_final_overrides', 0) + int(result != action)
    bot.stats['native_mine_escape_clearance_cm'] = round(nearest, 1)
    bot.stats['native_mine_escape_hazards'] = len(sites)
    bot.stats['native_mine_escape_vetoes'] = assessment['vetoes']
    bot._native_route, bot._native_route_active = tuple(points or ()), bool(points)
    if waypoint is not None:
        bot._mesh_wp = (waypoint[0], waypoint[2], now)
    if now - getattr(bot, '_native_escape_report_at', -math.inf) >= .5:
        bot._native_escape_report_at = now
        bot.stats['native_mine_escape_final'] = {'at': now, 'pos': list(pos), 'clearance_cm': round(nearest, 1),
            'hazards': len(sites), 'requested_hold': list(held), 'applied_hold': list(result['hold']),
            'safe_end': list(safe[3]) if safe else None, 'state': state,
            'candidate_vetoes': dict(assessment['vetoes']),
            'route': [list(p) for p in points[:12]] if points else []}
    return result
