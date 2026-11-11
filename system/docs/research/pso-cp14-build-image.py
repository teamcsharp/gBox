"""CP14 step 3 offline half: BUILD a real mod image with the added placement, then verify the image.

`pso_map_write.build(cfg, game_id, rom, name, ops)` applies ops, writes a modded image and verifies it. This builds
`ds_cp14_room_added` from the base disc with one `add` op (a record at the room's measured centre) and then re-opens the built
image to prove the set now has 235 records and the new one is inside the room's footprint.

The image is what a live session would load with CP5's warp; the load itself is the part that needs the window.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\.tmp\cp14build\system")

from gbox import config as CFG, gcdisc, pso_editor as E, pso_map_write as W, pso_rooms as R, pso_setdata as P  # noqa: E402

BASE = r"D:\gBox\cache\mods\436e0bb84d5337d1\pso_city_npc_moved\Phantasy Star Online Episode I & II Plus (USA).iso"
GID = "436e0bb84d5337d1"
SET = "map_ancient01_00_00o.dat"
ROOM = "Scene/map_aancient01_00r.rel"
NAME = "ds_cp14_room_added"


def main():
    cfg = CFG.load()
    disc = gcdisc.GCDisc(BASE)
    quad = R.room_quad(disc.read(ROOM))
    x, y, z = quad["origin"][0], 0.0, quad["origin"][2]
    kind = P.records(W.read_set(disc, SET)[0])[0]["kind"]
    op = E.edit("add", SET, kind=kind, x=float(x), y=float(y), z=float(z))
    print(f"building {NAME}: add kind {kind:#x} at ({x:.1f}, {y:.2f}, {z:.1f})", flush=True)
    result = W.build(cfg, GID, BASE, NAME, [op], progress=lambda p, m: print(f"  [{p}] {m}", flush=True))
    print("build:", json.dumps({k: v for k, v in result.items() if k != "verification"}, default=str)[:600])
    verification = result.get("verification")
    print("verification:", json.dumps(verification, default=str)[:400])

    image = Path(result.get("image") or result.get("path") or result.get("rom") or "")
    if not image.is_file():
        candidates = list((Path(cfg.cache_dirs.get("windows") if isinstance(cfg.cache_dirs, dict) else Path(r"D:\gBox\cache"))
                           ).glob(f"mods/{GID}/{NAME}/*.iso"))
        image = candidates[0] if candidates else image
    print("image:", image, image.is_file())
    if image.is_file():
        modded = gcdisc.GCDisc(str(image))
        after = P.records(W.read_set(modded, SET)[0])
        print(f"modded image set: {len(after)} records; last at "
              f"({after[-1].get('x', 0):.2f}, {after[-1].get('z', 0):.2f}); "
              f"inside footprint: {R.contains(quad, after[-1].get('x', 0), after[-1].get('z', 0))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
