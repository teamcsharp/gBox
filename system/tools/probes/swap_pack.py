"""Swap a whole character pack, not the mesh inside it: does the engine load whatever the file contains?

Every mesh-level route has a ceiling - same-topology edits draw, rebuilt topology does not - so a character *replacement* needs the pack file
itself to be exchanged. The engine reads `bio4/em/<name>.udas` by name, and a LayeredFS overlay can substitute any file for that name, so the
test is: write a player pack's bytes under an enemy pack's name and see who spawns.

If it works, "replace the zombies with the cast" is a file copy, with no mesh surgery at all.
"""
import os
import sys

sys.path.insert(0, os.path.expanduser("~/gBox/system"))
from gbox import switch_mods

HOME = os.path.expanduser("~")
ROMFS = os.path.join(HOME, "gBox_alt/switch/romfs/010099A00BC1E000", "bio4", "em")
GAME_ID = "270a15eb98dab4d7"
TITLE_ID = "010099A00BC1E000"


class Config:
    cache = os.path.join(HOME, "gBox_alt", "gbox-cache")


def main() -> int:
    pairs = sys.argv[1] if len(sys.argv) > 1 else ""      # "pl07=pl08,em16=em10"
    if pairs and "=" in pairs:
        build = sys.argv[2] if len(sys.argv) > 2 else "re4sw-packswap"
        changes = {}
        for pair in pairs.split(","):
            src_name, dst_name = [v.strip() for v in pair.split("=", 1)]
            src = os.path.join(ROMFS, src_name)
            dst = os.path.join(ROMFS, dst_name)
            if not (os.path.isfile(src) and os.path.isfile(dst)):
                print(f"skipping {pair}: not both in bio4/em")
                continue
            changes[f"romfs/bio4/em/{dst_name}"] = {"bytes": open(src, "rb").read()}
            print(f"  {dst_name} <- {src_name}")
        if not changes:
            return 1
        result = switch_mods.write_files(Config(), GAME_ID, build, changes,
                                         create={"title_id": TITLE_ID, "kind": "file", "game_title": "re4"},
                                         note=f"within-family pack swaps: {pairs}")
        print("wrote", result.get("mod"), result.get("files"))
        return 0
    source = sys.argv[1] if len(sys.argv) > 1 else "pl00.udas"     # whose body to wear
    targets = (sys.argv[2] if len(sys.argv) > 2 else "em10.udas")
    build = sys.argv[3] if len(sys.argv) > 3 else "re4sw-packswap"
    src_path = os.path.join(ROMFS, source)
    if not os.path.isfile(src_path):
        print(f"{source} is not in bio4/em")
        return 1
    data = open(src_path, "rb").read()
    changes = {}
    for name in [t.strip() for t in targets.split(",") if t.strip()]:
        if not os.path.isfile(os.path.join(ROMFS, name)):
            print(f"skipping {name}: not in bio4/em")
            continue
        changes[f"romfs/bio4/em/{name}"] = {"bytes": data}
        print(f"  {name} <- {source} ({len(data)} bytes)")
    if not changes:
        print("nothing to write")
        return 1
    result = switch_mods.write_files(Config(), GAME_ID, build, changes,
                                     create={"title_id": TITLE_ID, "kind": "file", "game_title": "re4"},
                                     note=f"whole-pack swap: {source} written as {targets}")
    print("wrote", result.get("mod"), result.get("files"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
