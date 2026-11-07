"""Fill EVERY font's glyph bitmap in one build.

One font proved nothing because the title screen may use another. With every `font/*.fnt` filled, no screen can be drawing
unpatched glyphs, so the result is decisive either way: text in blocks means rebuilt files are read, normal text means they
are not.
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
OUT = os.path.expanduser("~/gBox_alt/gbox-cache/mods/78ab9efa2e310db4/re4gc-fontall")


def tpl_data_start(blob: bytes) -> int:
    at = blob.find(b"\x00\x20\xaf\x30")
    if at < 0:
        raise ValueError("no TPL")
    _, count, header_size = struct.unpack_from(">III", blob, at)
    return at + max(header_size, 0x0C + 8 * count)


def main() -> int:
    disc = GCDisc(SRC)
    fonts = {key: value for key, value in disc.files.items() if key.startswith("font/")}
    print(f"fonts on the disc: {len(fonts)}")
    plan = []
    for key, (offset, size) in sorted(fonts.items()):
        blob = bytearray(disc._r(offset, size))
        try:
            data_at = tpl_data_start(blob)
        except ValueError:
            print(f"  {key}: no TPL, skipped")
            continue
        blob[data_at:] = b"\xff" * (len(blob) - data_at)
        plan.append((key, offset, bytes(blob), len(blob) - data_at))
    print(f"fonts to write: {len(plan)}")
    os.makedirs(OUT, exist_ok=True)
    target = os.path.join(OUT, "re4-d1.iso")
    if not os.path.isfile(target) or os.path.getsize(target) != os.path.getsize(SRC):
        print("copying the disc (1.4 GB)...", flush=True)
        shutil.copyfile(SRC, target)
    with open(target, "r+b") as handle:
        for key, offset, blob, filled in plan:
            handle.seek(offset)
            handle.write(blob)
            print(f"  wrote {key} ({filled} bytes filled)", flush=True)
    with open(os.path.join(OUT, ".gbox-mod.json"), "w", encoding="utf-8") as handle:
        json.dump({"name": os.path.basename(OUT), "note": "every font glyph bitmap filled (decisive read test)",
                   "built": str(time.time()), "game_id": "78ab9efa2e310db4", "kind": "file", "launchable": True,
                   "image": "re4-d1.iso", "changes": {key: "glyph fill" for key, *_ in plan}}, handle, indent=1)
    print("built", target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
