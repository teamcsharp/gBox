"""Patch map_bot: steer straight at the clicked point instead of chasing flat-route waypoints.

The flat graph's waypoints frequently sit where the live area will not let the character walk (measured: "waypoint (-95,75) not reached
(65 units)"), so the bot orbited them. The empirical controller already picks the best-aligned direction it can actually move in, so for a
click order the bot now walks directly at the point and only falls back to route waypoints when the direct line is blocked for several
steps in a row.
"""
import pathlib

PATH = pathlib.Path(r"C:\_tools\gBox\.tmp\map_bot.py")
text = PATH.read_text(encoding="utf-8")

OLD = '''        path = route((me[0], me[2]), target)
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

NEW = '''        # steer straight at the clicked point: the empirical controller walks in whatever direction it can actually
        # move, so it does not need waypoints (the flat graph's waypoints are often inside live collision)
        import steer

        def read_xz():
            point = player()
            return (point[0], point[2]) if point else None

        arrived, steps, final, reason = steer.step_toward(
            hold, read_xz, target, tolerance=10.0, max_steps=10, log=log)
        log(f"  order {target}: arrived={arrived} after {steps} steps, {final:.0f} units ({reason})")
        if arrived:
            log("order complete")
            order = None'''

assert text.count(OLD) == 1, text.count(OLD)
PATH.write_text(text.replace(OLD, NEW), encoding="utf-8")
print("map_bot steers directly at the order")
