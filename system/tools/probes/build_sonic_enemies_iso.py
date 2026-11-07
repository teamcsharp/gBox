"""Inject every rebuilt enemy pack into a copy of the disc, then write the mod marker with an `image` pointer.

All 58 rebuilt `em/*.drs` packs are the same size as their disc entries (the builder keeps the budget), so the FST needs no
edit: a seek and a write per pack. Output is a mod build Dolphin can open, with `image` set - the key without which
`filemods.launch_path` looks for the library's own `.gcz` and the launch fails.
"""
import json
import os
import shutil
import sys
import time

sys.path.insert(0, os.path.expanduser("~/gBox/system"))
from gbox.gcdisc import GCDisc

SRC = os.path.expanduser("~/gBox_alt/re4-lab/gc/re4-d1.iso")
PACKS = os.path.expanduser("~/gBox_alt/re4-lab/re4gc-sonic-enemies")
OUT = os.path.expanduser("~/gBox_alt/gbox-cache/mods/78ab9efa2e310db4/re4gsonic_enemies")
NOTE = "GameCube Ganados rebuilt from the collection's Sonic rig (58 em/*.drs packs)"


def main() -> int:
    disc = GCDisc(SRC)
    plan = []
    for name in sorted(os.listdir(PACKS)):
        if not name.endswith(".drs"):
            continue
        key = f"em/{name}"
        entry = disc.files.get(key)
        if entry is None:
            print(f"{key}: not on the disc, skipping")
            continue
        offset, disc_size = entry
        local = os.path.join(PACKS, name)
        size = os.path.getsize(local)
        if size > disc_size:
            print(f"{key}: {size} > {disc_size}, skipping (needs a rebuild)")
            continue
        plan.append((key, offset, size, disc_size, local))
    print(f"packs to write: {len(plan)}")
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
                print(f"{key}: short read ({len(payload)} of {size}), aborting")
                return 1
            handle.seek(offset)
            handle.write(payload)
            if size < disc_size:
                handle.write(b"\0" * (disc_size - size))
        print(f"wrote {len(plan)} packs", flush=True)
    with open(os.path.join(OUT, ".gbox-mod.json"), "w", encoding="utf-8") as handle:
        json.dump({"name": os.path.basename(OUT), "note": NOTE, "built": str(time.time()),
                   "game_id": "78ab9efa2e310db4", "kind": "file", "launchable": True, "image": "re4-d1.iso",
                   "changes": {key: "sonic" for key, *_ in plan}}, handle, indent=1)
    print("built", target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
