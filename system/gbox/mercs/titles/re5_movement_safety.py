"""Final movement exclusion for measured lethal RE5 stage volumes.

Combat, wall recovery and mine escape can all rewrite movement. This guard runs
after them, checks the actual left-stick direction, and never treats walkable
floor as proof that an incinerator is safe.
"""
from __future__ import annotations

import math

from . import re5_stage_hazards as hazards
from .re5_switch_wall import _travel_heading

LOOKAHEAD_CM = 200.0
MOVEMENT = frozenset(('lup', 'ldown', 'lleft', 'lright', 'b', 'rleft', 'rright'))
# Routing clearances around a newly placed five-foot ring; these are not blast radii.
RING_ENVELOPE_CM, MINE_FOOTPRINT_CM = 180., 45.


def _end(mesh, pos, heading):
    point = (pos[0] + LOOKAHEAD_CM * math.sin(heading), pos[1],
             pos[2] + LOOKAHEAD_CM * math.cos(heading))
    if callable(getattr(mesh, 'find', None)) and callable(getattr(mesh, '_height', None)):
        tri = mesh.find(point, floor_only=True)
        height = mesh._height(tri, point[0], point[2]) if tri is not None else None
        if height is not None and math.isfinite(height):
            point = (point[0], height, point[2])
    return point


def _mine_clear(bot, snap, start, end):
    from .re5_nav import NavMesh
    from .re5_switch_mines import BLAST_CM
    mines = getattr(bot, 'mines', None)
    sites = dict(getattr(mines, 'bombs', {}))
    escape = getattr(mines, '_native_escape', None)
    cluster, predicted = set(), ()
    if escape:
        sites.update(escape.get('sites', {}))
        predicted = escape.get('predicted', ())
        center = escape['center']
        cluster = {key for key, p in escape.get('sites', {}).items()
                   if math.hypot(p[0]-center[0],p[2]-center[2]) <= RING_ENVELOPE_CM}
        radial = (start[0]-center[0], start[2]-center[2])
        step = (end[0]-start[0], end[2]-start[2])
        cluster_exit = (math.hypot(*radial) <= RING_ENVELOPE_CM
            and radial[0]*step[0]+radial[1]*step[1] >= 0
            and math.hypot(end[0]-center[0],end[2]-center[2]) > math.hypot(*radial))
    else:
        cluster_exit = False
    for row in snap.get('ground_mines') or ():
        if row.get('pos'):
            sites[row.get('ptr', row.get('unit', ('unidentified', tuple(row['pos']))))] = row['pos']
    # Mine avoidance remains horizontal, matching the existing native tactic.
    # At the center of a surrounding ring, moving away from *every* mine is
    # impossible. Cross a gap out of this identified small cluster while keeping
    # all external mines' full margins and never crossing a mine's footprint.
    margins = [((p[0], start[1], p[2]), MINE_FOOTPRINT_CM if cluster_exit and key in cluster else BLAST_CM)
               for key,p in sites.items()]
    margins += [((p[0], start[1], p[2]), MINE_FOOTPRINT_CM if cluster_exit and
                 math.hypot(p[0]-center[0],p[2]-center[2]) <= RING_ENVELOPE_CM else BLAST_CM)
                for p in predicted]
    return NavMesh.hazard_segment_clear(
        start, (end[0], start[1], end[2]), margins, departing=True)


def guard(bot, action, snap, now):
    mesh, player = snap.get('nav'), snap.get('player') or {}
    known = hazards.for_mesh(mesh)
    if not known:
        bot.stats['stage_hazard_coverage'] = {'mesh': getattr(mesh, 'sig', None), 'volumes': 0,
                                             'source': 'unavailable', 'policy': 'no verified scene catalogue'}
        return action
    if not player.get('pos') or (player.get('hp') or 0) <= 0:
        return action
    bot.stats['stage_hazard_coverage'] = {'mesh': mesh.sig, 'volumes': len(known),
                                         'source': 'native_scene', 'policy': 'hard_exclusion'}
    from . import re5_switch as config
    if player.get('motion') in config.MOTION_HELD:
        return action  # these stick inputs resolve the grab, not walking
    if getattr(bot, 'doing', None) in ('held', 'prompt') and snap.get('prompt') \
            and bot._prompt_type(snap['prompt'], snap) in ('enemy', 'dying'):
        return action
    held = tuple(action.get('hold') or ())
    heading = _travel_heading(player, held)
    if heading is None:
        return action
    if bot.stats.get('target_feedback_ram') is True:
        # Native aim can rotate the actor after this snapshot. A world-space
        # safe heading cannot be certified from its previous rotation.
        bot.stats['stage_hazard_heading_waits'] = bot.stats.get('stage_hazard_heading_waits', 0) + 1
        return dict(action, hold=tuple(k for k in held if k not in MOVEMENT))
    pos = tuple(player['pos'])
    end = _end(mesh, pos, heading)
    hazard = hazards.blocked_segment(mesh, pos, end, departing=True)
    if hazard is None:
        return action

    # No later governor may put the rejected direction back into the pad.
    bot.stats['stage_hazard_blocks'] = bot.stats.get('stage_hazard_blocks', 0) + 1
    route = getattr(bot, '_mroute', None)
    if route is not None:
        route.update(at=-1e9, pts=None)
    bot._mesh_wp = None
    safe = None
    rot = player.get('rot') or 0.0
    room = getattr(bot, '_sm', None)
    directions = sorted(range(8), key=lambda i: abs(config.wrap(rot + i * math.pi / 4 - heading)))
    for direction in directions:
        rel = config.wrap(direction * math.pi / 4)
        point = _end(mesh, pos, rot + rel)
        if hazards.blocked_segment(mesh, pos, point, departing=True) is not None:
            continue
        if not mesh.floor_segment(pos, point) or not _mine_clear(bot, snap, pos, point):
            continue
        if room is not None and room.walk_block(pos, point, end_r=0., body_r=config.ROOM_BRUSH_CM) is not None:
            continue
        safe = (rel, point)
        break
    rest = tuple(k for k in held if k not in MOVEMENT)
    if safe is None:
        result = dict(action, hold=rest)
        state = 'blocked; no verified escape heading'
    else:
        rel, point = safe
        # Aimed movement is constrained by the game; release aim for an evasive step.
        rest = tuple(k for k in rest if k not in ('zl', 'zr'))
        keys = config.Bot._stick_toward(rel)
        if abs(rel) < math.radians(22.5):
            keys += ('b',)
        elif abs(rel) <= math.radians(135):
            keys += ('rleft',) if rel > 0 else ('rright',)
        result = dict(action, hold=rest + keys)
        state = 'steering along verified floor away from lethal volume'
    bot.doing, bot.why = 'hazard_avoid', f'{hazard.name}: {state}'
    if now - getattr(bot, '_hazard_report_at', -math.inf) >= 1.:
        bot._hazard_report_at = now
        bot.stats['stage_hazard_last'] = {'at': now, 'mesh': mesh.sig, 'pos': list(pos),
            'proposed_end': list(end), 'safe_end': list(safe[1]) if safe else None,
            'requested_hold': list(held), 'applied_hold': list(result['hold']),
            'state': state, 'hazard': hazard.evidence()}
    return result


def prompt_allowed(bot, snap, now, *, kind=None):
    """Check locomotion prompts too; enemy/grab and recovery QTEs remain admitted."""
    mesh, player, prompt = snap.get('nav'), snap.get('player') or {}, snap.get('prompt')
    if not hazards.for_mesh(mesh) or not prompt or not player.get('pos'):
        return True
    kind = kind or bot._prompt_type(prompt, snap)
    if kind not in ('door', 'traverse'):
        return True
    pos = tuple(player['pos'])
    path = (getattr(bot, '_mroute', None) or {}).get('pts') or ()
    waypoint = path[0] if path else None
    if waypoint is not None and hasattr(waypoint, 'approach') and math.dist(pos, waypoint.approach) <= 150.:
        hit = hazards.blocked_path(mesh, pos, [waypoint], departing=True)
    else:
        hit = hazards.blocked_segment(mesh, pos, _end(mesh, pos, player.get('rot') or 0.), departing=True)
    if hit is None:
        return True
    bot.stats['stage_hazard_prompt_blocks'] = bot.stats.get('stage_hazard_prompt_blocks', 0) + 1
    bot.stats['stage_hazard_last'] = {'at': now, 'mesh': mesh.sig, 'pos': list(pos),
        'state': 'locomotion prompt enters native lethal volume', 'prompt_kind': kind,
        'label': prompt.get('label'), 'hazard': hit.evidence()}
    return False
