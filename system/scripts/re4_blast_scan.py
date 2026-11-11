"""RE4 Switch (010099A00BC1E000) static blast-entry scanner (checkpoint G3's tooling).

    python scripts/re4_blast_scan.py [main.bin]

Read-only capstone scan of the extracted Switch main: every `bl 0x33B770` (AREA_ATTACK) site with the effect ids
(`mov w5, #id` before an EFFECT call), the sound id, the attack class and the float radius the site loads, plus every
rodata qword that points into the blast cluster (`0x2E4000..0x2E6000`, the blast spawn functions the F1 verifier pins).
The three known RE4 blasts (`main+0x2E48B0` hand, `0x2E4AA0` simple, `0x2E4E50` flash) are the baseline; G3's
incendiary is the entry that differs. Nothing here writes or runs game code.
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

TEXT_END = 0x655850
RODATA_START, RODATA_END = 0x656000, 0xAE1BCC
AREA_ATTACK, EFFECT, SOUND = 0x33B770, 0x1F7DC0, 0x261C20
BLAST_LO, BLAST_HI = 0x2E4000, 0x2E6000
KNOWN = {0x2E48B0: "hand", 0x2E4AA0: "simple", 0x2E4E50: "flash"}


def bl_target(text: bytes, addr: int) -> int | None:
    word = struct.unpack_from("<I", text, addr)[0]
    if word >> 26 != 0b100101:
        return None
    off = word & 0x3FFFFFF
    if off & 0x2000000:
        off -= 0x4000000
    return (addr + off * 4) & 0xFFFFFFFF


def scan(image: bytes) -> dict:
    """{sites: [...], slots: [...], blasts: {fn: name}} - every area-attack site and every blast-cluster slot."""
    from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM
    text = image[0x100:0x100 + TEXT_END]
    md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    md.detail = True
    sites = []
    for site in range(0, len(text) - 4, 4):
        if bl_target(text, site) != AREA_ATTACK:
            continue
        page, effects, sounds, klass, radius = None, [], [], None, []
        for ins in md.disasm(text[max(0, site - 0x80):site + 4], max(0, site - 0x80)):
            if ins.mnemonic == "adrp":
                try:
                    page = int(ins.op_str.split(", #")[1], 0)
                except (IndexError, ValueError):
                    page = None
            elif ins.mnemonic == "ldr" and page is not None and ins.op_str.startswith("s0, [x"):
                try:
                    at = page + int(ins.op_str.rsplit("#", 1)[1].rstrip("]"), 0)
                    radius.append((at, struct.unpack_from("<f", image, at + 0x100)[0]))
                except (IndexError, ValueError, struct.error):
                    pass
                page = None
            elif ins.mnemonic == "mov":
                if ins.op_str.startswith("w5, #"):
                    effects.append(int(ins.op_str.rsplit("#", 1)[1], 0))
                elif ins.op_str.startswith("w1, #"):
                    sounds.append(int(ins.op_str.rsplit("#", 1)[1], 0))
                elif ins.op_str.startswith("w3, #"):
                    klass = int(ins.op_str.rsplit("#", 1)[1], 0)
        sites.append({"site": site, "class": klass, "effects": effects[-2:], "sounds": sounds[-2:],
                      "radius": [(hex(at), round(value, 1)) for at, value in radius[-2:]]})
    slots = []
    if len(image) >= RODATA_END + 0x100:               # a whole image: the rodata slot table is scanable
        for off in range(RODATA_START, RODATA_END - 8, 8):
            value = struct.unpack_from("<Q", image, off + 0x100)[0]
            if BLAST_LO <= value < BLAST_HI:
                slots.append({"slot": off, "fn": value})
    blasts = {}
    for entry in slots:
        name = KNOWN.get(entry["fn"])
        if name:
            blasts[entry["fn"]] = name
    return {"sites": sites, "slots": slots, "blasts": blasts}


def report(image: bytes) -> list[str]:
    data = scan(image)
    lines = [f"area-attack sites: {len(data['sites'])}", f"blast-cluster slots: {len(data['slots'])}",
             "known blasts: " + ", ".join(f"{fn:#x} ({name})" for fn, name in sorted(data["blasts"].items()))]
    for entry in data["slots"]:
        if entry["fn"] not in KNOWN:
            lines.append(f"  unclaimed slot {entry['slot']:#x} -> {entry['fn']:#x}")
    return lines


def main(argv) -> int:
    path = Path(argv[1]) if len(argv) > 1 else Path("main.bin")
    if not path.is_file():
        print(f"missing image: {path}")
        return 2
    for line in report(path.read_bytes()):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

