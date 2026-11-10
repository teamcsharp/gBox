"""Vet RE4 Switch's native code cave against an extracted `main` image.

    python tools/verify_re4_caves.py <main.bin> [--json] [--at 0xADDR] [--size N]

`main.bin` is the NSO0 image with its sections expanded (Citron's `dump_nso`, or `main` through
`hactool -t nso --uncompressed` / `gbox.switch_extract exefs`): file offset = virtual address + 0x100. Every range
below comes from the image's own NSO header, never from a guess:

    .text   [0, text_size)              the instructions the header declares
    padding [text_size, RX page end)    the tail of the executable mapping: zero bytes, never an instruction
    .rodata [rodata_memory, +size)
    .rwdata [data_memory, +size)
    .bss    [data_memory + data_size, +bss_size)

The cave must start on a fresh 64-byte line in that tail padding (the first one after the declared `.text`), so the
first instruction of an install never shares a line with executed code - RE4 runs under NCE, whose cores have no
instruction-cache coherency (`CTR_EL0 = 0x9444C004`), so a rewritten line is a hang, not a stale read.

What it proves, exactly as checkpoint E1 asks:

  1. the whole cave range is zero (the install refuses anything else);
  2. no direct branch (B/BL), ADR or ADRP+ADD anywhere in `.text` targets it;
  3. no 64-bit literal anywhere in `.text`/`.rodata`/`.rwdata` holds an address inside it;
  4. the cave starts 64-byte aligned and lies inside the RX mapping the header declares.

Static evidence only: it cannot prove no indirect jump or computed address lands there, so the controller still treats
a nonzero cave as occupied and never overwrites one.
"""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gbox import nso_elf  # noqa: E402

SHIFT = 0x100                      # payload offset of a hactool/Citron `main` image
LINE = 64                          # the NCE instruction-cache line (IminLine = 64 bytes)
PAGE = 0x1000


def _sxt(value: int, bits: int) -> int:
    return value - (1 << bits) if value & (1 << (bits - 1)) else value


def layout(image: bytes) -> dict:
    """The section ranges the image's NSO header declares (addresses are main-relative virtual addresses)."""
    head = nso_elf.header(image)
    text = (head["text_memory"], head["text_memory"] + head["text_size"])
    rodata = (head["rodata_memory"], head["rodata_memory"] + head["rodata_size"])
    data = (head["data_memory"], head["data_memory"] + head["data_size"])
    bss = (data[1], data[1] + head["bss_size"])
    out = {"header_bytes": SHIFT, "text": text, "rodata": rodata, "rwdata": data, "bss": bss,
           "image_bytes": len(image), "payload_bytes": max(0, len(image) - SHIFT)}
    if len(image) < SHIFT + data[1]:
        raise nso_elf.NsoError("the image ends before the .rwdata section the header declares")
    return out


def default_cave(sections: dict) -> tuple[int, int, str]:
    """(address, size, why) for the first 64-byte line of the executable mapping's tail padding.

    The tail is the RX-mapping page after the declared `.text`, capped at the next section (`.rodata`); a section
    that starts earlier than the page end simply leaves less padding, and a page-aligned `.text` leaves none.
    """
    text_lo, text_end = sections["text"]
    mapping_end = ((text_end + PAGE - 1) // PAGE) * PAGE
    stop = min(mapping_end, sections["rodata"][0])
    start = ((text_end + LINE - 1) // LINE) * LINE
    size = max(0, stop - start)
    why = (f"the first {LINE}-byte line after the declared .text end {text_end:#x}, "
           f"inside the RX mapping page ending {mapping_end:#x}"
           + ("" if stop == mapping_end else f" (capped by .rodata at {stop:#x})"))
    return start, size, why


def scan(image: bytes, ranges, sections: dict) -> dict:
    """References into `ranges` from the code and the relocated data of the image."""
    payload = image[SHIFT:]

    def inside(target):
        return next((name for at, size, name in ranges if at <= target < at + size), None)

    hits = []
    text_lo, text_end = sections["text"]
    for pc in range(0, min(text_end, len(payload)) - 3, 4):
        word = struct.unpack_from("<I", payload, pc)[0]
        if (word & 0xFC000000) in (0x14000000, 0x94000000):                  # B / BL
            target = pc + _sxt(word & 0x3FFFFFF, 26) * 4
        elif (word & 0x9F000000) == 0x90000000:                              # ADRP (+ADD soon after)
            rd = word & 31
            imm = _sxt(((word >> 5) & 0x7FFFF) << 2 | ((word >> 29) & 3), 21) << 12
            page = (pc & ~0xFFF) + imm
            target = None
            for step in (4, 8, 12):                                          # the ADD usually follows at once
                nxt = struct.unpack_from("<I", payload, pc + step)[0]
                if (nxt & 0x7F800000) == 0x11000000 and (nxt & 31) == rd and ((nxt >> 5) & 31) == rd:
                    target = page + ((nxt >> 10) & 0xFFF) * (4096 if (nxt >> 22) & 1 else 1)
                    break
            if target is None:
                continue
        elif (word & 0x9F000000) == 0x10000000:                              # ADR
            target = pc + _sxt(((word >> 5) & 0x7FFFF) << 2 | ((word >> 29) & 3), 21)
        else:
            continue
        name = inside(target)
        if name:
            hits.append({"cave": name, "at": hex(pc), "kind": "instruction", "target": hex(target)})
    for region in ("text", "rodata", "rwdata"):
        lo, hi = sections[region]
        hi = min(hi, len(payload))
        for off in range(lo, hi - 7, 8):
            value = struct.unpack_from("<Q", payload, off)[0]
            name = inside(value)
            if name:
                hits.append({"cave": name, "at": hex(off), "kind": "literal-64", "target": hex(value)})
    return {"references": hits,
            "holes": {name: not any(payload[at:at + size]) for at, size, name in ranges},
            "aligned": {name: at % LINE == 0 for at, size, name in ranges},
            "in_mapping": {name: text_lo <= at and at + size <= ((text_end + PAGE - 1) // PAGE) * PAGE
                           for at, size, name in ranges}}


def evaluate(image: bytes, cave: tuple[int, int, str] | None = None) -> dict:
    """The full verdict for one cave (default: the aligned tail padding of `.text`)."""
    sections = layout(image)
    at, size, why = cave or default_cave(sections)
    if size <= 0:
        return {"layout": sections, "cave": {"at": hex(at), "size": 0, "why": why},
                "usable": False, "reason": "the declared .text leaves no tail padding in its RX page",
                "references": [], "holes": {}, "aligned": {}, "in_mapping": {}}
    block = scan(image, [(at, size, "re4_cave")], sections)
    usable = block["holes"]["re4_cave"] and block["aligned"]["re4_cave"] and \
        block["in_mapping"]["re4_cave"] and not block["references"]
    reason = ""
    if not block["holes"]["re4_cave"]:
        reason = "the cave range is not all zero"
    elif not block["aligned"]["re4_cave"]:
        reason = f"the cave does not start on a {LINE}-byte line"
    elif not block["in_mapping"]["re4_cave"]:
        reason = "the cave is not inside the declared executable mapping"
    elif block["references"]:
        reason = "code or a literal points into the cave"
    return {"layout": sections, "cave": {"at": hex(at), "size": size, "why": why}, "usable": usable,
            "reason": reason, **block}


def main(argv) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    image = Path(argv[1]).read_bytes()
    cave = None
    if "--at" in argv:
        at = int(argv[argv.index("--at") + 1], 0)
        size = int(argv[argv.index("--size") + 1], 0) if "--size" in argv else None
        if size is None:
            raise SystemExit("--at needs --size")
        cave = (at, size, "the range given on the command line")
    report = evaluate(image, cave)
    report["sha256"] = __import__("hashlib").sha256(image).hexdigest()
    report["ok"] = report["usable"]
    if "--json" in argv:
        print(json.dumps(report, indent=2))
    else:
        lay = report["layout"]
        for name in ("text", "rodata", "rwdata", "bss"):
            lo, hi = lay[name]
            print(f"{name:7s} {lo:#010x}..{hi:#010x}  ({hi - lo:#x} bytes)")
        print(f"cave    {report['cave']['at']} size {report['cave']['size']:#x} - {report['cave']['why']}")
        print(f"holes={report['holes']} aligned={report['aligned']} in_mapping={report['in_mapping']}")
        print(f"references={report['references'] or 'none'}")
        print("verdict:", ("PASS - the cave is unused zero padding in the RX tail" if report["ok"]
                           else f"FAIL - {report['reason']}"))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
