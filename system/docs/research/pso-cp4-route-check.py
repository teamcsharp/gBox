"""CP4 helper: does the Forest 1 mission's route line up with real placement records?

The mission says "open two door panels" at (-95, 214) and (7, 362), then fight around (90, 300). Forest 1's placements are in
`map_forest01_00o.dat`; CP8 measured that entities and rooms share one coordinate space, so a door record should sit almost exactly
on each interact point. This checks that, and reports what kind each nearby record is.
"""
import sys

sys.path.insert(0, r"C:\_tools\gBox\.tmp\main-repo\system")

from gbox import gcdisc, pso_map_write as W, pso_setdata as P                # noqa: E402

DISC = r"D:\gBox\cache\mods\436e0bb84d5337d1\pso_city_npc_moved\Phantasy Star Online Episode I & II Plus (USA).iso"
SETS = ["map_forest01_00o.dat", "map_forest01d.dat"]
POINTS = [("interact 1", -95, 214), ("interact 2", 7, 362), ("fight centre", 90, 300)]


def main():
    disc = gcdisc.GCDisc(DISC)
    for set_name in SETS:
        try:
            data, _where = W.read_set(disc, set_name)
        except Exception as exc:                                  # noqa: BLE001
            print(f"{set_name}: unreadable ({exc})")
            continue
        recs = P.records(data)
        kinds = {}
        for r in recs:
            kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
        print(f"{set_name}: {len(recs)} records, {len(kinds)} kinds {sorted(kinds)[:12]}")
        for label, x, z in POINTS:
            near = sorted(recs, key=lambda r: (r["x"] - x) ** 2 + (r["z"] - z) ** 2)[:3]
            for r in near:
                d = ((r["x"] - x) ** 2 + (r["z"] - z) ** 2) ** 0.5
                print(f"  {label:12s} ({x:5d},{z:4d}): {d:7.2f} away  kind {r['kind']:#06x} "
                      f"at ({r['x']:8.2f}, {r['y']:7.2f}, {r['z']:8.2f}) rot {r.get('rotation')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
