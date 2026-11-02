"""One observed 3OE2 Pioneer 2 corridor, using the owned collision REL.

This is a static, sampled clearance constraint, not measured actor radius or
dynamic-door state. Native room IDs change along this corridor; ordinary room
learning is deliberately not reused. Menu selection belongs to MenuProgress.
"""
import hashlib
import heapq
import math
from collections import defaultdict

from .registry import Unsupported

REL = 'Scene/map_city00_00c.rel'
REL_SHA = '6d5f5d5d0ff9c18958d1ab577e5be9e6f83c66808537b085ca4c9d2cd97535ec'
SIZE = 2.5
TRIANGLES_SHA = '03d26c27a128ecc58de161843c86b55878f6e512a0badbdfcb06bdd2de13da26'
GEOMETRY_ID = hashlib.sha256(f'3OE2|1|0|{TRIANGLES_SHA}'.encode()).hexdigest()
PLATFORM = (360.003, 25.998)
# Observed native constellation, including the platform's otherwise ambiguous
# TObject. Sentinel room 65535 is accepted only for this exact scene match.
LANDMARKS = (
    ('TObjCityDoor_Med', 16401, 10, (193.501, 0., -93.495)),
    ('TObjCityDoor_Guild', 16404, 10, (184.998, 0., 172.999)),
    ('TObjCityDoor_Warp', 16405, 10, (254.001, 0., 25.002)),
    ('TObject', None, 65535, (360.003, 1., 25.998)),
)


def _finite(values):
    return all(type(v) in (int, float) and math.isfinite(v) for v in values)


def _pointer(value):
    if not isinstance(value, str) or len(value) != 8:
        return False
    try:
        address = int(value, 16)
    except ValueError:
        return False
    return 0x80000000 <= address < 0x81800000 and address % 4 == 0


def scene(state):
    if (state.get('verified') is not True or state.get('profile') != 'pso-gc-plus-us' or
            state.get('globals', {}).get('disc_id') != 'GPOE8P' or
            state.get('phase') != 14 or state.get('episode') != 1 or state.get('floor') != 0 or
            state.get('travelling') or set(state.get('players', {})) != {1, 2} or
            any(e.get('kind') == 'enemy' and e.get('hp', 0) > 0 for e in state.get('entities', []))):
        return None
    identities = []
    for cls, entity_id, room, point in LANDMARKS:
        # The generic platform's entity ID is allocated at runtime (18372
        # and 18354 in owned captures). Its unique exact scene constellation,
        # class, room and position establish this landmark instead.
        rows = [e for e in state.get('entities', []) if e.get('class') == cls and
                (e.get('entity_id') == entity_id if entity_id is not None else
                 e.get('room') == room and _finite([e.get(k) for k in ('x','y','z')]) and
                 all(abs(e[k]-v) <= .15 for k,v in zip(('x','y','z'),point)))]
        if len(rows) != 1:
            return None
        row = rows[0]
        xyz = [row.get(k) for k in ('x', 'y', 'z')]
        if row.get('room') != room or not _finite(xyz) or any(abs(a-b) > .15 for a,b in zip(xyz, point)):
            return None
        if not _pointer(row.get('ptr')):
            return None
        identities.append(row['ptr'])
    for p in state['players'].values():
        if (p.get('class') != 'TObjPlayer' or p.get('hp', 0) <= 0 or
                not isinstance(p.get('ptr'), str) or not p['ptr'] or
                not _finite([p.get(k) for k in ('x', 'y', 'z', 'heading_deg')]) or not -.1 <= p['y'] <= 1.1):
            return None
    if state['players'][1]['ptr'] == state['players'][2]['ptr']:
        return None
    return (state.get('difficulty'), *(state['players'][s]['ptr'] for s in (1, 2)), *identities)


class Corridor:
    """Height-filtered grid confined to the actually traversed east-town region.

    Every upward surface at a cell must be on the observed y0..1 ground. An
    overlapping upper/lower floor rejects that cell instead of selecting maxY.
    Three-by-three erosion is a conservative static margin, not an actor-size
    measurement. Exact start/end connectors are checked; no nearest-cell snap.
    """
    def __init__(self, triangles):
        from .psomap import _inside, _height, TRIGGER_FLAG
        heights, walls = defaultdict(list), set()
        if not 0 < len(triangles) <= 1500:
            raise Unsupported('Town triangle count differs')
        for a, b, c, flags, normal in triangles:
            if not _finite([*a, *b, *c, *normal]) or any(abs(v) > 3000 for p in (a,b,c) for v in p):
                raise Unsupported('Town geometry bounds differ')
            if flags & TRIGGER_FLAG:
                continue
            if normal[1] > .6:
                for i in range(max(72, math.floor(min(a[0],b[0],c[0])/SIZE)), min(152, math.floor(max(a[0],b[0],c[0])/SIZE))+1):
                    for j in range(max(2, math.floor(min(a[2],b[2],c[2])/SIZE)), min(116, math.floor(max(a[2],b[2],c[2])/SIZE))+1):
                        x, z = self.center((i,j))
                        if _inside(x,z,a,b,c):
                            heights[i,j].append(_height(x,z,a,b,c))
            elif abs(normal[1]) <= .6 and max(a[1],b[1],c[1]) > 3 and min(a[1],b[1],c[1]) < 20:
                for p,q in ((a,b),(b,c),(c,a)):
                    steps = max(1, math.ceil(math.hypot(q[0]-p[0],q[2]-p[2])/.5))
                    for k in range(steps+1):
                        u=k/steps
                        walls.add(self.cell((p[0]+(q[0]-p[0])*u,p[2]+(q[2]-p[2])*u)))
        self.base = {p for p,h in heights.items() if min(h) >= -.1 and max(h) <= 1.1} - walls
        self.safe = {p for p in self.base if all((p[0]+i,p[1]+j) in self.base
                    for i in (-1,0,1) for j in (-1,0,1))}

    @staticmethod
    def cell(point):
        return tuple(math.floor(v / SIZE) for v in point)

    @staticmethod
    def center(cell):
        return tuple((v+.5)*SIZE for v in cell)

    def clear(self, start, end, excluded=()):
        return self._clear(start, end, self.safe, excluded)

    def _clear(self, start, end, floor, excluded=()):
        if not _finite([*start,*end]):
            return False
        distance=math.dist(start,end)
        if distance > 800:
            return False
        # Check every grid crossing and each intervening open interval. A
        # fixed-distance sampler can skip a tiny forbidden corner crossing.
        crossings = {0., 1.}
        for dimension in (0, 1):
            delta = end[dimension] - start[dimension]
            if not delta:
                continue
            low, high = sorted((start[dimension], end[dimension]))
            for boundary in range(math.ceil(low/SIZE), math.floor(high/SIZE)+1):
                crossings.add((boundary*SIZE-start[dimension])/delta)
        ordered = sorted(crossings)
        samples = ordered + [(a+b)/2 for a,b in zip(ordered,ordered[1:])]
        for u in samples:
            x,z=(start[n]+(end[n]-start[n])*u for n in (0,1))
            cells={(math.floor((x+dx)/SIZE),math.floor((z+dz)/SIZE))
                   for dx in (-1e-7,1e-7) for dz in (-1e-7,1e-7)}
            if any(c not in floor or c in excluded for c in cells):
                return False
        return True

    def recover(self, start, excluded=()):
        """Shortest bounded grid path from known base floor into static margin.

        This exact town base rejects raised/overlapping floors and solid-wall
        cells. It does not establish actor clearance or dynamic passability.
        """
        if not _finite(start):
            return None
        first = self.cell(start)
        if (first not in self.base or first in self.safe or first in excluded or
                not self._clear(start, self.center(first), self.base, excluded)):
            return None
        initial = math.dist(start, self.center(first))
        queue = [(initial, first)]
        cost, previous = {first: initial}, {first: None}
        while queue and len(previous) <= 128:
            distance, cell = heapq.heappop(queue)
            if distance != cost[cell] or distance > 12:
                continue
            if cell in self.safe:
                chain = []
                while cell is not None:
                    chain.append(self.center(cell)); cell = previous[cell]
                return [start, *reversed(chain)]
            for dx, dz in ((1,0),(-1,0),(0,1),(0,-1)):
                nxt = cell[0] + dx, cell[1] + dz
                score = distance + SIZE
                if (score > 12 or nxt not in self.base or nxt in excluded or
                        score >= cost.get(nxt, math.inf) or
                        not self._clear(self.center(cell), self.center(nxt), self.base, excluded)):
                    continue
                cost[nxt] = score; previous[nxt] = cell
                heapq.heappush(queue, (score, nxt))
        return None

    def route(self, start, end=PLATFORM, excluded=()):
        if not _finite([*start,*end]):
            return None
        first,last=self.cell(start),self.cell(end)
        if (first not in self.safe or last not in self.safe or first in excluded or last in excluded or
                not self.clear(start,self.center(first),excluded) or not self.clear(self.center(last),end,excluded)):
            return None
        queue=[(0,first)]; previous={first:None}; cost={first:0}
        while queue and len(previous)<=10000:
            _,p=heapq.heappop(queue)
            if p==last:
                chain=[]
                while p is not None:
                    chain.append(self.center(p));p=previous[p]
                result=[start,*reversed(chain),end]
                return result if all(self.clear(a,b,excluded) for a,b in zip(result,result[1:])) else None
            for dx,dz in ((1,0),(-1,0),(0,1),(0,-1)):
                nxt=p[0]+dx,p[1]+dz
                if nxt not in self.safe or nxt in excluded:
                    continue
                score=cost[p]+1
                if score>=cost.get(nxt,100000):
                    continue
                cost[nxt]=score;previous[nxt]=p
                heapq.heappush(queue,(score+abs(nxt[0]-last[0])+abs(nxt[1]-last[1]),nxt))
        return None


def load_corridor(ad):
    from .gcdisc import GCDisc
    from .psomap import collision
    path=getattr(ad,'memory_card_rom',None)
    if not path or ad.read_memory(0x80000000,8) != b'GPOE8P\0\x02':
        raise Unsupported('Town route requires the current 3OE2 disc and native header')
    disc=GCDisc(path)
    try:
        if disc._r(0,8) != b'GPOE8P\0\x02' or disc.files.get(REL,(0,0))[1] != 70144:
            raise Unsupported('Town collision disc identity differs')
        data=disc.read(REL)
        # Exact immutable hash bounds the established decoder before parsing.
        if len(data)!=70144 or hashlib.sha256(data).hexdigest()!=REL_SHA:
            raise Unsupported('Town collision source fingerprint differs')
        return Corridor(collision(data))
    finally:
        disc.f.close()


class TownRoute:
    def __init__(self, ad, *, corridor=None):
        self.ad,self.corridor=ad,corridor
        self.identity=None;self.rows={};self.failure=None
        self.status={'state':'inactive','arrival_verified':False}

    def bind(self,state):
        identity=scene(state)
        if identity is None:
            self.status={'state':'held','reason':'Town scene/height/landmark identity unavailable','arrival_verified':False}
            self.identity=None;self.rows.clear()
            return None
        identity=(*identity,getattr(self.ad,'_pso_timing_epoch',0))
        if identity!=self.identity:
            self.identity=identity;self.rows.clear()
        if self.corridor is None and self.failure is None:
            try:self.corridor=load_corridor(self.ad)
            except (OSError,ValueError,KeyError,Unsupported) as exc:self.failure=str(exc)
        if self.failure:
            self.status={'state':'held','reason':self.failure,'arrival_verified':False}
            return None
        return identity

    def plan(self,state,now):
        if self.bind(state) is None:return {}
        commands={};reports={}
        for slot,p in state['players'].items():
            pos=(p['x'],p['z'])
            row=self.rows.setdefault(slot,dict(attempts=0,stalls=0,wait_until=0.,halted=False,
                excluded={},last=None,last_target=None,best=math.inf,no_progress=0,halt_position=None,
                recovering=False,margin_attempts=0))
            if row['halted'] and math.dist(pos,row['halt_position'])>=5:
                # A separately observed position change (e.g. operator help)
                # permits a fresh bounded attempt; time alone never unlatches.
                self.rows.pop(slot);return self.plan(state,now)
            if row['halted'] or row['attempts']>=600:
                row.update(halted=True,halt_position=row['halt_position'] or pos)
                reports[slot]='held_after_bounded_stalls';continue
            if now<row['wait_until']:
                reports[slot]='waiting_for_door_reobservation';continue
            row['excluded']={c:until for c,until in row['excluded'].items() if until>now}
            row['recovering']=False
            route=self.corridor.route(pos,excluded=row['excluded'])
            if not route:
                # Only this exact loaded city mesh can authorize leaving the
                # conservative margin. No unknown floor/height is projected.
                proven = (state.get('geometry_verified') is True and
                    state.get('geometry_identity') == GEOMETRY_ID and
                    state.get('geometry_source', {}).get('triangles_sha256') == TRIANGLES_SHA)
                recovery = self.corridor.recover(pos, row['excluded']) if proven else None
                if not recovery or not self.corridor.route(recovery[-1], excluded=row['excluded']):
                    reports[slot]='held_no_clear_route';continue
                if row['margin_attempts'] >= 8:
                    row.update(halted=True,halt_position=pos)
                    reports[slot]='held_margin_recovery_limit';continue
                waypoint = recovery[1]
                for point in recovery[2:]:
                    if math.dist(pos,point)>6 or not self.corridor._clear(pos,point,self.corridor.base,row['excluded']):break
                    waypoint=point
                if math.dist(pos,waypoint)<.5:
                    reports[slot]='held_connector_too_short';continue
                row['recovering']=True
                commands[slot]=waypoint
                reports[slot]='recovering_static_margin_clearance_unknown';continue
            row['margin_attempts']=0
            if math.dist(pos,PLATFORM)<=4:
                reports[slot]='at_platform_waiting_for_observed_menu';continue
            remaining=sum(math.dist(a,b) for a,b in zip(route,route[1:]))
            if remaining<row['best']-2:
                row['best']=remaining;row['no_progress']=0
            if row['no_progress']>=8:
                row['stalls']+=1;row['no_progress']=0;row['wait_until']=now+1.5
                if row['stalls']>=3:
                    row.update(halted=True,halt_position=pos)
                elif row['last_target'] is not None:
                    cell=self.corridor.cell(row['last_target'])
                    if cell!=self.corridor.cell(pos):row['excluded'][cell]=now+5
                reports[slot]='held_after_bounded_stalls' if row['halted'] else 'waiting_for_door_reobservation'
                continue
            waypoint=route[1]
            for point in route[2:]:
                if math.dist(pos,point)>12 or not self.corridor.clear(pos,point,row['excluded']):break
                waypoint=point
            if math.dist(pos,waypoint)<.5:
                reports[slot]='held_connector_too_short';continue
            commands[slot]=waypoint
            reports[slot]='following_static_corridor'
        self.status=dict(state='routing' if commands else 'held',players=reports,
            geometry_sha256=REL_SHA,static_margin=SIZE,dynamic_doors_verified=False,
            actor_radius_verified=False,arrival_verified=False,
            clearance_unknown_players=[slot for slot,row in self.rows.items() if row.get('recovering')],
            note='Only the independent destination-menu observer can confirm arrival/entry')
        return commands

    def moved(self,slot):
        # Called only after the ordinary input hold completed successfully.
        row=self.rows[slot];row['attempts']+=1;row['no_progress']+=1
        if row.get('recovering'):row['margin_attempts']+=1

    def pulse_seconds(self,slot):
        return .04 if self.rows[slot].get('recovering') else .08

    def target(self,slot,point):
        self.rows[slot]['last_target']=point
