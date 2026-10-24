"""Optional measured-floor suggestions; the title planner still owns goals and hazards."""
import math
import threading


class Guidance:
    def __init__(self, data_dir, title):
        self.data_dir, self.title = data_dir,title
        self.at, self.geometry, self.rows = -math.inf,None,[]
        self.refreshing = False
        self.last_error = None
        self.lock = threading.Lock()
        self.practice_state = None

    def reset_practice(self):
        """A confirmed new round/actor may start the selected demonstration again."""
        self.practice_state = None

    def practice(self, mesh, position, now, *, mode=None, selected_route_id=None, hazards=(),
                 blocked_links=(), avoid=(), penalties=None):
        """An explicit human-route goal sequence, advanced only by measured arrivals.

        The caller keeps combat, healing, prompts and input ownership above this
        optional objective. No input/timing playback and no inferred checkpoint acquisition.
        """
        if mesh is None or not mode or not selected_route_id:
            self.practice_state = None
            return None
        scope = (selected_route_id,mode,mesh.learning_sig)
        if self.practice_state is not None and self.practice_state['scope']!=scope:
            self.practice_state = None
        self._refresh(mesh,now)
        row = next((r for r in self.rows if r.get('id')==selected_route_id
                    and r.get('kind')=='recorded_demonstration' and r.get('adopted')
                    and r.get('bot_eligible') and r.get('mode')==mode and r.get('title')==self.title
                    and r.get('geometry')==mesh.learning_sig and (r.get('source') or {}).get('control')=='human'), None)
        if row is None:
            return None
        from .reviewer import _point, traversal_allowed
        points = row.get('points') or []
        if not 2<=len(points)<=4096 or not all(_point(p) for p in points) or not _point(position):
            return None
        state = self.practice_state
        if state is None or state['scope']!=scope:
            state = self.practice_state = {'scope':scope,'index':0,'started':now}
        # A combat interruption does not reset the checkpoint to whichever point
        # happens to be nearest when movement resumes.
        while state['index']<len(points):
            target = points[state['index']]
            node = mesh.find(position,floor_only=True,height_slack=40.)
            if node is None or node!=mesh.find(target,floor_only=True,height_slack=40.) \
                    or math.dist(position,target)>60.:
                break
            state['index'] += 1
        out = {'suggestion_id':row['id'],'index':state['index'],'point_count':len(points),
               'source':row['source'],'assistance':row.get('assistance'),
               'id':'demonstration:'+row['id']+':'+str(state['index'])}
        if state['index']>=len(points):
            return {**out,'status':'completed','route':[],'pos':None}
        target = tuple(points[state['index']])
        route = mesh.route(position,target,avoid=avoid,blocked_links=blocked_links,link_penalties=penalties)
        previous = position
        safe = bool(route)
        for waypoint in route or []:
            approach = waypoint.approach if hasattr(waypoint,'approach') else waypoint
            if not mesh.floor_segment(previous,approach) or not mesh.hazard_segment_clear(previous,approach,hazards):
                safe = False;break
            if hasattr(waypoint,'approach') and (not traversal_allowed(mesh,waypoint,row.get('traversals') or [])
                    or not mesh.hazard_segment_clear(approach,waypoint,hazards)):
                safe = False;break
            previous = waypoint
        return {**out,'status':'approach' if state['index']==0 and safe else 'practice' if safe else 'blocked',
                'pos':target,'route':route if safe else []}

    def _refresh(self, mesh, now):
        """Annotations may be locked or expensive; movement never waits on them."""
        signature = mesh.learning_sig
        with self.lock:
            if self.geometry != signature:
                self.geometry, self.rows, self.at = signature, [], -math.inf
            if self.refreshing or now-self.at < 5.:
                return
            self.refreshing, self.at = True, now

        def read():
            error, rows = None, []
            try:
                from .reviewer import validated_suggestions
                rows = validated_suggestions(self.data_dir,self.title,mesh)
            except Exception as exc:
                # Optional persisted annotations cannot interrupt the title's
                # validated baseline route, including malformed saved payloads.
                error = type(exc).__name__
            finally:
                with self.lock:
                    if self.geometry == signature:
                        self.rows, self.last_error = rows, error
                    self.refreshing = False

        threading.Thread(target=read, name='mercs-route-guidance', daemon=True).start()

    def route(self, mesh, start, goal, baseline, now, *, hazards=(), blocked_links=(), avoid=(), penalties=None,
              mode=None, selected_route_id=None):
        if mesh is None or not baseline:
            return None
        self._refresh(mesh, now)
        rows = [row for row in self.rows if not selected_route_id or row.get('id')==selected_route_id]
        for row in rows[:3]:
            demonstration = row.get('kind')=='recorded_demonstration'
            if demonstration and (not row.get('adopted') or not mode or row.get('mode')!=mode
                    or row.get('geometry')!=mesh.learning_sig or row.get('title')!=self.title
                    or (row.get('source') or {}).get('control')!='human'):
                continue
            from .reviewer import demonstrated_segment, traversal_allowed
            proofs = row.get('traversals') or [] if demonstration else []
            points = row['points']
            first = min(range(len(points)),key=lambda i:math.dist(start,points[i]))
            if first >= len(points)-1 or math.dist(start,points[first]) > 300.:
                continue
            last = min(range(first+1,len(points)),key=lambda i:math.dist(goal,points[i]))
            if math.dist(goal,points[last]) > 300.:
                continue
            chain = [tuple(start),*map(tuple,points[first:last+1]),tuple(goal)]
            if len(chain)>34:
                if demonstration:
                    # A long selected recording is not a controller replay. Use only
                    # a local, applicable goal segment without deleting its corners.
                    continue
                chain = [chain[round(i*(len(chain)-1)/33)] for i in range(34)]
            # An annotation never licenses a wall crossing, a different floor,
            # an action link, a mine margin or a known blocked portal.
            if not all((demonstrated_segment(mesh,a,b,proofs) if demonstration else mesh.floor_segment(a,b))
                       and mesh.hazard_segment_clear(a,b,hazards)
                       for a,b in zip(chain,chain[1:])):
                continue
            route = []
            for a,b in zip(chain,chain[1:]):
                if math.dist(a,b) < 1.:
                    continue
                part = mesh.route(a,b,avoid=avoid,blocked_links=blocked_links,link_penalties=penalties)
                if not part or any(hasattr(p,'approach') and not (demonstration and traversal_allowed(mesh,p,proofs)) for p in part):
                    break
                if not all((mesh.floor_segment(u,v.approach) and mesh.hazard_segment_clear(u,v.approach,hazards)
                            and mesh.hazard_segment_clear(v.approach,v,hazards) if hasattr(v,'approach') else
                            mesh.floor_segment(u,v) and mesh.hazard_segment_clear(u,v,hazards))
                           for u,v in zip([a]+part,part)):
                    break
                route.extend(part)
            else:
                if route:
                    return {'route':route,'suggestion_id':row['id'],
                            'demonstration_source':row.get('source') if demonstration else None,
                            'assistance':row.get('assistance') if demonstration else None,
                            'provenance':'recorded human route revalidated; live action prompts remain required' if demonstration else
                                         'operator suggestion revalidated against current floor and hazards'}
        return None
