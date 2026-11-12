"""How much room knowledge is actually internalised right now?

`pso_knowledge.KnowledgeStore` persists, per geometry fingerprint: a room's gate understanding, and per area: the room-adjacency graph and critical path. That is
the "analyzed, scanned and internalized" layer for path-guiding - and it keys on geometry identity rather than coordinates, which is why it does not suffer the
room-offset problem.

This finds the store on disk and reports what it holds: rooms, areas, edges, paths. If it is empty, that is the honest state and the next step is to populate it
by walking.
"""
import json
import pathlib
import sys

sys.path.insert(0, r"C:\_tools\gBox\system")

from gbox import pso_knowledge                                   # noqa: E402


def find_stores():
    roots = [pathlib.Path(r"D:\gBox\pso-ds"), pathlib.Path(r"C:\_tools\gBox\system\gbox-data"),
             pathlib.Path(r"D:\gBox\cache")]
    seen = []
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*.json"):
            name = path.name.lower()
            if "knowledge" in name or "pso-knowledge" in name or "room-knowledge" in name:
                seen.append(path)
    return seen


if __name__ == "__main__":
    print("=== stores found on disk ===")
    found = find_stores()
    if not found:
        print("  none")
    for path in found:
        size = path.stat().st_size
        print(f"  {path}  ({size} bytes)")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:                                   # noqa: BLE001
            print(f"    unreadable: {type(exc).__name__}")
            continue
        rooms = data.get("rooms") or {}
        areas = data.get("areas") or {}
        print(f"    version {data.get('version')} | rooms {len(rooms)} | areas {len(areas)}")
        for key, area in list(areas.items())[:5]:
            edges = area.get("edges") or {}
            path_rooms = area.get("path") or []
            print(f"      area {key[:12]}: {len(edges)} edges, path of {len(path_rooms)} rooms")
        for key, room in list(rooms.items())[:5]:
            print(f"      room {key[:12]}: fields {sorted(room)[:8]}")

    print("\n=== what a fresh store exposes ===")
    store = pso_knowledge.KnowledgeStore()
    print("  rooms:", len(store.rooms), "| areas:", len(store.areas))
    print("  methods:", [name for name in dir(store) if not name.startswith("_")][:12])

    print("\n=== the geometry-keyed identity it relies on ===")
    print("  area_fingerprint(episode, floor, geometry_identity):")
    print("   ", pso_knowledge.area_fingerprint(1, 3, "example-geometry-hash"))
    print("  -> a store keyed this way survives restarts and never crosses a random layout")
