"""Make the bot follow clicked orders: the minimap writes a point, the bot walks to it.

The operator asked to click the map and have the bot go there. `minimap_live` records a click into `goto-order.json`; this makes self-play check that
file before choosing its own destination, walk to the ordered point with the height-aware planner, and then consume the order so it is not repeated.

An order takes precedence over exploration, which is what makes the map a control surface rather than a picture.
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\.tmp\selfplay2.py")
text = path.read_text(encoding="utf-8")

old = '''        candidates = [r for r in room_list if r["room"] not in visited] or room_list'''
new = '''        order = take_order()
        if order is not None:
            log(f"following the map order to ({order['x']:.0f},{order['z']:.0f})", {"event": "order", **order})
            here = ME.read_pos()
            if here is not None:
                import nav3
                route, raw_cells, legs = nav3.plan_h(here, (order["x"], order["z"]), start_height=now_y())
                if route:
                    log(f"  order route: {raw_cells} cells -> {legs} legs")
                    for waypoint in route[1:]:
                        RUN.run_to(ME.read_pos, (waypoint[0], waypoint[1]), tolerance=8.0, budget=20.0)
                        if not pso_input.allowed():
                            break
                else:
                    RUN.run_to(ME.read_pos, (order["x"], order["z"]), tolerance=10.0, budget=30.0)
            continue

        candidates = [r for r in room_list if r["room"] not in visited] or room_list'''
if text.count(old) != 1:
    raise SystemExit(f"travel anchor count {text.count(old)}")
text = text.replace(old, new)

helper = '''ORDER = Path(r"D:\\gBox\\pso-ds\\goto-order.json")
_last_order = [0.0]


def take_order():
    """The pending map order, if it is newer than the last one consumed."""
    try:
        payload = json.loads(ORDER.read_text(encoding="utf-8"))
    except Exception:                                            # noqa: BLE001
        return None
    if payload.get("t", 0) <= _last_order[0]:
        return None
    _last_order[0] = payload.get("t", 0)
    return {"x": payload["x"], "z": payload["z"]}


def main():'''
text = text.replace("def main():", helper, 1)
path.write_text(text, encoding="utf-8")
print("self-play now follows map orders")
