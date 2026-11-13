"""Use whichever Forest map actually fits, instead of always forest01c.

The two maps in `forest-maps.json` **both contain the player's coordinates**:

```
Scene/map_forest01c.rel   90,986 cells   x -244..251  z -243..239   player inside: True
Scene/map_forest02c.rel   98,671 cells   x -262..246  z -251..232   player inside: True
```

and the doors in the current room resolve on **different** maps - one door gets a 40-waypoint route on forest01c, another
a 75-waypoint route on forest02c - so a single hardcoded name is wrong for some targets no matter which one is chosen.

`route_walk` now builds a router for every map in the file and takes the **shortest route that exists**. A wrong map
usually returns nothing at all (its cells do not connect the two points); when both return one, the shorter is the better
guess. The map name is available for logging so the choice is visible rather than implicit.
"""
import pathlib
import py_compile

ENDLESS = pathlib.Path(r"C:\_tools\gBox\.tmp\endless.py")
text = ENDLESS.read_text(encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles BEFORE")

OLD = '''        row = data.get("Scene/map_forest01c.rel") or {}
        cells = row.get("cells") or []
        if cells:
            router = MapRouter(cells)
            for _ in range(legs):
                me = state(pad).get("player") or {}
                x, z = float(me.get("x") or 0), float(me.get("z") or 0)
                remaining = math.hypot(tx - x, tz - z)
                if remaining <= 25.0:
                    return remaining
                route = router.route((x, z), (tx, tz), limit=400000)
                if not route:
                    break'''

NEW = '''        # BOTH Forest maps contain the player's coordinates, and different doors resolve on different maps, so build a
        # router for each and take the shortest route that exists rather than trusting one hardcoded name.
        routers = []
        for _name, _row in data.items():
            _cells = (_row or {}).get("cells") or []
            if _cells:
                routers.append((_name, MapRouter(_cells)))
        if routers:
            for _ in range(legs):
                me = state(pad).get("player") or {}
                x, z = float(me.get("x") or 0), float(me.get("z") or 0)
                remaining = math.hypot(tx - x, tz - z)
                if remaining <= 25.0:
                    return remaining
                route = None
                for _name, _router in routers:
                    try:
                        candidate = _router.route((x, z), (tx, tz), limit=400000)
                    except Exception:                     # noqa: BLE001 - one bad map must not stop the walk
                        candidate = None
                    if candidate and (route is None or len(candidate) < len(route)):
                        route = candidate
                if not route:
                    break'''

count = text.count(OLD)
print("anchor count:", count)
if count != 1:
    raise SystemExit("route_walk map selection not unique - refusing to guess")
text = text.replace(OLD, NEW, 1)
print("route_walk now tries every map and takes the shortest route")

ENDLESS.write_text(text, encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles AFTER")
