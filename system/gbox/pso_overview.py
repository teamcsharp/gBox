"""2D overview of a PSO area built from the knowledge crystal.

Pure: reads a KnowledgeStore (room-adjacency edges, critical path, per-room
forced-gate records) and returns (a) a JSON-able overview - rooms with their
grid position, the doors between them, the switch/stage flags that gate each
room's forward door, the shortest route start->exit and the best known time -
and (b) an SVG drawing. Positions are a BFS layering of the observed door graph
(schematic, not world coordinates); nothing here touches the game.
"""
from __future__ import annotations

from collections import deque
from html import escape

SCHEMA = "gbox.pso.area-overview/1"


def shortest_route(edges, start, goal):
    """Fewest-door route start->goal over directed {room:{door:to}} edges."""
    if start == goal:
        return [start]
    prev, queue = {start: None}, deque([start])
    while queue:
        room = queue.popleft()
        for to in sorted(set((edges.get(room) or {}).values())):
            if to in prev:
                continue
            prev[to] = room
            if to == goal:
                out = [to]
                while prev[out[-1]] is not None:
                    out.append(prev[out[-1]])
                return out[::-1]
            queue.append(to)
    return []


def build_overview(store, area, *, floor=None, episode=None):
    edges = store.area_edges(area)
    rooms = set(edges)
    for doors in edges.values():
        rooms.update(doors.values())
    path = store.critical_path(area)
    rooms.update(path)
    start = path[0] if path else (min(rooms) if rooms else None)
    goal = path[-1] if path else None
    # BFS layers from the start give each room a (column, row) cell.
    layer = {}
    if start is not None:
        layer[start] = 0
        queue = deque([start])
        while queue:
            room = queue.popleft()
            for to in sorted(set((edges.get(room) or {}).values())):
                if to not in layer:
                    layer[to] = layer[room] + 1
                    queue.append(to)
    for room in sorted(rooms - set(layer)):      # unreachable from start: own column
        layer[room] = max(layer.values(), default=-1) + 1
    gates = {}
    for rec in store.rooms.values():
        if rec.get("gate") != "forced_flags" or type(rec.get("room")) is not int:
            continue
        if rec["room"] not in rooms or (floor is not None and rec.get("floor") != floor) \
                or (episode is not None and rec.get("episode") != episode):
            continue
        flags = [f for f in rec.get("forward_flags", []) if type(f) is int]
        gates.setdefault(rec["room"], set()).update(flags)
    rows, nodes = {}, []
    for room in sorted(rooms, key=lambda r: (layer[r], r)):
        row = rows[layer[room]] = rows.get(layer[room], -1) + 1
        nodes.append({"room": room, "col": layer[room], "row": row,
                      "gate_flags": sorted(gates.get(room, ())),
                      "on_route": room in path})
    doors = [{"from": fr, "door": door, "to": to}
             for fr in sorted(edges) for door, to in sorted(edges[fr].items())]
    rec = store.areas.get(area) or {}
    return {"schema": SCHEMA, "area": area, "start": start, "exit": goal,
            "route": shortest_route(edges, start, goal) if goal is not None else [],
            "critical_path": path, "rooms": nodes, "doors": doors,
            "best_s": rec.get("best_s"), "runs": rec.get("runs", 0)}


def render_svg(overview, *, cell=96):
    pos = {n["room"]: (30 + n["col"] * cell, 30 + n["row"] * cell) for n in overview["rooms"]}
    w = max((x for x, _ in pos.values()), default=0) + cell
    h = max((y for _, y in pos.values()), default=0) + cell
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
           f'viewBox="0 0 {w} {h}" role="img" aria-label="area overview">']
    for d in overview["doors"]:
        if d["from"] in pos and d["to"] in pos:
            (x1, y1), (x2, y2) = pos[d["from"]], pos[d["to"]]
            out.append(f'<line x1="{x1+30}" y1="{y1+15}" x2="{x2+30}" y2="{y2+15}" '
                       f'stroke="#888"><title>{escape(str(d["door"]))}</title></line>')
    for n in overview["rooms"]:
        x, y = pos[n["room"]]
        fill = "#cfe8cf" if n["on_route"] else "#eee"
        label = f'room {n["room"]}' + (f' flags {",".join(map(str, n["gate_flags"]))}' if n["gate_flags"] else "")
        out.append(f'<rect x="{x}" y="{y}" width="60" height="30" fill="{fill}" stroke="#333"/>'
                   f'<text x="{x+30}" y="{y+19}" font-size="9" text-anchor="middle">{escape(label)}</text>')
    out.append("</svg>")
    return "".join(out)
