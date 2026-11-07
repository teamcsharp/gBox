"""Rename the font directory in the FST to `Font/` AND fill the glyph bitmap, in one build.

The DOL names `Font/common_p.fnt` with a capital F; the disc's FST says `font/`. If that lookup is case-sensitive, the game
never opens the file the patches filled - so two changes go in together: the name (a single byte in the FST's name table,
same length, so nothing moves) and the glyph data.

Outcomes, and what each means:

* text becomes blocks -> case mattered, and archive patching works; the model archives were failing for a different reason
* text unchanged      -> case is not it, and the patch/read path needs a different explanation again
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
OUT = os.path.expanduser("~/gBox_alt/gbox-cache/mods/78ab9efa2e310db4/re4gc-fontcase")
FONT = "font/common_p.fnt"


def tpl_data_start(blob: bytes) -> int:
    at = blob.find(b"\x00\x20\xaf\x30")
    if at < 0:
        raise ValueError("no TPL")
    _, count, header_size = struct.unpack_from(">III", blob, at)
    return at + max(header_size, 0x0C + 8 * count)


def main() -> int:
    disc = GCDisc(SRC)
    fst_off, fst_size = struct.unpack(">II", disc._r(0x424, 8))
    fst = bytearray(disc._r(fst_off, fst_size))
    count = struct.unpack_from(">I", fst, 8)[0]
    names_at = count * 12
    renamed = []
    for i in range(1, count):
        word, a, b = struct.unpack_from(">III", fst, i * 12)
        is_dir, name_off = word >> 24, word & 0xFFFFFF
        start = names_at + name_off
        end = fst.index(b"\0", start)
        name = fst[start:end]
        if name == b"font":
            fst[start] = ord("F")
            renamed.append(name.decode())
    print(f"FST: {count} entries, name table at {names_at} | renamed directories: {renamed}")

    offset, size = disc.files[FONT] if FONT in disc.files else disc.files[FONT]
    blob = bytearray(disc._r(offset, size))
    data_at = tpl_data_start(blob)
    blob[data_at:] = b"\xff" * (len(blob) - data_at)
    print(f"{FONT}: offset {offset} size {size} | filled {len(blob) - data_at} bytes of glyphs")

    os.makedirs(OUT, exist_ok=True)
    target = os.path.join(OUT, "re4-d1.iso")
    if not os.path.isfile(target) or os.path.getsize(target) != os.path.getsize(SRC):
        print("copying the disc (1.4 GB)...", flush=True)
        shutil.copyfile(SRC, target)
    with open(target, "r+b") as handle:
        handle.seek(fst_off)
        handle.write(bytes(fst))
        handle.seek(offset)
        handle.write(bytes(blob))
    with open(os.path.join(OUT, ".gbox-mod.json"), "w", encoding="utf-8") as handle:
        json.dump({"name": os.path.basename(OUT), "note": "font dir renamed Font/ and glyphs filled (case test)",
                   "built": str(time.time()), "game_id": "78ab9efa2e310db4", "kind": "file", "launchable": True,
                   "image": "re4-d1.iso", "changes": {"FST font/ -> Font/": "rename", FONT: "glyph fill"}},
                  handle, indent=1)
    print("built", target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
