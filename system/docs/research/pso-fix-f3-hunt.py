"""Fix the F3 takeover's hunting branch, which was left with placeholder lines.

The branch that should walk to a distant enemy contained two dead expressions from an editing pass:
    RUN.run_to(node := None, (0, 0)) if False else None
    pso_input.hold("a", 0.0) if False else None
Both are never evaluated (they sit behind `if False`), so nothing crashed, but the hunt did nothing at all. It now walks the route the height-aware
planner returns, legs at a time, the same way the other loops do.
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\.tmp\f3_takeover.py")
text = path.read_text(encoding="utf-8")

old = """            if route:
                for waypoint in route[1:3]:
                    RUN.run_to(node := None, (0, 0)) if False else None
                    pso_input.hold("a", 0.0) if False else None
                    break
        return None"""

new = """            if route:
                for waypoint in route[1:4]:
                    RUN.run_to(lambda: (player()[0], player()[2]) if player() else None,
                               (waypoint[0], waypoint[1]), tolerance=12.0, budget=20.0)
                    if not pso_input.allowed():
                        break
        return None"""

count = text.count(old)
print(f"pattern count: {count}")
if count == 1:
    path.write_text(text.replace(old, new), encoding="utf-8")
    print("F3 takeover: the hunt now walks the planned route")
else:
    print("pattern not found - leaving the file untouched")
