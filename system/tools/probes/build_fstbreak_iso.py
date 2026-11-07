"""Does the game read the FST at all? Corrupt it and find out.

Every patch test so far assumed the game finds files through the disc's FST at the offsets `GCDisc` reports. Two header
families exist among the archives (`836e834a` and `cab6be20`), both legitimate, so the parser is not mispairing anything -
which leaves a harder question: does the game consult the FST, or does its own code hold a file table?

The test is blunt. Overwrite the FST's first 64 bytes - the root entry and the entry count - with 0xFF. A game that looks
its files up in the FST cannot boot past that; a game with its own table will not even notice.
"""
import json
import os
import shutil
import struct
import sys
import time

sys.path.insert(0, os.path.expanduser("~/gBox/system"))
from gbox.gcdisc import GCDisc

SRC = os.path.expanduser("~/gBox_alt/re4-lab/gc/re4-d1.iso")
OUT = os.path.expanduser("~/gBox_alt/gbox-cache/mods/78ab9efa2e310db4/re4gc-fstbreak")


def main() -> int:
    disc = GCDisc(SRC)
    fst_off, fst_size = struct.unpack(">II", disc._r(0x424, 8))
    print(f"FST at {fst_off}, size {fst_size}")
    os.makedirs(OUT, exist_ok=True)
    target = os.path.join(OUT, "re4-d1.iso")
    if not os.path.isfile(target) or os.path.getsize(target) != os.path.getsize(SRC):
        print("copying the disc (1.4 GB)...", flush=True)
        shutil.copyfile(SRC, target)
    with open(target, "r+b") as handle:
        handle.seek(fst_off)
        handle.write(b"\xff" * 64)
    print("corrupted the FST root entry and the first entries")
    with open(os.path.join(OUT, ".gbox-mod.json"), "w", encoding="utf-8") as handle:
        json.dump({"name": os.path.basename(OUT), "note": "FST root corrupted - does the game use the file table?",
                   "built": str(time.time()), "game_id": "78ab9efa2e310db4", "kind": "file", "launchable": True,
                   "image": "re4-d1.iso", "changes": {"FST@%d" % fst_off: "first 64 bytes destroyed"}}, handle, indent=1)
    print("built", target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
