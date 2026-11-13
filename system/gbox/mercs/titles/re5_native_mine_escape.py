"""Final native-mine movement priority, after aim and wall postprocessors.

A departure is complete only outside every observed/retained mine's margin.
Routes use actual linked floor and collision, never a straight ray through a
wall or a successful clearance from only the most recent placement batch.
"""
from __future__ import annotations

import heapq
import math

from . import re5_movement_safety as movement, re5_stage_hazards as hazards
from .re5_nav import FloorWaypoint, STEP_DY
from .re5_switch_mines import RETREAT_CM, flat

REPLAN_S, MAX_TRAVEL_CM, MAX_NODES = .75, 6000., 6000


def _sites(bot, snap):
    mines = getattr(bot, 'mines', None)
    return mines.native_sites(snap) if mines is not None else {}


def _clear(bot, snap, a, b):
    mesh, room = snap.get('nav'), getattr(bot, '_sm', None)
    if mesh is None or not callable(getattr(mesh, 'floor_segment', None)):
        return False
    if not mesh.floor_segment(a, b) or not movement._mine_clear(bot, snap, a, b):
        return False
    if hazards.blocked_segment(mesh, a, b, departing=True) is not None:
        return False
    if room is not None:
        from .re5_switch import ROOM_BRUSH_CM
        if room.walk_block(a, b, end_r=0., body_r=ROOM_BRUSH_CM) is not None:
            return False
    return True


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


def _mandatory(bot, snap, now):
    from . import re5_switch as config
    player = snap['player']
    if player.get('motion') in config.MOTION_HELD or bot.doing == 'held':
        return 'native grab/QTE recovery'
    if bot.doing == 'prompt' and snap.get('prompt'):
        kind = bot._prompt_type(snap['prompt'], snap)
        if kind in ('enemy', 'dying', 'other'):
            return 'mandatory prompt input'
    if bot.doing in ('native_equip', 'heal'):
        return 'native equipment/healing synchronization'
    if player.get('motion') == config.MOTION_SHOT:
        return 'boosted shot animation movement lock'
    if now < getattr(bot, '_shot_until', -math.inf):
        return 'boosted shot tail movement lock'
    return None


def guard(bot, action, snap, now, *, before_aim=False):
    """Own final movement while departing; later stage guard can still veto it."""
    from . import re5_switch as config
    player, mines = snap.get('player') or {}, getattr(bot, 'mines', None)
    if (mines is None or mines.native is None or not player.get('pos')
            or (player.get('hp') or 0) <= config.DYING_HP
            or snap.get('mercenaries_phase') != config.PHASE_PLAYING
            or bot.stats.get('operator_control')):
        return action
    sites = _sites(bot, snap)
    if not sites:
        return action
    pos, held = tuple(player['pos']), tuple(action.get('hold') or ())
    nearest = min(flat(pos, site) for site in sites.values())
    heading = movement._travel_heading(player, held)
    proposed = movement._end(snap.get('nav'), pos, heading) if heading is not None else None
    required = nearest < RETREAT_CM
    bot.stats['native_mine_escape_required'] = required
    unsafe = proposed is not None and not movement._mine_clear(bot, snap, pos, proposed)
    if not required and not unsafe:
        return action
    pause = _mandatory(bot, snap, now)
    bot.stats['native_mine_escape_pause'] = pause
    if pause:
        if pause.startswith('boosted shot'):
            # Holding ZR starts another boosted shot and refreshes the movement
            # lock forever. Release the gun now, wait out this actual shot/tail,
            # then depart without applying boosted movement to the runner.
            bot._gun_down()
            bot.doing, bot.why = 'mine', pause + '; releasing trigger before departure'
            return {'hold': ()}
        return action
    if not before_aim and bot.stats.get('target_feedback_ram') is True:
        bot._gun_down()
        bot.doing, bot.why = 'mine', 'native aim changed heading; wait for fresh pose before escape movement'
        bot.stats['native_mine_escape_pause'] = 'fresh player heading after native aim write'
        return {'hold': ()}
    mesh = snap.get('nav')
    fingerprint = (getattr(mesh, 'sig', None), tuple(sorted((str(k), tuple(v)) for k, v in sites.items())),
                   tuple(sorted(getattr(bot, 'blocked_links', ()))))
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
    candidates = []
    for i in range(8):
        rel = config.wrap(i * math.pi / 4)
        end = movement._end(mesh, pos, rot + rel)
        if not _clear(bot, snap, pos, end):
            continue
        # Do not waive every mine's margin just because the recent batch is clear.
        gain = min(flat(end, site) for site in sites.values()) - nearest
        angle = abs(config.wrap(rot + rel - desired))
        candidates.append((angle, -gain, rel, end))
    safe = min(candidates) if candidates else None
    if safe is None:
        result = {'hold': ()}
        state = 'blocked: no verified floor escape from all mines'
    else:
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
    bot._native_route, bot._native_route_active = tuple(points or ()), bool(points)
    if waypoint is not None:
        bot._mesh_wp = (waypoint[0], waypoint[2], now)
    if now - getattr(bot, '_native_escape_report_at', -math.inf) >= .5:
        bot._native_escape_report_at = now
        bot.stats['native_mine_escape_final'] = {'at': now, 'pos': list(pos), 'clearance_cm': round(nearest, 1),
            'hazards': len(sites), 'requested_hold': list(held), 'applied_hold': list(result['hold']),
            'safe_end': list(safe[3]) if safe else None, 'state': state,
            'route': [list(p) for p in points[:12]] if points else []}
    return result
