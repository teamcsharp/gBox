"""Confirm the exit coordinate independently: is there a collision trigger near the recorded warp point?

The operator's play recorded the Forest 1 -> Forest 2 transition at (133.0,-48.1). A warp has to be a trigger region in the level, so this
checks every TRIGGER_FLAG triangle position for one close to that point. A hit confirms the exit's identity from the level data rather than
from a single recorded event.
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\system")

from gbox import psomap                                            # noqa: E402

REL = Path(r"D:\gBox\pso-ds\rel\map_forest01c.rel")
EXITS = [(133.0, -48.1), (536.4, -566.4)]
RADIUS = 40.0


def main():
    tris = psomap.collision(REL.read_bytes())
    triggers = []
    for (a, b, c, flags, _normal) in tris:
        if not (flags & psomap.TRIGGER_FLAG):
            continue
        x = (a[0] + b[0] + c[0]) / 3.0
        y = (a[1] + b[1] + c[1]) / 3.0
        z = (a[2] + b[2] + c[2]) / 3.0
        triggers.append((x, y, z))
    print(f"trigger triangles: {len(triggers)}")
    for exit_point in EXITS:
        near = sorted(((math.dist((t[0], t[2]), exit_point), t) for t in triggers), key=lambda pair: pair[0])[:3]
        print(f"\nexit {exit_point}:")
        for distance, point in near:
            print(f"  trigger at ({point[0]:8.1f},{point[1]:6.1f},{point[2]:8.1f})  {distance:6.1f} units away")
        closest = near[0][0] if near else 999
        print(f"  nearest trigger: {closest:.1f} units -> {'TRIGGER FOUND' if closest <= RADIUS else 'no trigger nearby'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
