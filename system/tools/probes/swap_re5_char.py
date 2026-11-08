"""Swap whole character archives in a non-RE4 title: does the engine draw whatever the file contains?

Test 1 for RE5. The panel's skin swaps move textures between `nativeNXx64/ImgNX/Archive/uPlNN*.arc`; this instead writes one character's
**entire archive** over another's, which is the only route that could produce a different *character* rather than a different paint job.

If the round loads and shows Jill where Chris should be, RE5 tolerates substitution at the archive level and mesh work becomes worthwhile. If
it hangs or ignores the file, the answer is no and no mesh work will change it.
"""
import os
import sys

sys.path.insert(0, os.path.expanduser("~/gBox/system"))
from gbox import switch_mods

HOME = os.path.expanduser("~")
ROOT = os.path.join(HOME, "gBox_alt/switch/romfs/010018100CD46000")


class Config:
    cache = os.path.join(HOME, "gBox_alt", "gbox-cache")


def main() -> int:
    pairs = sys.argv[1] if len(sys.argv) > 1 else "uPl02JillCos1.arc=uPl00ChrisNormal.arc"
    build = sys.argv[2] if len(sys.argv) > 2 else "re5-charswap"
    game_id = sys.argv[3] if len(sys.argv) > 3 else "52d15709be0fda1a"
    title_id = "010018100CD46000"
    changes = {}
    for pair in pairs.split(","):
        src_name, dst_name = [v.strip() for v in pair.split("=", 1)]
        src = os.path.join(ROOT, "nativeNXx64", "ImgNX", "Archive", src_name)
        dst = os.path.join(ROOT, "nativeNXx64", "ImgNX", "Archive", dst_name)
        if not (os.path.isfile(src) and os.path.isfile(dst)):
            print(f"skipping {pair}: not both present")
            continue
        changes[f"romfs/nativeNXx64/ImgNX/Archive/{dst_name}"] = {"bytes": open(src, "rb").read()}
        print(f"  {dst_name} <- {src_name} ({os.path.getsize(src)} bytes)")
    if not changes:
        return 1
    result = switch_mods.write_files(Config(), game_id, build, changes,
                                     create={"title_id": title_id, "kind": "file", "game_title": "re5"},
                                     note=f"whole-character archive swap: {pairs}")
    print("wrote", result.get("mod"), result.get("files"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
