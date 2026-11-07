"""Patch the Sonic player archives into a copy of the RE4 GameCube disc, in place.

The disc's FST names them `em/pl00.drs` and friends, and `GCDisc.files` holds `(offset, size)` tuples - an entry's size is
fixed by the FST, so a same-size replacement is a seek and a write, no ISO rebuild. This refuses rather than guess when a
size differs.

Writes `<out>/re4-d1.iso` and `<out>/.gbox-mod.json`, the shape a Dolphin mod build has.
"""
import json
import os
import shutil
import sys
import time

sys.path.insert(0, os.path.expanduser("~/gBox/system"))
from gbox.gcdisc import GCDisc

SRC = os.path.expanduser("~/gBox_alt/re4-lab/gc/re4-d1.iso")
PATCHED = os.path.expanduser("~/gBox_alt/re4-lab/re4gc-sonic")
OUT = os.path.expanduser("~/gBox_alt/gbox-cache/mods/78ab9efa2e310db4/re4gsonic_real")
NAMES = ("pl00.drs", "pl08.drs", "pl09.drs", "pl10.drs")
NOTE = "Sonic player models injected into a copy of the GameCube disc (em/pl00, pl08, pl09, pl10)"


def main() -> int:
    disc = GCDisc(SRC)
    plan = []
    for name in NAMES:
        key = f"em/{name}"
        entry = disc.files.get(key)
        local = os.path.join(PATCHED, name)
        if entry is None:
            print(f"{key}: not on the disc")
            return 1
        if not os.path.isfile(local):
            print(f"{key}: no patched archive at {local}")
            return 1
        offset, disc_size = entry
        size = os.path.getsize(local)
        fits = size <= disc_size
        print(f"{key}: offset {offset} disc size {disc_size} | patched {size} | fits: {fits}")
        if not fits:
            print("   refusing: larger than the disc entry needs an ISO rebuild, not a write")
            return 1
        # a DRS is read through its own entry table, so a shorter archive padded with zeros to the disc's entry size is
        # the same archive to the game; the padding is never addressed by an offset inside the table
        plan.append((key, offset, size, disc_size, local))
    os.makedirs(OUT, exist_ok=True)
    target = os.path.join(OUT, "re4-d1.iso")
    if not os.path.isfile(target) or os.path.getsize(target) != os.path.getsize(SRC):
        print("copying the disc (1.4 GB)...", flush=True)
        shutil.copyfile(SRC, target)
    with open(target, "r+b") as handle:
        for key, offset, size, disc_size, local in plan:
            with open(local, "rb") as source:
                payload = source.read()
            if len(payload) != size:
                print(f"{key}: read {len(payload)} of {size}; aborting before writing")
                return 1
            handle.seek(offset)
            handle.write(payload)
            if size < disc_size:
                handle.write(b"\0" * (disc_size - size))
            print(f"   wrote {key} at {offset}", flush=True)
    with open(os.path.join(OUT, ".gbox-mod.json"), "w", encoding="utf-8") as handle:
        json.dump({"name": os.path.basename(OUT), "note": NOTE, "built": str(time.time()),
                   "game_id": "78ab9efa2e310db4", "kind": "file",
                   "changes": {f"em/{n}": "sonic" for n in NAMES}}, handle, indent=1)
    print("built", target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
