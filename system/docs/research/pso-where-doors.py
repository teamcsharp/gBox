"""Field doors are not placements. Where are they, then?

`map_cave01_00` places exactly five class types - TORockCaveBL03 (155), TOSymbolchatColli (14), TOSensorAncient01 (11), TOSensorGeneral01 (11) and an unresolved
index 6 (8) - and **none of them is a door, warp, gate, teleport or area class**. The registry's door classes are all city doors (`TObjCityDoor_Shop`, `_Guild`,
`_Warp`, `_Med`, `_Lobby`) plus map/goal warps for the ruins.

So a field-room connection is **not a placement**, which is why the cave graph built from `link` is sparse: the data is not in the placement sets to find.

The remaining candidates are the event scripts (`*.evt`) and the collision geometry. `pso_evt` already parses headers, record tables and scripts, and its own docstring
says door transitions are the thing this lane has never found in the placement sets. This checks what the disc actually offers per area, so the next step is chosen
from evidence.
"""
import sys

sys.path.insert(0, r"C:\_tools\gBox\system")

from gbox import gcdisc                                          # noqa: E402

DISC = r"D:\gBox\cache\436e0bb84d5337d1\Phantasy Star Online Episode I & II Plus (USA).gcz"
AREAS = ("cave01", "cave02", "cave03", "machine01", "machine02", "ruins01", "ruins02",
         "ancient01", "ancient02", "ancient03", "forest01")


if __name__ == "__main__":
    disc = gcdisc.GCDisc(DISC)
    names = sorted(disc.files)

    print(f"disc files: {len(names)}\n")
    for area in AREAS:
        mine = [name for name in names if area in name]
        by_ext = {}
        for name in mine:
            ext = name.rsplit(".", 1)[-1].lower()
            by_ext[ext] = by_ext.get(ext, 0) + 1
        interesting = {ext: count for ext, count in by_ext.items() if ext in ("evt", "rel", "dat", "tam", "bin")}
        evt = [name for name in mine if name.lower().endswith(".evt")]
        print(f"{area:11s} files {len(mine):3d}  {interesting}")
        if evt:
            print(f"             evt: {evt[:4]}")

    print("\n=== every .evt on the disc, by area prefix ===")
    all_evt = [name for name in names if name.lower().endswith(".evt")]
    print(f"total .evt files: {len(all_evt)}")
    for name in all_evt[:14]:
        print("  ", name)

    print("\n=== is there an event archive rather than loose files? ===")
    archives = [name for name in names if "event" in name.lower() or name.lower().startswith("event")]
    print(f"names mentioning event: {len(archives)}")
    for name in archives[:10]:
        print("  ", name)
