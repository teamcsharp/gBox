"""CP4 helper: validate the Forest 1 mission's route with the plane's own navmap code.

`load_navmap` (autoplay.py) turns the mission's rel into a walkability grid with
`psomap.walkable_cells(psomap.collision(data, be), size)`. This reproduces that offline - so the question "are the mission's
waypoints on walkable cells, and is the route connected?" is answered in the same coordinate space the runner uses.
"""
import hashlib
import sys

sys.path.insert(0, r"C:\_tools\gBox\system")

from gbox import gcdisc, psomap                                          # noqa: E402

DISC = r"D:\gBox\cache\mods\436e0bb84d5337d1\pso_city_npc_moved\Phantasy Star Online Episode I & II Plus (USA).iso"
REL = "Scene/map_forest01c.rel"
WANT = "0e7bc121a41e483e2c4d03bb031226461fecafb6c14ebfbeaab8ffe76ecfd2f5"
SIZE = 10.0
POINTS = [("interact 1", -95.0, 214.0), ("navigate 1", -140.0, 330.0), ("interact 2", 7.0, 362.0), ("fight", 90.0, 300.0)]


def main():
    data = gcdisc.GCDisc(DISC).read(REL)
    print(f"{REL}: {len(data)} bytes, sha256 {hashlib.sha256(data).hexdigest()[:16]} "
          f"{'== the mission artifact' if hashlib.sha256(data).hexdigest() == WANT else '!= the artifact'}")
    col = psomap.collision(data, True)
    floor, wall = psomap.walkable_cells(col, SIZE)
    print(f"cells: floor {len(floor)}, wall {len(wall)}")
    def cell(x, z):
        return (int(x // SIZE), int(z // SIZE))
    for label, x, z in POINTS:
        c = cell(x, z)
        where = "floor" if c in floor else ("wall" if c in wall else "off-grid")
        print(f"  {label:11s} ({x:6.1f},{z:6.1f}) -> cell {c} {where}")
        if c in wall:
            # nearest floor cell, to say how far the plan is from walkable ground
            best = min(floor, key=lambda f: (f[0] - c[0]) ** 2 + (f[1] - c[1]) ** 2) if floor else None
            if best:
                d = ((best[0] - c[0]) ** 2 + (best[1] - c[1]) ** 2) ** 0.5
                print(f"      nearest floor cell {best} at {d:.1f} cells")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
