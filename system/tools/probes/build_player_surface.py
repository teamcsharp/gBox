"""The player reshaped to a Ganado's silhouette: `morph_to`, which is the only edit that changes a shape.

Bone-proportion transfer preserves silhouettes (round 86, measured across every player pack), so it cannot change a character. The
surface morph pulls each of the template's vertices onto the donor's surface, which does change it - that is what the working
`em16morph` build did to enemies - and it keeps the template's vertex count, primitive table and materials, the only class of edit
this engine draws.

The donor is a real BIN from the same game (`em16` slot 0), so no conversion is needed and the result is the operator's
"player be zombies" swap in the one place a camera always shows: the character you play.
"""
import json
import os
import sys

sys.path.insert(0, os.path.expanduser("~/gBox/system"))
from gbox import config as gconfig
from gbox import re4gc_inventory as INV
from gbox import re4hd_affine as A
from gbox import re4hd_models as R
from gbox import switch_mods

TITLE = "010099A00BC1E000"
GAME = "270a15eb98dab4d7"
ROMFS = os.path.join(os.path.expanduser("~/gBox_alt/switch/romfs"), TITLE, "bio4", "em")
DONOR_PACK = sys.argv[1] if len(sys.argv) > 1 else "em16.udas"
DONOR_SLOT = int(sys.argv[2]) if len(sys.argv) > 2 else 0
BUILD = sys.argv[3] if len(sys.argv) > 3 else "re4sw-playercoherent"
TEMPLATE_PREFIX = os.environ.get("TEMPLATE_PREFIX", "pl")     # pl = the player, em = the enemies
BLEND_ENV = os.environ.get("BLEND", "auto")                    # "auto" = choose from the target's bands, else 0..1
BLEND = None if BLEND_ENV == "auto" else float(BLEND_ENV)
# a ceiling on the automatic strength: `auto` keeps a slot loadable, the ceiling keeps it recognisable
BLEND_CAP = float(os.environ["BLEND_CAP"]) if os.environ.get("BLEND_CAP") else None
# the recognition rule: reach this factor on the most extreme band, whatever the pack's band sizes are
TARGET = float(os.environ["TARGET"]) if os.environ.get("TARGET") else None     # pl = the player, em = the enemies
PACKS = sys.argv[4].split(",") if len(sys.argv) > 4 else None


def donor_from_bin(path: str) -> R.Bin:
    """A donor read straight from a .bin (the collection path: any extracted model converted once)."""
    return R.bin_read(open(path, "rb").read())


def donor_mesh() -> R.Bin:
    data = open(os.path.join(ROMFS, DONOR_PACK), "rb").read()
    slots = INV.bin_slots(data, endian="<")
    entry = slots[DONOR_SLOT]
    mesh = R.bin_read(data[entry["offset"]:entry["offset"] + entry["size"]])
    if mesh.pos is None or mesh.tris is None:
        raise SystemExit("the donor slot has no geometry")
    return mesh


def main() -> int:
    cfg = gconfig.load(os.path.expanduser("~/gBox/system/gbox.toml"))
    donor_bin_path = os.environ.get("DONOR_BIN", "")
    donor = donor_from_bin(donor_bin_path) if donor_bin_path else donor_mesh()
    print(f"donor: {DONOR_PACK} slot {DONOR_SLOT} | {len(donor.pos)} vertices, {len(donor.tris)} triangles")
    # PACKS may name several packs (comma separated): a village round spawns more than one enemy pack, so patching a single pack
    # leaves most villagers untouched and makes "did it work?" unanswerable from a frame.
    chosen = (",".join(PACKS) if isinstance(PACKS, (list, tuple)) else str(PACKS))
    names = [n.strip() for n in chosen.split(",") if n.strip()] if chosen else sorted(
        n for n in os.listdir(ROMFS) if n.lower().startswith(TEMPLATE_PREFIX) and n.lower().endswith(".udas"))
    changes, totals = {}, {"packs": 0, "slots": 0, "vertices": 0}
    for name in names:
        data = open(os.path.join(ROMFS, name), "rb").read()
        try:
            slots = INV.bin_slots(data, endian="<")
        except ValueError:
            continue
        patched, touched, moved = data, 0, 0
        for index, slot in enumerate(slots):
            body = data[slot["offset"]:slot["offset"] + slot["size"]]
            try:
                mesh = R.bin_read(body)
                if mesh.pos is None or mesh.tris is None or not mesh.mats:
                    continue
                # only the main (largest) mesh of each pack: the head/accessory slots are small and would distort faces
                if len(mesh.pos) < 800:
                    continue
                # coherent: the bone decides where a vertex may land, the surface decides the shape (round 87's shards came
                # from letting a global nearest-surface search pick the region)
                # per-band affine: coherent AND shape-changing, the combination the last three variants each lacked
                replacement = R.pad_to(A.band_affine_bin(mesh, donor, bands=6, blend=BLEND, blend_cap=BLEND_CAP, target_factor=TARGET)[0], slot["size"])
                patched = INV.pack_patch(patched, index, replacement, endian="<")
                touched += 1
                moved += len(mesh.pos)
                print(f"  {name} slot {index}: {len(mesh.pos)} vertices onto the donor surface")
            except (R.BINError, ValueError, IndexError):
                continue
        if touched:
            changes[f"bio4/em/{name}"] = {"bytes": patched}
            totals["packs"] += 1
            totals["slots"] += touched
            totals["vertices"] += moved
    print(f"packs: {totals['packs']} | slots: {totals['slots']} | vertices: {totals['vertices']}")
    if not changes:
        return 1
    out = switch_mods.write_files(cfg, GAME, BUILD, changes,
                                  create={"title_id": TITLE, "game_title": "re4_switch", "base": "", "kind": "files"},
                                  note=f"player meshes pulled onto {DONOR_PACK} slot {DONOR_SLOT}'s surface")
    print("write_files:", json.dumps(out)[:200])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
