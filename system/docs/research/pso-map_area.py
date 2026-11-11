"""Map an area by floor number, using its extracted collision file.

Every tool in the chain - the room segmenter, the height table, the room database, the audit, the planner and the minimap - is keyed by **floor
number** and reads `rel/map_forest<NN>c.rel`. So mapping an area is: place its collision file at the floor's name, then run the pipeline.

Live-layout identification happens when the bot is standing in the area (the loaded layout is the only one whose walkable cells contain the character
and the objects). Away from the area there is no live evidence, so the caller names the layout explicitly - defaulting to `_00`, the first variant.

Usage:
  python map_area.py <floor> <area> [layout]
  python map_area.py --batch          # the Episode I floors, layout 00
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

REL = Path(r"D:\gBox\pso-ds\rel")
ROUTES = Path(r"D:\gBox\pso-ds\routes")
TMP = Path(r"C:\_tools\gBox\.tmp")

EP1_FLOORS = {
    4: "cave02",
    5: "cave03",
    6: "machine01",
    7: "machine02",
    8: "ruins01",
    9: "ruins02",
    10: "ruins03",
}


def map_floor(floor, area, layout="00"):
    suffix = f"_{layout}" if layout else ""
    source = REL / f"map_{area}{suffix}c.rel"
    if not source.exists():
        lower = REL / f"map_a{area}_{layout}c.rel"
        if lower.exists():
            source = lower
        else:
            print(f"floor {floor}: no collision file for {area} layout {layout}")
            return False
    target = REL / f"map_forest{floor:02d}c.rel"
    if not target.exists() or target.stat().st_size != source.stat().st_size:
        shutil.copyfile(source, target)
    print(f"floor {floor} <- {source.name} ({source.stat().st_size} bytes)")

    for command in ([f"rooms_mesh2.py", str(floor)], ["height_map.py", str(floor)]):
        result = subprocess.run([sys.executable, *command], cwd=str(TMP), capture_output=True, text=True)
        tail = (result.stdout or "").strip().splitlines()[-2:]
        print("   " + " | ".join(tail) if tail else f"   {command[0]} produced no output")
        if result.returncode != 0:
            print(f"   {command[0]} failed: {(result.stderr or '').strip().splitlines()[-1:]}")
            return False
    return True


def main(argv):
    if len(argv) > 1 and argv[1] == "--batch":
        done = 0
        for floor, area in EP1_FLOORS.items():
            if map_floor(floor, area):
                done += 1
        print(f"\nmapped {done} of {len(EP1_FLOORS)} Episode I floors")
        return 0
    if len(argv) < 3:
        print(__doc__)
        return 2
    floor = int(argv[1])
    area = argv[2]
    layout = argv[3] if len(argv) > 3 else "00"
    return 0 if map_floor(floor, area, layout) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
