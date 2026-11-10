"""Vet the two new RE6 class-image caves against a decompressed `main` image.

    python tools/verify_re6_classes.py <main.bin> [--json]

`main.bin` is what `hactool -t nso --uncompressed=main.bin main` (or
`gbox.switch_extract exefs <nsp> <program.nca> <out>` first) produces: the NSO header kept, so every virtual
address is at file offset `vaddr + 0x100` (`gbox.nso_elf`).

The derived class images live in `system/gbox/mercs/native/re6_061d2a06/classes.py` at `main+0x18F2BC0`
(spawn_class, 256 bytes) and `main+0x18F2CC0` (detonate_class, 232). This checks, on the operator's own image:

  1. both ranges are all zero (the install refuses anything else);
  2. no direct branch (B/BL), ADR, or ADRP+ADD pair in `.text` targets them;
  3. no 64-bit literal anywhere in `.text`/`.rodata` holds an address inside them;
  4. for context, the same facts about the four images already shipped (call/spawn/detonate/spawn_bomb).

Exit code 0 when both new caves pass. Static evidence only: it cannot prove no indirect jump lands there, so the
controller still treats a non-zero cave as occupied and never overwrites one.
"""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gbox.mercs.native.re6_061d2a06 import classes as C  # noqa: E402

SHIFT = 0x100
TEXT_END = 0x18F3000
RODATA_END = 0x25A4000
NEW_CAVES = (C.SPAWN_CLASS, C.DETONATE_CLASS)
SHIPPED_CAVES = ((0x18F2640, 536, "call"), (0x18F2880, 256, "spawn"),
                 (0x18F29C0, 232, "detonate"), (0x18F2AC0, 232, "spawn_bomb"))


def _sxt(value: int, bits: int) -> int:
    return value - (1 << bits) if value & (1 << (bits - 1)) else value


def scan(image: bytes, ranges) -> dict:
    def inside(target):
        return next((name for at, size, name in ranges if at <= target < at + size), None)

    hits = []
    text_end = min(TEXT_END, len(image))          # a truncated dump is scanned as far as it goes
    for pc in range(0, text_end - 3, 4):
        word = struct.unpack_from("<I", image, pc)[0]
        if (word & 0xFC000000) in (0x14000000, 0x94000000):                  # B / BL
            target = pc + _sxt(word & 0x3FFFFFF, 26) * 4
        elif (word & 0x9F000000) == 0x90000000:                              # ADRP + ADD
            rd = word & 31
            imm = _sxt(((word >> 5) & 0x7FFFF) << 2 | ((word >> 29) & 3), 21) << 12
            page = (pc & ~0xFFF) + imm
            nxt = struct.unpack_from("<I", image, pc + 4)[0]
            if not ((nxt & 0x7F800000) == 0x11000000 and (nxt & 31) == rd and ((nxt >> 5) & 31) == rd):
                continue
            target = page + ((nxt >> 10) & 0xFFF) * (4096 if (nxt >> 22) & 1 else 1)
        elif (word & 0x9F000000) == 0x10000000:                              # ADR
            target = pc + _sxt(((word >> 5) & 0x7FFFF) << 2 | ((word >> 29) & 3), 21)
        else:
            continue
        name = inside(target)
        if name:
            hits.append({"cave": name, "at": hex(pc), "kind": "instruction", "target": hex(target)})
    for region_end in (text_end, min(RODATA_END, len(image))):
        for off in range(0, region_end - 8, 8):
            value = struct.unpack_from("<Q", image, off)[0]
            name = inside(value)
            if name:
                hits.append({"cave": name, "at": hex(off), "kind": "literal-64", "target": hex(value)})
    return {"references": hits,
            "holes": {name: not any(image[at:at + size]) for at, size, name in ranges}}


def main(argv) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    image = Path(argv[1]).read_bytes()[SHIFT:]
    report = {"image_bytes": len(image)}
    new = scan(image, [(at, size, name) for at, name, size, _digest in NEW_CAVES])
    shipped = scan(image, [(at, size, name) for at, size, name in SHIPPED_CAVES])
    report["new_caves"] = new
    report["shipped_caves"] = shipped
    report["ok"] = all(new["holes"].values()) and not new["references"]
    if "--json" in argv:
        print(json.dumps(report, indent=2))
    else:
        for label, block in (("new", new), ("shipped", shipped)):
            print(f"{label}: holes={block['holes']}")
            print(f"{label}: references={block['references'] or 'none'}")
        print("verdict:", "PASS - both class images sit in unused zero padding" if report["ok"]
              else "FAIL - do not install there")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
