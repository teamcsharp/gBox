"""Patch map_bot to walk each route waypoint with the empirical steer controller.

pso_kbwalk.walk_path drifted (ordered (-40,240) it walked away from it). steer.step_toward measures each direction immediately before
striding and arrived within 7 units on a 123-unit leg in 5 steps, so every waypoint is now walked that way and an unreachable waypoint is
skipped rather than orbited.
"""
import pathlib

PATH = pathlib.Path(r"C:\_tools\gBox\.tmp\map_bot.py")
text = PATH.read_text(encoding="utf-8")

OLD = '''        path = route((me[0], me[2]), target)
        if not path:
            log("no flat route to the order; waiting")
            time.sleep(1.0)
            continue
        try:
            pso_kbwalk.walk_path(lambda: (player()[0], player()[2]), hold, [tuple(w) for w in path[:4]], tolerance=8.0)
        except RuntimeError as exc:
            log(f"walk_path: {exc}")'''

NEW = '''        path = route((me[0], me[2]), target)
        if not path:
            log("no flat route to the order; waiting")
            time.sleep(1.0)
            continue
        # walk the waypoints with the empirical controller, which cannot go stale like a calibration table
        import steer

        def read_xz():
            point = player()
            return (point[0], point[2]) if point else None

        reached_all = True
        for waypoint in path[1:5]:
            arrived, steps, final, reason = steer.step_toward(
                hold, read_xz, (waypoint[0], waypoint[1]), tolerance=9.0, max_steps=8, log=log)
            if not arrived and reason == "step limit":
                log(f"  waypoint {tuple(round(v) for v in waypoint)} not reached ({final:.0f} units)")
                reached_all = False
                continue
        if not reached_all:
            log("  some waypoints unreachable; re-planning next round")'''

assert text.count(OLD) == 1, text.count(OLD)
PATH.write_text(text.replace(OLD, NEW), encoding="utf-8")
print("map_bot now steers per waypoint")
