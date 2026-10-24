"""Measured follow/protect planning for a separately owned Player 2 controller.

This module returns goals, routes and target preferences. It never sends input,
changes game memory, invents visibility or falls back to controlling Player 1.
The title driver supplies fresh actor/camera/prompt/controller ownership proof.
"""
from __future__ import annotations

import math


def _point(value):
    return isinstance(value, (tuple, list)) and len(value)==3 and all(type(v) in (int,float) and math.isfinite(v) for v in value)


def _actor(row):
    value = row.get('actor',row.get('ptr',row.get('id')))
    return value if type(value) is int and value>0 or isinstance(value,str) and 0<len(value)<=96 else None


def _alive(row):
    return type(row.get('hp')) in (int,float) and math.isfinite(row['hp']) and row['hp']>0 and _point(row.get('pos'))


def _fresh(observed, now, max_age):
    return type(observed) in (int,float) and math.isfinite(observed) and 0<=now-observed<=max_age


class FollowProtect:
    """Distances are metres converted using the title's explicit world-unit scale.

    A native Traversal remains an action waypoint. It is rejected unless a title
    callback explicitly validates it for the current ownership scope; even then
    the caller's live Player 2 prompt handling owns execution.
    """
    def __init__(self, *, units_per_m, max_age=.75, title=None):
        if type(units_per_m) not in (int,float) or not math.isfinite(units_per_m) or units_per_m<=0 \
                or type(max_age) not in (int,float) or not .05<=max_age<=1.:
            raise ValueError('explicit navigation units and bounded proof freshness are required')
        if title is not None and (not isinstance(title,str) or not title):
            raise ValueError('expected title must be explicit when supplied')
        self.units_per_m, self.max_age, self.title = float(units_per_m),max_age,title
        self.reset()

    def reset(self):
        self.scope = None
        self.goal = None
        self.following = False
        self.retreating = False
        self.serial = 0
        self.route = []
        self.route_at = -math.inf
        self.constraints = None

    @staticmethod
    def _result(state, reason, **extra):
        return {'state':state,'reason':reason,'goal':None,'route':[],
                'protect_target':None,'threat_bias':{},**extra}

    def _ownership(self, snap, mesh, now, proof, session_id):
        if not isinstance(proof,dict) or not isinstance(session_id,str) or not session_id \
                or proof.get('session_id')!=session_id or snap.get('session_id',session_id)!=session_id:
            return None,'exact session ownership is unavailable'
        if mesh is None or proof.get('geometry')!=getattr(mesh,'learning_sig',None):
            return None,'current full navigation geometry is not owned by this proof'
        expected = self.title or snap.get('title')
        if expected and any(value is not None and value!=expected for value in (snap.get('title'),proof.get('title'))):
            return None,'native ownership belongs to another title'
        if type(now) not in (int,float) or not math.isfinite(now) or not _fresh(proof.get('observed_at'),now,self.max_age):
            return None,'native ownership observation is missing or stale'
        if any(proof.get(key) is not True for key in ('verified','controller2_verified','camera2_verified','prompt2_verified')) \
                or type(proof.get('control_player')) is not int or proof['control_player']!=2:
            return None,'Player 2 actor, controller, camera and prompt ownership are not all verified'
        players = snap.get('players')
        if not isinstance(players,list):
            return None,'separate recorded Player 1 and Player 2 identities are required'
        rows = [[p for p in players if isinstance(p,dict) and p.get('slot')==slot] for slot in (1,2)]
        if any(len(group)!=1 for group in rows):
            return None,'native participant identity is missing or ambiguous'
        human, bot = rows[0][0],rows[1][0]
        if human.get('id')!='p1' or bot.get('id')!='p2' or human.get('control')!='human' or bot.get('control')!='bot':
            return None,'explicit human Player 1 and bot Player 2 assignments are required'
        for row in (human,bot):
            provenance = row.get('provenance') or {}
            if provenance.get('native_actor_verified') is not True \
                    or provenance.get('control_source')!='operator_assignment_and_bot_input_fence':
                return None,'native participant and controller-assignment provenance is unavailable'
            if expected and provenance.get('title',expected)!=expected:
                return None,'native participant belongs to another title'
        p1,p2 = _actor(human),_actor(bot)
        primary = snap.get('player') or {}
        if p1 is None or p2 is None or p1==p2 or proof.get('p1_actor')!=p1 or proof.get('p2_actor')!=p2 \
                or _actor(primary)!=p2:
            return None,'the controlled snapshot must belong to the exact verified Player 2 actor'
        if not _alive(human) or not _alive(bot) or not _point(primary.get('pos')) \
                or math.dist(primary['pos'],bot['pos'])>.01*self.units_per_m:
            return None,'both native actors must be alive with consistent current positions'
        for key in ('hp','hp_max'):
            if primary.get(key) is not None and bot.get(key) is not None and primary[key]!=bot[key]:
                return None,'controlled actor health does not match the Player 2 participant'
        return (human,bot),'verified native Player 2 context'

    def _threats(self, snap, human, bot, now, exposures):
        proofs = {}
        for proof in exposures:
            if not isinstance(proof,dict) or proof.get('verified') is not True or proof.get('clear') is not True \
                    or proof.get('observer_actor')!=_actor(bot) or not _fresh(proof.get('observed_at'),now,self.max_age) \
                    or proof.get('source') not in ('native_first_hit','native_raycast','native_line_of_sight'):
                continue
            target = _actor({'actor':proof.get('target_actor')})
            if target is not None:
                proofs[target] = proof
        result = []
        for enemy in snap.get('enemies') or ():
            if not isinstance(enemy,dict) or not _alive(enemy) or _actor(enemy) in (_actor(human),_actor(bot)):
                continue
            identity = _actor(enemy)
            if identity is None or identity not in proofs:
                continue
            ally_distance = math.dist(human['pos'],enemy['pos'])
            self_distance = math.dist(bot['pos'],enemy['pos'])
            if ally_distance>12.*self.units_per_m:
                continue
            priority = .25+.75*(1.-ally_distance/(12.*self.units_per_m))
            result.append({'id':identity,'priority':priority,'distance_to_human':ally_distance,
                           'distance_to_bot':self_distance,'exposure':dict(proofs[identity])})
        result.sort(key=lambda row:(-row['priority'],row['distance_to_bot'],str(row['id'])))
        return result

    def _safe(self, mesh, start, route, hazards, ownership, traversal_check):
        previous = start
        for waypoint in route:
            approach = waypoint.approach if hasattr(waypoint,'approach') else waypoint
            if not _point(approach) or not mesh.floor_segment(previous,approach) \
                    or not mesh.hazard_segment_clear(previous,approach,hazards,departing=True):
                return False
            if hasattr(waypoint,'approach'):
                try:
                    allowed = callable(traversal_check) and traversal_check(waypoint,ownership) is True
                except Exception:
                    allowed = False
                if not allowed or not mesh.hazard_segment_clear(approach,waypoint,hazards,departing=True):
                    return False
            previous = waypoint
        return bool(route)

    def _route(self, mesh, start, goal, hazards, ownership, traversal_check, blocked_links, avoid, penalties):
        route = mesh.route(start,goal,avoid=avoid,blocked_links=blocked_links,link_penalties=penalties)
        if route and self._safe(mesh,start,route,hazards,ownership,traversal_check):
            return list(route)
        # A measured floor detour can adapt to current bombs/bodies. It must not
        # project an unreachable goal or synthesize a traversal action.
        alternative = getattr(mesh,'route_avoiding_hazards',None)
        if callable(alternative):
            route = alternative(start,goal,hazards,avoid=avoid,blocked_links=blocked_links,link_penalties=penalties)
            if route and self._safe(mesh,start,route,hazards,ownership,traversal_check):
                return list(route)
        return None

    def plan(self, snap, mesh, now, *, ownership, session_id, hazards=(), exposures=(),
             blocked_links=(), avoid=(), penalties=None, traversal_check=None):
        """Return measured movement and protection preferences, never controller events.

        Ownership timestamps and exposure timestamps use the caller's monotonic
        clock. Missing proof means unavailable; there is no Player 1 fallback.
        Explicit pause flags supplement the caller's higher-priority native
        QTE, healing and own-mine escape handling.
        """
        participants,reason = self._ownership(snap,mesh,now,ownership,session_id)
        if participants is None:
            self.reset()
            return self._result('unavailable',reason)
        human,bot = participants
        scope = (session_id,_actor(human),_actor(bot),mesh.learning_sig)
        if self.scope!=scope:
            self.reset();self.scope=scope
        blocked_links = tuple(blocked_links)
        avoid = tuple(avoid)
        constraints = (frozenset(blocked_links),tuple(tuple(point) for point in avoid))
        if constraints!=self.constraints:
            self.constraints,self.route_at = constraints,-math.inf
        provenance = {'session_id':session_id,'geometry':mesh.learning_sig,'p1_actor':_actor(human),
                      'p2_actor':_actor(bot),'observed_at':ownership['observed_at'],'units_per_m':self.units_per_m,
                      'title':self.title or snap.get('title'),
                      'movement':'current measured floor; title-owned action prompt handling',
                      'visibility':'explicit fresh native Player 2 exposure evidence only'}
        for key in ('mandatory_qte','recovery_active','healing','mine_escape','cooperation_pause'):
            if snap.get(key):
                return self._result('paused',key+' retains priority',provenance=provenance)
        maximum = bot.get('hp_max')
        if type(maximum) not in (int,float) or not math.isfinite(maximum) or maximum<=0:
            return self._result('paused','Player 2 health context is incomplete',provenance=provenance)
        if bot['hp']/maximum<=.4:
            return self._result('paused','Player 2 healing retains priority',provenance=provenance)
        if mesh.find(bot['pos'],floor_only=True,height_slack=.4*self.units_per_m) is None \
                or mesh.find(human['pos'],floor_only=True,height_slack=.4*self.units_per_m) is None:
            return self._result('blocked','both actors need measured current floor support',provenance=provenance)
        checked_hazards = []
        for hazard in hazards:
            if not isinstance(hazard,(tuple,list)) or len(hazard)!=2:
                return self._result('blocked','a current hazard has invalid geometry',provenance=provenance)
            centre,radius = hazard
            if not _point(centre) or type(radius) not in (int,float) or not math.isfinite(radius) or radius<=0:
                return self._result('blocked','a current hazard has invalid geometry',provenance=provenance)
            checked_hazards.append((tuple(centre),float(radius)))
        threats = self._threats(snap,human,bot,now,exposures)
        protect = threats[0]['id'] if threats else None
        extra = {'protect_target':protect,'threat_bias':{t['id']:t['priority'] for t in threats},
                 'threats':threats,'provenance':provenance,'human_hp':human['hp'],'human_hp_max':human.get('hp_max')}
        separation = math.dist(human['pos'],bot['pos'])
        same_area = mesh.floor_segment(bot['pos'],human['pos'])
        self.following = not same_area or separation>6.*self.units_per_m or self.following and separation>4.2*self.units_per_m
        self.retreating = separation<2.2*self.units_per_m or self.retreating and separation<3.*self.units_per_m
        if not self.following and not self.retreating:
            self.goal,self.route = None,[]
            return self._result('protect' if protect is not None else 'hold',
                'prefer exposed threats near the human' if protect is not None else 'within the human standoff band',**extra)
        collision_hazards = checked_hazards+[(tuple(human['pos']),1.6*self.units_per_m)]
        collision_hazards += [(tuple(e['pos']),1.4*self.units_per_m) for e in snap.get('enemies') or ()
                              if isinstance(e,dict) and _alive(e) and _actor(e) not in (_actor(human),_actor(bot))]
        if self.goal is not None:
            distance = math.dist(self.goal['pos'],human['pos'])
            if not 2.2*self.units_per_m<=distance<=5.2*self.units_per_m \
                    or math.dist(self.goal['human_pos'],human['pos'])>1.2*self.units_per_m \
                    or not mesh.floor_segment(human['pos'],self.goal['pos']):
                self.goal,self.route = None,[]
        if self.goal is None:
            dx,dz = bot['pos'][0]-human['pos'][0],bot['pos'][2]-human['pos'][2]
            facing = human.get('facing',human.get('rot',0.))
            facing = facing if type(facing) in (int,float) and math.isfinite(facing) else 0.
            angle = math.atan2(dx,dz) if math.hypot(dx,dz)>.01*self.units_per_m else facing+math.pi
            candidates = []
            for radius in (3.5*self.units_per_m,2.7*self.units_per_m):
                for turn in (0.,math.pi/4,-math.pi/4,math.pi/2,-math.pi/2,3*math.pi/4,-3*math.pi/4,math.pi):
                    point = (human['pos'][0]+math.sin(angle+turn)*radius,human['pos'][1],human['pos'][2]+math.cos(angle+turn)*radius)
                    node = mesh.find(point,floor_only=True,height_slack=.4*self.units_per_m)
                    if node is None:
                        continue
                    height = mesh._height(node,point[0],point[2]) if callable(getattr(mesh,'_height',None)) else point[1]
                    if height is None:
                        continue
                    point = (point[0],height,point[2])
                    if not mesh.floor_segment(human['pos'],point):
                        continue
                    if any(math.dist(point,c)<r for c,r in collision_hazards):
                        continue
                    route = self._route(mesh,bot['pos'],point,collision_hazards,ownership,traversal_check,blocked_links,avoid,penalties)
                    if not route:
                        continue
                    length = sum(math.dist(a,b) for a,b in zip([bot['pos']]+route,route))
                    if length>max(24.*self.units_per_m,2.5*math.dist(bot['pos'],point)):
                        continue
                    score = length+abs(radius-3.5*self.units_per_m)*.3
                    candidates.append((score,point,route))
            if not candidates:
                return self._result('protect' if protect is not None else 'blocked',
                    'no supported collision-free standoff route; no blind movement',**extra)
            _,point,route = min(candidates,key=lambda row:row[0])
            self.serial += 1
            self.goal = {'kind':'follow_human','id':f"cooperation:{session_id}:{_actor(human)}:{_actor(bot)}:{mesh.learning_sig}:{self.serial}",
                         'pos':point,'human_pos':tuple(human['pos'])}
            self.route,self.route_at = route,now
        if now-self.route_at>.5:
            route = self._route(mesh,bot['pos'],self.goal['pos'],collision_hazards,ownership,traversal_check,blocked_links,avoid,penalties)
            self.route,self.route_at = route or [],now
        route = list(self.route)
        while len(route)>1 and not hasattr(route[0],'approach') and math.dist(bot['pos'],route[0])<.6*self.units_per_m \
                and mesh.floor_segment(bot['pos'],route[1].approach if hasattr(route[1],'approach') else route[1]):
            route.pop(0)
        if not self._safe(mesh,bot['pos'],route,collision_hazards,ownership,traversal_check):
            self.goal,self.route = None,[]
            return self._result('protect' if protect is not None else 'blocked',
                'the current floor or hazard check invalidated the follow route',**extra)
        self.route = route
        return self._result('protect' if protect is not None else 'follow',
            'prefer exposed threats near the human' if protect is not None else 'follow on verified floor with standoff hysteresis',
            goal={k:v for k,v in self.goal.items() if k!='human_pos'},route=list(route),**extra)
