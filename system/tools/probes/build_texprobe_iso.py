"""The discriminator: overwrite one TPL's pixel data, inject it, and see whether the change is drawn.

If a solid-filled common texture draws, the write path reaches the game and the model archives specifically are not being
read from those FST paths. If nothing changes, the write path is wrong and every archive test so far measured that.

The patch keeps the file's size, so it goes in at the FST offset like the archives did. Any visible change is enough, so the
pixel region is filled with 0xFF rather than decoded: for RGBA that is white, for a paletted format it selects an index
whose colour differs from the original art.
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
TARGET = "ss/Cmn/f01.tpl"
OUT = os.path.expanduser("~/gBox_alt/gbox-cache/mods/78ab9efa2e310db4/re4gc-texprobe")


def tpl_data_offset(blob: bytes) -> int:
    """GC TPL: u32 magic 0x0020AF30, u32 texture count, u32 header size; then per-texture 8-byte headers."""
    magic, count, header_size = struct.unpack_from(">III", blob, 0)
    if magic != 0x0020AF30:
        raise ValueError(f"not a TPL (magic {magic:#x})")
    return max(header_size, 0x0C + 8 * count)


def main() -> int:
    disc = GCDisc(SRC)
    entry = disc.files.get(TARGET)
    if entry is None:
        print(f"{TARGET}: not on the disc")
        return 1
    offset, size = entry
    blob = bytearray(disc._r(offset, size))
    data_at = tpl_data_offset(blob)
    print(f"{TARGET}: offset {offset} size {size} | header says data at {data_at} "
          f"| first bytes {bytes(blob[:16]).hex()}")
    changed = len(blob) - data_at
    blob[data_at:] = b"\xff" * changed
    os.makedirs(OUT, exist_ok=True)
    target = os.path.join(OUT, "re4-d1.iso")
    if not os.path.isfile(target) or os.path.getsize(target) != os.path.getsize(SRC):
        print("copying the disc (1.4 GB)...", flush=True)
        shutil.copyfile(SRC, target)
    with open(target, "r+b") as handle:
        handle.seek(offset)
        handle.write(blob)
    print(f"wrote {changed} bytes of pixel data at {offset + data_at}")
    with open(os.path.join(OUT, ".gbox-mod.json"), "w", encoding="utf-8") as handle:
        json.dump({"name": os.path.basename(OUT), "note": f"{TARGET} pixel data filled to prove the write path draws",
                   "built": str(time.time()), "game_id": "78ab9efa2e310db4", "kind": "file", "launchable": True,
                   "image": "re4-d1.iso", "changes": {TARGET: "pixel fill"}}, handle, indent=1)
    print("built", target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
