"""Find a private, never-statically-referenced range of RE4 Switch's .bss (checkpoint E3).

    python scripts/verify_re4_bss.py <main.bin> [--size 0x1000] [--at 0xADDR] [--json] [--show 8]

The native harness needs private writable storage on the guest side - a mailbox, its generation guard, the call
arguments and the result word. The RE5/RE6 bootstrap allocates that from their engine's own allocator; RE4 is not
MT Framework and that allocator does not port, so the alternatives are RE4's own allocator (not identified) or a
`.bss` range the game never touches. The cave (`main+0x655880`) is executable code in the RX segment: it is an
install target only, never guest-writable, so it cannot hold the mailbox.

This tool does the static half of the `.bss` proof, from the image's own NSO header:

  1. every static reference into `.bss` is collected - `adrp` followed (within four instructions) by an `add`,
     `ldr`/`str`/`ldp`/`stp` or another immediate use on the same register, `adr`, and every 64-bit literal in
     `.text`/`.rodata`/`.rwdata`;
  2. the free stretches between those references are found, and the 4 KiB-aligned windows of at least `--size` bytes
     inside them are reported (the first `--show` of them, lowest address first);
  3. `--at <addr>` instead vets one chosen range (inside `.bss`, page-aligned, no static reference) and exits 0/1.

**It is not the whole proof.** A reference computed with a register index (`base + xN`), or a pointer written into
some object at run time, is invisible to a static scan. The chosen range must also read all-zero across three stage
loads on a live RE4 round (a read-only watch); only then may the controller use it. That watch is the request that
goes with this tool.
"""
from __future__ import annotations

import bisect
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gbox import nso_elf  # noqa: E402

SHIFT = 0x100
LINE = 64
PAGE = 0x1000
LOADS = ("ldr", "ldrb", "ldrh", "ldrsb", "ldrsh", "ldrsw", "ldur", "str", "strb", "strh", "stur", "ldp", "stp")


def layout(image: bytes) -> dict:
    """The section ranges the image's NSO header declares (main-relative virtual addresses)."""
    head = nso_elf.header(image)
    text = (head["text_memory"], head["text_memory"] + head["text_size"])
    rodata = (head["rodata_memory"], head["rodata_memory"] + head["rodata_size"])
    rwdata = (head["data_memory"], head["data_memory"] + head["data_size"])
    bss = (rwdata[1], rwdata[1] + head["bss_size"])
    if len(image) < SHIFT + rwdata[1]:
        raise nso_elf.NsoError("the image ends before the .rwdata section the header declares")
    return {"text": text, "rodata": rodata, "rwdata": rwdata, "bss": bss}


def references(image: bytes, sections: dict) -> list:
    """Every static reference that lands inside .bss: [{at, target, kind}], sorted by target."""
    from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM
    from capstone.arm64 import ARM64_OP_IMM, ARM64_OP_MEM, ARM64_OP_REG

    payload = image[SHIFT:]
    lo, hi = sections["bss"]
    out = []

    def inside(value):
        return lo <= value < hi

    text_end = sections["text"][1]
    md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    md.detail = True
    md.skipdata = True
    tracked = {}                         # register -> (page, instruction index)
    for index, ins in enumerate(md.disasm(payload[:text_end], 0)):
        try:
            mnem, ops = ins.mnemonic, ins.operands
        except Exception:                # a skipdata pseudo-instruction
            continue
        if mnem == "adrp" and len(ops) == 2:
            tracked[md.reg_name(ops[0].reg)] = (ops[1].imm, index)
            continue
        if mnem == "adr" and len(ops) == 2 and ops[1].type == ARM64_OP_IMM:
            if inside(ops[1].imm):
                out.append({"at": hex(ins.address), "target": hex(ops[1].imm), "kind": "adr"})
            continue
        if mnem == "add" and len(ops) == 3 and ops[2].type == ARM64_OP_IMM:
            src = md.reg_name(ops[1].reg)
            hit = tracked.get(src)
            if hit and index - hit[1] <= 4:
                target = hit[0] + ops[2].imm
                if inside(target):
                    out.append({"at": hex(ins.address), "target": hex(target), "kind": "adrp+add"})
                continue
        if mnem in LOADS:
            for op in ops:
                if op.type != ARM64_OP_MEM:
                    continue
                base = md.reg_name(op.mem.base)
                hit = tracked.get(base)
                if hit and index - hit[1] <= 4:
                    target = hit[0] + op.mem.disp
                    if inside(target):
                        out.append({"at": hex(ins.address), "target": hex(target), "kind": "adrp+mem"})
                    break
        # only the destination of this instruction stops holding an adrp page (a read operand keeps its value)
        if ops:
            try:
                if ops[0].type == ARM64_OP_REG:
                    tracked.pop(md.reg_name(ops[0].reg), None)
            except Exception:
                pass
    for region in ("text", "rodata", "rwdata"):
        rlo, rhi = sections[region]
        for off in range(rlo, min(rhi, len(payload)) - 7, 8):
            value = struct.unpack_from("<Q", payload, off)[0]
            if inside(value):
                out.append({"at": hex(off), "target": hex(value), "kind": "literal-64"})
    out.sort(key=lambda row: int(row["target"], 16))
    return out


def free_windows(sections: dict, refs: list, size: int) -> list:
    """Every 4 KiB-aligned `size`-byte window inside .bss with no static reference in it, lowest first."""
    lo, hi = sections["bss"]
    used = sorted(int(row["target"], 16) for row in refs)
    out = []
    start = (lo + PAGE - 1) // PAGE * PAGE
    for at in range(start, hi - size + 1, PAGE):
        end = at + size
        i = bisect.bisect_left(used, at)
        if i < len(used) and used[i] < end:
            continue
        out.append(at)
    return out


def largest_gap(sections: dict, refs: list) -> dict:
    """The longest stretch of .bss with no static reference into it (page-aligned start), and its size."""
    lo, hi = sections["bss"]
    used = sorted({int(row["target"], 16) for row in refs})
    best = {"at": lo, "size": 0}
    cursor = lo
    for target in used:
        if target > cursor and target - cursor > best["size"]:
            best = {"at": cursor, "size": target - cursor}
        cursor = max(cursor, target + 1)
    if hi > cursor and hi - cursor > best["size"]:
        best = {"at": cursor, "size": hi - cursor}
    raw_at, raw_size = best["at"], best["size"]
    aligned = (raw_at + PAGE - 1) // PAGE * PAGE
    return {"at": aligned, "size": max(0, raw_size - (aligned - raw_at))}


def evaluate(image: bytes, size: int = PAGE, at: int | None = None, show: int = 8) -> dict:
    if size <= 0 or size > PAGE:
        raise ValueError("--size must be between 1 and one page (4096)")
    sections = layout(image)
    refs = references(image, sections)
    bss_lo, bss_hi = sections["bss"]
    report = {"layout": sections, "bss": {"at": hex(bss_lo), "size": bss_hi - bss_lo},
              "references": len(refs), "reference_rows": refs[:40], "size": size}
    if at is not None:
        problems = []
        if not (bss_lo <= at < bss_hi):
            problems.append("the range does not start inside .bss")
        if at % PAGE:
            problems.append(f"the range does not start on a {PAGE}-byte page")
        if at + size > bss_hi:
            problems.append("the range does not fit inside .bss")
        hits = [row for row in refs if at <= int(row["target"], 16) < at + size]
        if hits:
            problems.append(f"{len(hits)} static reference(s) point into the range")
        report.update({"range": {"at": hex(at), "size": size}, "problems": problems,
                       "usable": not problems, "reason": "; ".join(problems)})
        return report
    windows = free_windows(sections, refs, size)
    gap = largest_gap(sections, refs)
    report.update({"candidates": [hex(w) for w in windows[:show]],
                   "last_candidates": [hex(w) for w in windows[-show:]] if windows else [],
                   "free_window_count": len(windows), "largest_gap": {"at": hex(gap["at"]), "size": gap["size"]},
                   "usable": bool(windows), "reason": "" if windows else "no free window of that size"})
    return report


def main(argv) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    size = int(argv[argv.index("--size") + 1], 0) if "--size" in argv else PAGE
    at = int(argv[argv.index("--at") + 1], 0) if "--at" in argv else None
    show = int(argv[argv.index("--show") + 1], 0) if "--show" in argv else 8
    image = Path(argv[1]).read_bytes()
    report = evaluate(image, size, at, show)
    report["ok"] = report["usable"]
    if "--json" in argv:
        print(json.dumps(report, indent=2))
    else:
        lay = report["layout"]
        for name in ("text", "rodata", "rwdata", "bss"):
            lo, hi = lay[name]
            print(f"{name:7s} {lo:#010x}..{hi:#010x}  ({hi - lo:#x} bytes)")
        print(f"static references into .bss: {report['references']} (showing {len(report['reference_rows'])})")
        for row in report["reference_rows"][:10]:
            print(f"  {row['kind']:10s} at {row['at']} -> {row['target']}")
        if at is not None:
            print(f"range {report['range']['at']} size {size:#x}: "
                  + ("PASS - inside .bss, page-aligned, no static reference" if report["ok"]
                     else f"FAIL - {report['reason']}"))
        else:
            print(f"free {size:#x}-byte windows: {report['free_window_count']}; first: {report['candidates']}")
            print(f"  last: {report['last_candidates']}")
            print(f"  largest unreferenced stretch: {report['largest_gap']['at']} "
                  f"({report['largest_gap']['size']:#x} bytes)")
            print("verdict:", "PASS - candidates exist (static half only; the live zero watch is still required)"
                  if report["ok"] else "FAIL - no free window of that size")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
