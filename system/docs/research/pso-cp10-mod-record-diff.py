"""CP10: find the moved record by diffing parsed set records (base vs modded image)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\.tmp\main-repo\system")

from gbox import gcdisc, pso_setdata as P  # noqa: E402

BASE = r"D:\gBox\cache\mods\436e0bb84d5337d1\pso_city_npc_moved\Phantasy Star Online Episode I & II Plus (USA).iso"
MODS = Path(r"D:\gBox\cache\mods\436e0bb84d5337d1")


def main():
    base = gcdisc.GCDisc(BASE)
    for name in ("pso_objmove_forest01_r5", "pso_objmove_forest01_l0_r60"):
        mod_dir = MODS / name
        manifest = json.loads((mod_dir / ".gbox-mod.json").read_text(encoding="utf-8"))
        mod = gcdisc.GCDisc(str(mod_dir / manifest["image"]))
        print(f"== {name}")
        for change in manifest["file_changes"]:
            path = change["path"]
            b = base.read(path)
            m = mod.read(path)
            try:
                rb, rm = P.records(b), P.records(m)
            except Exception as exc:                     # noqa: BLE001
                print(f"  {path}: records() failed {type(exc).__name__}: {exc}")
                continue
            print(f"  {path}: {len(rb)} base records, {len(rm)} modded records")
            diffs = 0
            for i, (x, y) in enumerate(zip(rb, rm)):
                if x != y:
                    diffs += 1
                    changed = {k: (x.get(k), y.get(k)) for k in set(x) | set(y) if x.get(k) != y.get(k)}
                    print(f"   record {i}: {changed}")
            print(f"   records changed: {diffs}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
