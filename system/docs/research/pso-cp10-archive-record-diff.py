"""CP10: diff the archive-based mod (gsl_set_object.gsl) too, by extracting its set entries."""
import json
import sys
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\.tmp\main-repo\system")

from gbox import gcdisc, pso_map_write as W, pso_setdata as P  # noqa: E402

BASE = r"D:\gBox\cache\mods\436e0bb84d5337d1\pso_city_npc_moved\Phantasy Star Online Episode I & II Plus (USA).iso"
MODS = Path(r"D:\gBox\cache\mods\436e0bb84d5337d1")


def main():
    base = gcdisc.GCDisc(BASE)
    name = "pso_objmove_forest01_l0_r60"
    mod_dir = MODS / name
    manifest = json.loads((mod_dir / ".gbox-mod.json").read_text(encoding="utf-8"))
    mod = gcdisc.GCDisc(str(mod_dir / manifest["image"]))
    base_sets = W.set_archive_files(base, "object")
    mod_sets = W.set_archive_files(mod, "object")
    print(f"object sets: base {len(base_sets)} modded {len(mod_sets)}")
    forest = [s for s in base_sets if "forest01" in s.lower()]
    print("forest01 sets:", forest[:8])
    for set_name in forest:
        try:
            b_data, _ = W.read_set(base, set_name)
            m_data, _ = W.read_set(mod, set_name)
        except Exception as exc:                          # noqa: BLE001
            continue
        if b_data == m_data:
            continue
        try:
            rb, rm = P.records(b_data), P.records(m_data)
        except Exception as exc:                          # noqa: BLE001
            print(f"  {set_name}: differs, records() failed: {exc}")
            continue
        print(f"  {set_name}: DIFFERS ({len(rb)} records)")
        for i, (x, y) in enumerate(zip(rb, rm)):
            if x != y:
                changed = {k: (x.get(k), y.get(k)) for k in set(x) | set(y) if x.get(k) != y.get(k)}
                print(f"    record {i}: {changed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
