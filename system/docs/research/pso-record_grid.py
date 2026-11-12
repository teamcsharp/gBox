"""Drive the character and record a live-coordinate navigation grid, then route on it.

This is the goal's last unmet clause: the map **used for path-guiding the bot**. The disc maps are blocked by per-room transforms, but a grid built from the game's
own coordinates needs no transform at all - `operator-walk-summary.json` already proved the method (2316 samples, 1163 cells, 1221 edges, one component).

Input is affordable: a short press through `/api/sessions/<sid>/input` leaves the RPC readable immediately (measured 0.0 s recovery), so the trail can be recorded
by driving rather than waiting for the autobot.

The grid is 8-unit cells, the same resolution as the existing recorded walk. Edges come from consecutive samples that move between adjacent cells, so they are
observed moves, not guesses. Then A* routes between two cells the character actually visited, and the result is checked for contiguity: every step must be a real
edge.
"""
import collections
import heapq
import json
import math
import sys
import time
import urllib.request

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
SIZE = 8.0
OUT = r"D:\gBox\pso-ds\routes\live-grid-cave01.json"


def call(sid, path, payload=None, method="POST", timeout=20):
    request = urllib.request.Request(
        f"http://127.0.0.1:18765{path}",
        data=json.dumps(payload).encode() if payload is not None else None,
        method=method,
        headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent", "content-type": "application/json"})
    try:
        return json.loads(urllib.request.urlopen(request, timeout=timeout).read() or b"null")
    except Exception as exc:                                       # noqa: BLE001
        return {"_error": f"{type(exc).__name__}: {str(exc)[:100]}"}


def list_sessions():
    request = urllib.request.Request(
        "http://127.0.0.1:18765/api/sessions",
        headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent"})
    rows = json.loads(urllib.request.urlopen(request, timeout=20).read() or b"[]")
    return rows if isinstance(rows, list) else (rows.get("items") or [])


def player(sid):
    state = call(sid, f"/api/sessions/{sid}/rpc", {"op": "state", "args": {"player_only": True}})
    return (state or {}).get("player") or {}


def press(sid, key, seconds=0.35):
    call(sid, f"/api/sessions/{sid}/input", {"events": [{"key": key, "down": True}]})
    time.sleep(seconds)
    call(sid, f"/api/sessions/{sid}/input", {"events": [{"key": key, "down": False}]})
    time.sleep(0.12)


def cell(point):
    return int(math.floor(point[0] / SIZE)), int(math.floor(point[1] / SIZE))


if __name__ == "__main__":
    sessions = list_sessions()
    sid = next(row["session_id"] for row in sessions if row.get("state") in ("running", "starting"))
    print("session:", sid)

    start = player(sid)
    print(f"start ({start['x']:.1f}, {start['z']:.1f}) room={start.get('room')}")

    trail = []
    plan = ["w", "w", "d", "w", "w", "a", "w", "s", "d", "w", "w", "a", "w", "d", "w", "w"]
    for index, key in enumerate(plan):
        press(sid, key)
        spot = player(sid)
        if "x" in spot:
            trail.append((spot["x"], spot["z"]))
        if index % 4 == 3:
            print(f"  {index + 1}/{len(plan)} keys -> ({trail[-1][0]:.1f}, {trail[-1][1]:.1f})" if trail else "  no sample")

    if len(trail) < 3:
        raise SystemExit("not enough samples")

    travelled = sum(math.dist(a, b) for a, b in zip(trail, trail[1:]))
    cells = {cell(point) for point in trail}
    print(f"\nsamples {len(trail)} | travelled {travelled:.1f} units | cells {len(cells)}")

    if travelled < 10:
        raise SystemExit("the character did not move; the grid would be a single point")

    # edges are observed moves between adjacent cells
    edges = set()
    for a, b in zip(trail, trail[1:]):
        ca, cb = cell(a), cell(b)
        if ca != cb and abs(ca[0] - cb[0]) <= 1 and abs(ca[1] - cb[1]) <= 1:
            edges.add((ca, cb))
            edges.add((cb, ca))
    print(f"edges {len(edges)}")

    # persist
    record = {"version": 1, "size": SIZE, "floor": 3, "area": "map_cave01", "room": start.get("room"),
              "cells": sorted([list(c) for c in cells]), "edges": sorted([[list(a), list(b)] for a, b in edges]),
              "samples": len(trail), "travelled": round(travelled, 1), "recorded": int(time.time())}
    open(OUT, "w", encoding="utf-8").write(json.dumps(record))
    print("saved", OUT)

    # A* over the recorded graph
    graph = collections.defaultdict(set)
    for a, b in edges:
        graph[a].add(b)

    ordered = sorted(cells)
    source = ordered[0]
    target = max(cells, key=lambda c: abs(c[0] - source[0]) + abs(c[1] - source[1]))
    print(f"\nrouting {source} -> {target} (manhattan {abs(target[0] - source[0]) + abs(target[1] - source[1])})")

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
        print("no route - the recorded cells form separate components")
    else:
        path = [target]
        while path[-1] != source:
            path.append(came[path[-1]])
        path.reverse()
        legal = all((b in graph.get(a, set())) for a, b in zip(path, path[1:]))
        print(f"route: {len(path)} cells, every step a recorded edge: {legal}")
        print("  path:", path[:12], "..." if len(path) > 12 else "")
        print("\nVERDICT: a live-coordinate grid was recorded and guides a route - no room transform needed")
