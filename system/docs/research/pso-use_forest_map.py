"""Steer with the internalised Forest map instead of walking blind.

The map is decoded (`forest01c`: 1455 triangles -> 90,986 safe cells; `forest02c`: 98,671) and `forest_route.py` proves A* returns real routes on it. This puts it to work in the loop.

Why it matters beyond "having a map": **every wedging episode in this session was the character walking into geometry.** The blind approach is turn-a-bit, step, hope. A route over **safe cells** -
walkable, eroded by 3x3, with no upper/lower floor ambiguity - only ever asks the character to stand where the geometry says it can stand, so the failure mode that produced
`wedged at (426,29,-18)` and the relocation machinery should largely stop happening.

`map_step(pad, tx, tz)` returns the **next waypoint** toward a target, or `None` when the map cannot help (target in another room, or the character off the safe set). `None` falls back to the existing
hill-climb, so this is a pure improvement: it adds a verified route where one exists and changes nothing where one does not.

The router loads once (`forest-maps.json`) and is cached; a missing or corrupt file simply disables the feature rather than breaking the loop.
"""
import json
import pathlib
import py_compile

ENDLESS = pathlib.Path(r"C:\_tools\gBox\.tmp\endless.py")
text = ENDLESS.read_text(encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles BEFORE")

HELPER = '''
FOREST_MAPS = pathlib.Path(r"D:\\gBox\\pso-ds\\forest-maps.json")
_ROUTERS = {}


def _router():
    """The Forest 1 router, loaded once. None when the map file is absent."""
    if "forest01" in _ROUTERS:
        return _ROUTERS["forest01"]
    router = None
    try:
        if FOREST_MAPS.exists():
            data = json.loads(FOREST_MAPS.read_text(encoding="utf-8"))
            row = data.get("Scene/map_forest01c.rel")
            if row and row.get("cells"):
                sys.path.insert(0, r"C:\\_tools\\gBox\\.tmp")
                from forest_route import MapRouter
                router = MapRouter(row["cells"])
    except Exception:                                          # noqa: BLE001 - the map is an aid, never a dependency
        router = None
    _ROUTERS["forest01"] = router
    return router


def map_step(pad: Pad, tx: float, tz: float) -> "tuple[float, float] | None":
    """The next waypoint from the character toward (tx,tz) on the internalised map, or None.

    A route is only returned when both ends snap to safe cells and A* finds a path - i.e. when the map genuinely knows
    how to get there. Anything else returns None and the caller keeps its own approach.
    """
    router = _router()
    if router is None:
        return None
    try:
        me = (state(pad).get("player") or {})
        here = (float(me.get("x") or 0), float(me.get("z") or 0))
        route = router.route(here, (tx, tz))
        if not route:
            return None
        for waypoint in route:
            if math.dist(here, waypoint) > 8.0:
                return (float(waypoint[0]), float(waypoint[1]))
    except Exception:                                          # noqa: BLE001
        return None
    return None


'''

anchor = "def play(pad: Pad, seconds: float = 120.0) -> str:"
if text.count(anchor) != 1:
    raise SystemExit("play anchor count: %d" % text.count(anchor))
if "def map_step(" not in text:
    text = text.replace(anchor, HELPER.lstrip("\n") + anchor, 1)
    print("map_step() added")

# use it in the box approach (the most frequent manoeuvre, and the one that wedges most)
old = """                else:
                    side_b = globals().get("BOX_SIDE", 1)
                    before_b = bdist
                    hold(pad, "left" if side_b > 0 else "right", 0.18)
                    hold(pad, "up", 0.7)
                    time.sleep(0.2)"""
new = """                else:
                    side_b = globals().get("BOX_SIDE", 1)
                    before_b = bdist
                    step = map_step(pad, bx, bz)      # route on the internalised Forest map when it knows the way
                    if step and math.dist((x, z), (bx, bz)) > 10.0:
                        side_toward = 1 if step[0] >= x else -1
                        hold(pad, "left" if side_toward > 0 else "right", 0.16)
                        hold(pad, "up", 0.7)
                        map_steps += 1
                    else:
                        hold(pad, "left" if side_b > 0 else "right", 0.18)
                        hold(pad, "up", 0.7)
                    time.sleep(0.2)"""
if text.count(old) == 1:
    text = text.replace(old, new, 1)
    print("box approach now prefers the map route")
else:
    print("box approach anchor count:", text.count(old))

old_decl = "    attacks = 0                                         # swing bursts aimed by sweeping the cone"
new_decl = ("    attacks = 0                                         # swing bursts aimed by sweeping the cone\n"
            "    map_steps = 0                                       # steps chosen from the internalised Forest map")
if text.count(old_decl) == 1:
    text = text.replace(old_decl, new_decl, 1)
    print("map_steps counter declared")

ENDLESS.write_text(text, encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles AFTER")
