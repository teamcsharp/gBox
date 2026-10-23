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

    def route(self, mesh, start, goal, baseline, now, *, hazards=(), blocked_links=(), avoid=(), penalties=None):
        if mesh is None or not baseline:
            return None
        self._refresh(mesh, now)
        for row in self.rows[:3]:
            points = row['points']
            first = min(range(len(points)),key=lambda i:math.dist(start,points[i]))
            if first >= len(points)-1 or math.dist(start,points[first]) > 300.:
                continue
            last = min(range(first+1,len(points)),key=lambda i:math.dist(goal,points[i]))
            if math.dist(goal,points[last]) > 300.:
                continue
            chain = [tuple(start),*map(tuple,points[first:last+1]),tuple(goal)]
            if len(chain)>34:
                chain = [chain[round(i*(len(chain)-1)/33)] for i in range(34)]
            # An annotation never licenses a wall crossing, a different floor,
            # an action link, a mine margin or a known blocked portal.
            if not all(mesh.floor_segment(a,b) and mesh.hazard_segment_clear(a,b,hazards)
                       for a,b in zip(chain,chain[1:])):
                continue
            route = []
            for a,b in zip(chain,chain[1:]):
                if math.dist(a,b) < 1.:
                    continue
                part = mesh.route(a,b,avoid=avoid,blocked_links=blocked_links,link_penalties=penalties)
                if not part or any(hasattr(p,'approach') for p in part):
                    break
                if not all(mesh.floor_segment(u,v) and mesh.hazard_segment_clear(u,v,hazards)
                           for u,v in zip([a]+part,part)):
                    break
                route.extend(part)
            else:
                if route:
                    return {'route':route,'suggestion_id':row['id'],
                            'provenance':'operator suggestion revalidated against current floor and hazards'}
        return None
