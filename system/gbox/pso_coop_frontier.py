"""Deterministic field objectives on a verified, player-layer collision grid.

Native gate classes identify an approach objective, never an open/clear predicate.
Only observed actor movement and transitions establish progress. Combat keeps
priority in Controller; this helper owns no inputs, memory writes or lifecycle.
"""
from __future__ import annotations

from collections import deque
import math

from .pso_coop_nav import geometry_view

GATES = frozenset({'TObjDoor', 'TOBarrierEnergy01', 'TObjLazerFenceNorm'})
DIRECTIONS = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))


def same_room_threats(state, player):
    return [e for e in state.get('entities', ())
            if e.get('kind') == 'enemy' and type(e.get('hp')) is int and e['hp'] > 0
            and e.get('room') == player.get('room')]


def field_actions(selected, state):
    """A field model cannot open Start menus; menus still have their own guard."""
    if state.get('verified') and state.get('phase') == 14 and state.get('floor', 0) > 0:
        return [row for row in selected if 'start' not in row[1]]
    return selected


def _finite(row, keys=('x', 'y', 'z')):
    return all(type(row.get(k)) in (int, float) and math.isfinite(row[k]) for k in keys)


def _gate_key(row):
    return str(row['class']), round(row['x'], 1), round(row['y'], 1), round(row['z'], 1)


class FieldObjectives:
    def __init__(self):
        self.identity = None
        self.active = {}
        self.completed = set()
        self.deferred = {}
        self.visited = set()
        self.origins = {}
        self.rooms = {}
        self.regroup = {}
        self.routes = {}
        self.frontiers = {}
        self.firing = {}
        self.revision = 0
        self.status = {'state': 'inactive', 'room_clear_verified': False, 'players': {}}

    def _bind(self, state):
        key = (state.get('episode'), state.get('floor'), state.get('geometry_identity'))
        if key != self.identity:
            self.identity = key
            self.active.clear()
            self.completed.clear()
            self.deferred.clear()
            self.visited.clear()
            self.origins.clear()
            self.rooms.clear()
            self.regroup.clear()
            self.routes.clear()
            self.frontiers.clear()
            self.firing.clear()
            self.status = {'state': 'inactive', 'room_clear_verified': False, 'players': {}}
        self.status.update(source='verified_native_collision', geometry_identity=key[2],
                           room_clear_verified=False)

    def _frontier(self, nav, player, layer, now):
        """Bounded connected-space search; no path through unknown floor or walls."""
        start = nav.cell((player['x'], player['z']))
        cache_key = (nav,layer,start,frozenset(self.visited),frozenset(self.completed),
                     frozenset(k for k,v in self.deferred.items() if v > now),frozenset(nav.blocked))
        if cache_key in self.frontiers:
            return self.frontiers[cache_key]
        self.revision += 1
        origin = self.origins.setdefault(layer, start)
        previous, depths = {start: None}, {start: 0.0}
        todo = deque([start])
        best, best_score = None, None
        while todo and len(previous) < 1800:
            cell = todo.popleft()
            distance = depths[cell]
            key = ('frontier', layer, cell)
            if (distance >= 55 and (layer, cell) not in self.visited and key not in self.completed
                    and self.deferred.get(key, 0) <= now):
                clearance = sum((cell[0]+dx, cell[1]+dz) in nav.floor for dx, dz in DIRECTIONS)
                score = (math.dist(cell, origin) * nav.size + distance * .15 + clearance,
                         -cell[0], -cell[1])
                if best_score is None or score > best_score:
                    best, best_score = cell, score
            if distance >= 150:
                continue
            for dx, dz in DIRECTIONS:
                nxt = cell[0]+dx, cell[1]+dz
                if nxt in previous or not nav.allowed(cell, nxt):
                    continue
                previous[nxt], depths[nxt] = cell, distance + math.hypot(dx, dz) * nav.size
                todo.append(nxt)
        result = nav.center(best) if best is not None else None
        self.frontiers[cache_key] = result
        if len(self.frontiers) > 16:
            self.frontiers.pop(next(iter(self.frontiers)))
        return result

    def route(self, nav, start, goal):
        """Cache successes and failures only for this exact static map and cells.

        New blocked edges change the key. Every search, including a failed one,
        forces Controller to obtain fresh native observations before any input.
        """
        key = (nav,nav.cell(start),nav.cell(goal),frozenset(nav.blocked))
        if key not in self.routes:
            self.revision += 1
            self.routes[key] = nav.route(start,goal)
            if len(self.routes) > 128:
                self.routes.pop(next(iter(self.routes)))
        path = self.routes[key]
        if path and not all(nav.allowed(nav.cell(a),nav.cell(b)) for a,b in zip(path,path[1:])):
            self.routes.pop(key,None)
            return None
        return path

    def combat_goal(self, nav, player, target, envelope):
        """A reachable stance inside the envelope, never the enemy's floor cell.

        The enemy may stand outside the conservative player grid. This search
        only traverses the player's own verified grid; range is not hit proof.
        Both successful and failed bounded searches require fresh observation.
        """
        if nav.floor is None or not nav.heights or not _finite(player) or not _finite(target):
            return None
        limits = tuple(envelope.get(k) for k in ('horizontal','vertical','vertical_half_angle'))
        if any(type(v) not in (int,float) or not math.isfinite(v) or v <= 0 for v in limits):
            return None
        start = nav.cell((player['x'],player['z']))
        if start not in nav.floor or start not in nav.heights:
            return None
        def suitable(cell):
            point = nav.center(cell)
            distance = math.dist(point,(target['x'],target['z']))
            height = abs(nav.heights[cell]-target['y'])
            return (distance <= limits[0]*.90 and height <= limits[1] and
                    math.degrees(math.atan2(height,max(distance,.001))) <= limits[2])
        # Cell-bound caching avoids a moving enemy forcing a new full search
        # each frame. Validate the chosen stance against exact fresh coordinates.
        key = (nav,start,target.get('ptr'),limits,frozenset(nav.blocked))
        exact_target = tuple(target[k] for k in ('x','y','z'))
        if key in self.firing:
            cached, observed_target = self.firing[key]
            if ((cached is None and observed_target == exact_target) or
                    (cached is not None and suitable(nav.cell(cached)))):
                return cached
            self.firing.pop(key,None)
        self.revision += 1
        previous, distances = {start:None}, {start:0.}
        todo = deque([start])
        found = None
        while todo and len(previous) <= 6000:
            cell = todo.popleft()
            if suitable(cell):
                found = cell
                break
            if distances[cell] >= 600:
                continue
            for dx,dz in DIRECTIONS:
                nxt = cell[0]+dx,cell[1]+dz
                if nxt in previous or not nav.allowed(cell,nxt):
                    continue
                previous[nxt] = cell
                distances[nxt] = distances[cell]+math.hypot(dx,dz)*nav.size
                todo.append(nxt)
        result = nav.center(found) if found is not None else None
        self.firing[key] = (result,exact_target)
        if len(self.firing) > 64:
            self.firing.pop(next(iter(self.firing)))
        if found is not None:
            path = [found]
            while previous[path[-1]] is not None:
                path.append(previous[path[-1]])
            self.routes[(nav,start,found,frozenset(nav.blocked))] = [nav.center(c) for c in reversed(path)]
            if len(self.routes)>128:
                self.routes.pop(next(iter(self.routes)))
        return result

    def _choose(self, state, player, nav, layer, now):
        candidates = []
        entities = sorted((e for e in state.get('entities', ())[:512] if _finite(e)),
                          key=lambda e: math.dist((player['x'], player['z']), (e['x'], e['z'])))
        inspected = 0
        for entity in entities:
            if entity.get('kind') != 'gate' or entity.get('class') not in GATES or not _finite(entity):
                continue
            key = ('gate', layer, _gate_key(entity))
            if key in self.completed or self.deferred.get(key, 0) > now:
                continue
            point = entity['x'], entity['z']
            if math.dist((player['x'], player['z']), point) > 700:
                continue
            cell = nav.cell(point)
            # Only the player's selected surface may provide this approach.
            height = getattr(nav, 'heights', {}).get(cell)
            if height is None or abs(height-entity['y']) > 8:
                continue
            inspected += 1
            if inspected > 12:
                break
            route = self.route(nav,(player['x'], player['z']), point)
            if not route:
                continue
            length = sum(math.dist(a, b) for a, b in zip(route, route[1:]))
            if length > 900:
                continue
            candidates.append((length, _gate_key(entity), key, point, entity))
        if candidates:
            _, _, key, point, entity = min(candidates, key=lambda row: row[:2])
            evidence = entity.get('door_requirements') or {}
            predicate = evidence.get('predicate', 'unknown') if evidence.get('code_verified') else 'unknown'
            return {'key': key, 'point': point, 'exit': {k: entity.get(k) for k in
                    ('class', 'entity_id', 'ptr', 'room', 'x', 'y', 'z')}, 'predicate': predicate,
                    'dependency': 'gate_proximity'}
        point = self._frontier(nav, player, layer, now)
        if point is None:
            return None
        return {'key': ('frontier', layer, nav.cell(point)), 'point': point, 'exit': None,
                'predicate': 'unknown', 'dependency': 'explore'}

    def destination(self, state, slot, nav, now):
        player = state.get('players', {}).get(slot)
        if (not player or state.get('verified') is not True or state.get('phase') != 14
                or state.get('floor', 0) <= 0 or state.get('geometry_verified') is not True):
            self.status.update(state='unknown_geometry')
            return None
        self._bind(state)
        previous_room = self.rooms.get(slot)
        if previous_room is not None and previous_room != player.get('room'):
            self.status['last_transition'] = {'player': slot, 'from_room': previous_room,
                                              'to_room': player.get('room')}
        self.rooms[slot] = player.get('room')
        row = self.status['players'].setdefault(str(slot), {})
        threats = same_room_threats(state, player)
        row.update(room=player.get('room'), enemy_count=len(threats), room_clear_verified=False)
        if threats:
            row.update(dependency='combat', outcome='combat', goal=None, exit=None, predicate='unknown')
            self.status['state'] = 'combat'
            return None
        view = geometry_view(state, player)
        layer = view.get('geometry_layer')
        if not layer or nav.floor is None or not _finite(player):
            self.status.update(state='unknown_geometry')
            row.update(outcome='held', dependency='own_geometry_unavailable', goal=None, exit=None, predicate='unknown')
            return None
        cell = nav.cell((player['x'], player['z']))
        self.visited.add((layer, cell))
        if len(self.visited) > 30000:
            self.visited = {(layer, cell)}
        buddy = state.get('players', {}).get(3-slot)
        if not buddy or not _finite(buddy) or buddy.get('hp', 0) <= 0:
            row.update(goal=None, exit=None, predicate='unknown', dependency='buddy_unavailable', outcome='held')
            self.status['state'] = 'waiting_for_living_buddy'
            return None
        buddy_view = geometry_view(state, buddy)
        separation = math.dist((player['x'], player['z']), (buddy['x'], buddy['z']))
        split_room = player.get('room') != buddy.get('room')
        missing_buddy_view = not buddy_view.get('geometry_layer')
        if split_room or separation > (85 if slot == 1 else 65) or (slot == 1 and missing_buddy_view):
            if slot == 1 and slot in self.active:
                self.active[slot]['progress_at'] = now
            row.update(goal=None, exit=None, predicate='unknown', dependency='buddy_regroup')
            if slot == 1:
                row['outcome'] = 'waiting_for_buddy'
                self.status['state'] = 'waiting_for_buddy'
                return None
            # A leader reaching an approach must not invalidate P2's unfinished
            # connector, even when its shared key is already marked completed.
            old = self.active.get(slot)
            choices = []
            if (old and old['key'][1] == layer and old.get('exit') and
                    math.dist((player['x'],player['z']),old['point']) > 2.5):
                choices.append((old['point'], old['exit'].get('y'), old['exit']))
            if (buddy_view.get('geometry_layer') == layer and
                    buddy_view.get('geometry_identity') == state.get('geometry_identity')):
                choices.append(((buddy['x'],buddy['z']),buddy['y'],None))
            else:
                # The buddy can be just outside the margin. Its independently
                # proven recovery endpoint is only a goal; P2 must prove its own
                # full route to it on P2's layer before receiving any movement.
                recovery = state.get('geometry_recovery_players',{}).get(3-slot,{})
                path = recovery.get('path') or []
                heights = recovery.get('path_heights') or []
                if (recovery.get('source') == 'verified_native_collision_base' and
                        recovery.get('geometry_identity') == state.get('geometry_identity') and
                        recovery.get('geometry_layer') == layer and recovery.get('player_ptr') == buddy.get('ptr') and
                        path and len(path) == len(heights)):
                    choices.append((tuple(path[-1]),heights[-1],None))
            for point, target_y, exit_row in choices:
                if (len(point)!=2 or any(type(v) not in (int,float) or not math.isfinite(v) for v in point)
                        or type(target_y) not in (int,float) or not math.isfinite(target_y)):
                    continue
                height = nav.heights.get(nav.cell(point))
                if (height is not None and abs(height-target_y) <= 8 and
                        self.route(nav,(player['x'],player['z']),point)):
                    token = ('regroup',layer,nav.cell(point))
                    distance = math.dist((player['x'],player['z']),point)
                    progress_key = (slot,token)
                    previous = self.regroup.get(progress_key)
                    if previous is None:
                        previous = self.regroup[progress_key] = dict(key=token,best=distance,progress_at=now)
                        if len(self.regroup) > 64:
                            self.regroup.pop(next(iter(self.regroup)))
                        self.revision += 1
                    elif distance < previous['best']-2:
                        previous.update(best=distance,progress_at=now)
                    elif now-previous['progress_at'] > 6:
                        continue
                    row.update(goal={'x':point[0],'z':point[1]}, exit=exit_row, outcome='active')
                    self.status['state'] = 'regrouping'
                    return point
            row['outcome'] = 'held'
            row['dependency'] = 'no_verified_regroup_route'
            self.status['state'] = 'no_verified_regroup_route'
            return None
        self.regroup = {k:v for k,v in self.regroup.items() if k[0] != slot}
        active = self.active.get(slot)
        if active and active['key'][1] != layer:
            active = None
            self.active.pop(slot, None)
        if active:
            distance = math.dist((player['x'], player['z']), active['point'])
            tolerance = 2.5 if active['exit'] else 9
            if distance <= tolerance:
                self.completed.add(active['key'])
                self.status['last_outcome'] = {'player': slot, 'outcome': 'approach_reached',
                    'exit': active['exit'], 'passability_verified': False}
                row.update(outcome='reached', predicate='approach_reached_not_gate_open')
                self.active.pop(slot, None)
                active = None
            elif distance < active['best']-2:
                active['best'], active['progress_at'] = distance, now
            elif now-active['progress_at'] > 6:
                self.deferred[active['key']] = now+30
                self.active.pop(slot, None)
                row.update(outcome='blocked', predicate='unknown', goal=None)
                self.status['state'] = 'blocked_objective'
                return None
        if active is None:
            leader = self.active.get(1) if slot == 2 else None
            if (leader and leader['key'][1] == layer and leader['key'] not in self.completed and
                    self.route(nav,(player['x'],player['z']),leader['point'])):
                active = dict(leader)
            else:
                active = self._choose(state, player, nav, layer, now)
            if active is None:
                row.update(outcome='held', dependency='unknown_geometry', goal=None, exit=None, predicate='unknown')
                self.status['state'] = 'no_verified_route'
                return None
            active.update(best=math.dist((player['x'], player['z']), active['point']), progress_at=now)
            self.active[slot] = active
            self.revision += 1
        row.update(goal={'x': active['point'][0], 'z': active['point'][1]}, exit=active['exit'],
                   predicate=active['predicate'], dependency=active['dependency'], outcome='active')
        self.status['state'] = 'routing'
        return active['point']
