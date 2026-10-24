"""Bounded local detours around measured blocked approaches, not invented walls.

Title adapters supply floor projection, directed segment support and hazard
clearance. A stationary actor alone cannot identify a physical collision object.
"""
import heapq
import math


def clear_segment(a, b, obstacles):
    dx, dz = b[0]-a[0], b[2]-a[2]
    length = dx*dx+dz*dz
    for row in obstacles:
        p = row['pos']
        if abs(p[1]-a[1]) > 100. or abs(p[1]-b[1]) > 100.:
            continue
        t = max(0., min(1., ((p[0]-a[0])*dx+(p[2]-a[2])*dz)/length)) if length else 0.
        if math.hypot(a[0]+t*dx-p[0], a[2]+t*dz-p[2]) < row['radius']:
            return False
    return True


def detour(start, goal, obstacles, *, project, supported, hazard_clear=lambda a,b:True,
           cell=80., radius=480., max_nodes=128):
    """A small A* grid, checked against actual title floors on every step.

    No route is returned through a gap, a blocked directed portal or a hazard.
    A distant goal gets a local waypoint; the title's main planner retains it.
    """
    if abs(goal[1]-start[1]) > 60. or not supported(start,start):
        return None
    span = max(1, min(8, int(radius/cell)))
    dx,dz = goal[0]-start[0],goal[2]-start[2]
    distance = math.hypot(dx,dz)
    scale = min(1., radius*.7/max(1.,distance))
    target = project((start[0]+dx*scale,start[1],start[2]+dz*scale))
    if target is None or not clear_segment(target,target,obstacles):
        return None
    positions = {(0,0):tuple(start)}
    costs, parents = {(0,0):0.}, {}
    queue = [(math.dist(start,target),0.,(0,0))]
    end = None
    while queue and max_nodes > 0:
        _,cost,node = heapq.heappop(queue)
        if cost != costs[node]:
            continue
        max_nodes -= 1
        point = positions[node]
        if math.dist(point,target) <= cell*1.5 and clear_segment(point,target,obstacles) \
                and supported(point,target) and hazard_clear(point,target):
            end = node
            break
        for ox,oz in ((0,1),(0,-1),(1,0),(-1,0),(1,1),(1,-1),(-1,1),(-1,-1)):
            nxt = (node[0]+ox,node[1]+oz)
            if max(abs(nxt[0]),abs(nxt[1])) > span:
                continue
            if nxt not in positions:
                positions[nxt] = project((start[0]+nxt[0]*cell,start[1],start[2]+nxt[1]*cell))
            q = positions[nxt]
            if q is None or not clear_segment(point,q,obstacles) or not supported(point,q) or not hazard_clear(point,q):
                continue
            value = cost+math.dist(point,q)
            if value < costs.get(nxt,math.inf):
                costs[nxt],parents[nxt] = value,node
                heapq.heappush(queue,(value+math.dist(q,target),value,nxt))
    if end is None:
        return None
    route = [target]
    while end != (0,0):
        route.append(positions[end]);end=parents[end]
    route.reverse()
    return route
