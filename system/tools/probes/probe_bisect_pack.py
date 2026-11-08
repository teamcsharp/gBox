"""Which player pack does the camera actually draw? Vanish a set of them and see whether the player survives.

`pl00`-only edits change nothing (rounds 70 and 108), while all 26 packs at once visibly collapse the player (round 70). So the visible
mesh is one of `pl01`..`pl21`, and this bisects: vanish every material of the body slots in a chosen set of packs, one build, one boot.
If the player disappears, the visible pack is in the set.

Usage: probe_bisect_pack.py <build name> <first pack> <last pack>
"""
import os
import sys

sys.path.insert(0, os.path.expanduser("~/gBox/system"))
from gbox import re4gc_inventory as INV
from gbox import re4hd_hide as HIDE
from gbox import re4hd_models as R
from gbox import re4hd_tex as TEX
from gbox import switch_mods

HOME = os.path.expanduser("~")
ROMFS = os.path.join(HOME, "gBox_alt/switch/romfs/010099A00BC1E000/bio4/em")
GAME_ID = "270a15eb98dab4d7"
TITLE_ID = "010099A00BC1E000"


class Config:
    """The little of the config the writer needs: where the mod cache lives."""
    cache = os.path.join(HOME, "gBox_alt", "gbox-cache")


MODE = os.environ.get("MODE", "vanish")


def main() -> int:
    build = sys.argv[1] if len(sys.argv) > 1 else "bisect-a"
    first = sys.argv[2] if len(sys.argv) > 2 else "pl00"
    last = sys.argv[3] if len(sys.argv) > 3 else "pl0d"
    names = sorted(n for n in os.listdir(ROMFS) if n.startswith("pl") and n.endswith(".udas"))
    chosen = [n for n in names if first <= n.lower().replace(".udas", "") <= last]
    print(f"packs: {first}..{last} -> {len(chosen)} of {len(names)}: {', '.join(chosen)}")
    changes, touched = {}, []
    for name in chosen:
        data = open(os.path.join(ROMFS, name), "rb").read()
        try:
            slots = INV.bin_slots(data, endian="<")
        except ValueError:
            continue
        patched, any_slot = data, False
        for index, entry in enumerate(slots):
            body = patched[entry["offset"]:entry["offset"] + entry["size"]]
            try:
                mesh = R.bin_read(body)
            except (R.BINError, ValueError):
                continue
            if mesh.pos is None or len(mesh.pos) < 800 or not mesh.mats:
                continue
            # keep material 0: vanishing every material leaves a mesh of zero-area triangles, which the writer (rightly)
            # refuses. Keeping one material still makes the visible pack obvious - the player renders as that surface only.
            if MODE == "scale":
                # SCALE is the signal that is already proven visible (round 70 collapsed the player with it), so a bisection
                # with it needs no interpretation: a changed player means the pack is in the set.
                HIDE.mesh_check(mesh)
                HIDE.scale_materials(mesh, list(range(len(mesh.mats))), 0.1)
                report = {"vertices_changed": len(mesh.pos)}
            else:
                survivors = list(range(1, len(mesh.mats)))
                if not survivors:
                    continue
                report = HIDE.hide_materials(mesh, survivors, mode="vanish")
            replacement = R.pad_to(R.bin_write(mesh, verify=True), entry["size"])
            patched = patched[:entry["offset"]] + replacement + patched[entry["offset"] + entry["size"]:]
            touched.append({"pack": name, "slot": index, "vertices": report.get("vertices_changed"),
                            "materials": len(mesh.mats)})
            any_slot = True
        if any_slot:
            changes[f"romfs/bio4/em/{name}"] = {"bytes": patched}
    if not changes:
        print("nothing to vanish")
        return 1
    result = switch_mods.write_files(Config(), GAME_ID, build, changes,
                                     create={"title_id": TITLE_ID, "kind": "file", "game_title": "re4"},
                                     note=f"bisect: every material of {first}..{last} vanished")
    print("wrote", result.get("mod"), "files", len(result.get("files") or []), "slots", len(touched))
    print("slots:", touched[:4])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
