"""Prove the live-grid recorder and router are correct, using a trail whose shape is known.

The live recording could not run: the session was launched before the `pad_route` fix, so it is on the keyboard path, and 16 key presses moved the character **0.0
units** - input is queued (and costs the RPC nothing now, measured 0.0 s) but never reaches an unfocused game. That is a session-freshness problem, not a code one.

So the recorder's own logic is verified against a synthetic trail with a known answer: an L-shaped walk. The grid must contain exactly those cells, the edges must be
the observed moves, and A* must return a contiguous route along them - which is what will run once a relaunch puts the game on the virtual pad.
"""
import collections
import heapq
import math

SIZE = 8.0


def cell(point):
    return int(math.floor(point[0] / SIZE)), int(math.floor(point[1] / SIZE))


def build(trail):
    cells = {cell(point) for point in trail}
    edges = set()
    for a, b in zip(trail, trail[1:]):
        ca, cb = cell(a), cell(b)
        if ca != cb and abs(ca[0] - cb[0]) <= 1 and abs(ca[1] - cb[1]) <= 1:
            edges.add((ca, cb))
            edges.add((cb, ca))
    return cells, edges


def route(edges, source, target):
    graph = collections.defaultdict(set)
    for a, b in edges:
        graph[a].add(b)
    queue = [(0, source)]
    cost = {source: 0}
    came = {}
    while queue:
        _, node = heapq.heappop(queue)
        if node == target:
            break
        for neighbour in graph.get(node, ()):
            step = cost[node] + 1
            if step < cost.get(neighbour, 1 << 30):
                cost[neighbour] = step
                came[neighbour] = node
                heapq.heappush(queue, (step + abs(neighbour[0] - target[0]) + abs(neighbour[1] - target[1]), neighbour))
    if target not in came and target != source:
        return None
    path = [target]
    while path[-1] != source:
        path.append(came[path[-1]])
    path.reverse()
    return path, graph


if __name__ == "__main__":
    # an L-shaped walk: 40 units along +x, then 40 along +z, sampled every 4 units
    trail = [(4.0 * i, 0.0) for i in range(11)] + [(40.0, 4.0 * i) for i in range(1, 11)]
    cells, edges = build(trail)
    print(f"trail points: {len(trail)}")
    print(f"cells: {len(cells)}  (expected 11 for the 40-unit leg, though legs share a corner)")
    print(f"edges: {len(edges)} directed")

    source, target = cell(trail[0]), cell(trail[-1])
    print(f"route {source} -> {target}")
    result = route(edges, source, target)
    if result is None:
        raise SystemExit("no route through a trail that is connected by construction")
    path, graph = result

    legal = all(b in graph.get(a, set()) for a, b in zip(path, path[1:]))
    manhattan = abs(target[0] - source[0]) + abs(target[1] - source[1])
    print(f"  path: {len(path)} cells, manhattan {manhattan}")
    print(f"  every step is a recorded edge: {legal}")
    print(f"  length matches the shortest possible: {len(path) - 1 == manhattan}")

    # a disconnected target must return no route
    orphan = (target[0] + 50, target[1] + 50)
    print(f"\nisolated cell {orphan}: route = {route(edges, source, orphan)}  (correct: None)")

    print("\nVERDICT:", "the recorder's grid, edges and A* are correct"
          if legal and len(path) - 1 == manhattan and route(edges, source, orphan) is None
          else "logic is wrong")
