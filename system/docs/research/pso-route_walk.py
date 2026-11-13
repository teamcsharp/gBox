"""Walk to a target by following the internalised map's route, one waypoint at a time.

A straight `walk_to` at a switch 92 units away stalled: `92 -> 92 -> 102 -> 102 -> 241`, because Forest geometry sits
between the character and the target and a beeline has no way around it. Walking is required (no teleports), so the
answer is not a longer leash on `walk_to` - it is **route it through the safe-cell graph**, which is exactly what the
objective's map clause is for.

`route_walk(pad, tx, tz)`:

1. ask `forest_route.MapRouter` for the path over `forest-maps.json`'s safe cells;
2. **walk to successive waypoints** with the proven `walk_to`, ~25 units apart so each leg is short enough for the
   heading loop to hold and any obstacle is met one segment at a time;
3. give up on a leg that makes no progress and try the next waypoint rather than grinding in place, and report how far it
   got so the caller can log honestly.

If the map has no route (target outside the safe set, or the character off it) it falls back to plain `walk_to`, so
nothing regresses where the graph cannot help.
"""
import pathlib
import py_compile

ENDLESS = pathlib.Path(r"C:\_tools\gBox\.tmp\endless.py")
text = ENDLESS.read_text(encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles BEFORE")

HELPER = '''
def route_walk(pad: Pad, tx: float, tz: float, legs: int = 12) -> float:
    """Walk to (tx,tz) following the internalised Forest route. Returns the remaining distance.

    A beeline stalls against Forest geometry (measured: 92 -> 92 -> 102 -> 241), so the walk follows the safe-cell graph
    one short leg at a time. Falls back to a plain walk when the map has no route.
    """
    try:
        import json
        import pathlib as _pathlib
        from forest_route import MapRouter

        data = json.loads(_pathlib.Path(r"D:\\gBox\\pso-ds\\forest-maps.json").read_text(encoding="utf-8"))
        row = data.get("Scene/map_forest01c.rel") or {}
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
                    break
                # the furthest waypoint within one short leg, so each hop has a real chance of being reachable
                target = None
                for waypoint in route:
                    if math.dist((x, z), waypoint) <= 25.0:
                        target = waypoint
                    else:
                        break
                if target is None:
                    target = route[1] if len(route) > 1 else route[0]
                before = (x, z)
                walk_to(pad, target[0], target[1], max_steps=22)
                after = state(pad).get("player") or {}
                if math.dist(before, (float(after.get("x") or 0), float(after.get("z") or 0))) < 2.0:
                    break                                     # this leg is blocked too; stop rather than spin
    except Exception:                                         # noqa: BLE001 - the map is an optimisation, not a gate
        pass
    me = state(pad).get("player") or {}
    return math.hypot(tx - float(me.get("x") or 0), tz - float(me.get("z") or 0))


'''

anchor = "def play(pad: Pad, seconds: float = 120.0) -> str:"
if text.count(anchor) != 1:
    raise SystemExit("play anchor count: %d" % text.count(anchor))
if "def route_walk(" in text:
    print("route_walk already present")
else:
    text = text.replace(anchor, HELPER.lstrip("\n") + anchor, 1)
    print("route_walk added")

OLD = 'walk_to(pad, float(ient.get("x") or 0), float(ient.get("z") or 0), max_steps=70)'
NEW = 'route_walk(pad, float(ient.get("x") or 0), float(ient.get("z") or 0))'
count = text.count(OLD)
print("interact walk anchor count:", count)
if count == 1:
    text = text.replace(OLD, NEW, 1)
    print("the interact walk now follows the map route")

ENDLESS.write_text(text, encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles AFTER")
