"""Door-aware walkability: treat a doorway cell as passable, because at runtime the door opens.

The map audit found three Forest 2 rooms unreachable from room 0 through the walkable cell graph. The cause is structural: the collision mesh marks
doorway cells as walls, since the mesh is static, while at runtime a door opens when its room is cleared and the character walks straight through.

So the walkable set used for planning is the free cells **plus the doorway cells recorded in the room mesh**. That is not a cheat around geometry:
the doorways are exactly the cells the level's own data says connect two rooms, and the bot opens them by clearing the room, which is the game's own
rule.

After this the audit must show every room reachable, otherwise the mesh and the collision disagree somewhere else and that would be the next thing to
understand.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import nav_fast as NAV                                             # noqa: E402

ROUTES = Path(r"D:\gBox\pso-ds\routes")
CELL = 10.0


def doorway_cells(floor):
    """The cells the room mesh records as doorways, converted from world to cell space."""
    try:
        graph = json.loads((ROUTES / f"forest{floor}-rooms-mesh.json").read_text(encoding="utf-8"))
    except Exception:                                            # noqa: BLE001
        return set()
    cells = set()
    for door in graph.get("doors") or []:
        x, z = door.get("x"), door.get("z")
        if isinstance(x, (int, float)) and isinstance(z, (int, float)):
            # a doorway is wider than one cell, so include the surrounding cells too
            cx, cz = int(x // CELL), int(z // CELL)
            for dx in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    cells.add((cx + dx, cz + dz))
        centre = door.get("centre")
        if isinstance(centre, (list, tuple)) and len(centre) >= 2:
            cells.add((int(centre[0] // CELL), int(centre[1] // CELL)))
    return cells


def walkable(floor, with_doors=True):
    """Free cells, plus doorway cells when requested."""
    free = set(NAV.cells(floor))
    if with_doors:
        free |= doorway_cells(floor)
    return free


def reachable_from(free, start_cell):
    seen = {start_cell}
    frontier = [start_cell]
    while frontier:
        x, z = frontier.pop()
        for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
            neighbour = (x + dx, z + dz)
            if neighbour in free and neighbour not in seen:
                seen.add(neighbour)
                frontier.append(neighbour)
    return seen


if __name__ == "__main__":
    for floor in (1, 2):
        try:
            graph = json.loads((ROUTES / f"forest{floor}-rooms-mesh.json").read_text(encoding="utf-8"))
        except Exception:                                        # noqa: BLE001
            print(f"floor {floor}: no graph")
            continue
        rooms = graph.get("rooms") or []
        before = set(NAV.cells(floor))
        after = walkable(floor)
        print(f"floor {floor}: free cells {len(before)} -> {len(after)} with doorways "
              f"(+{len(after) - len(before)})")
        start = rooms[0]["centre"]
        start_cell = min(after, key=lambda c: (NAV.centre(c)[0] - start[0]) ** 2 + (NAV.centre(c)[1] - start[1]) ** 2)
        seen = reachable_from(after, start_cell)
        unreachable = []
        for room in rooms:
            cells = [(int(c[0] // CELL), int(c[1] // CELL)) for c in room.get("cell_list") or []]
            if not any(cell in seen for cell in cells):
                unreachable.append(room["room"])
        print(f"   reachable cells {len(seen)} | unreachable rooms {unreachable or 'none'}")
