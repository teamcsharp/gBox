"""How many files' parsed offsets actually look like the file they claim to be?

`parse_fst` pairs each path with a file offset. If the pairing is wrong, every patch written through `GCDisc` lands on
unrelated bytes - and nothing complains: the write succeeds, the size matches, and the game never sees it.

This measures the pairing against the one thing a GC archive always carries: its magic. `.drs` files start `ca b6 be 20`,
so a parsed offset for a `.drs` path that does not start with it is a mispairing, not a modelling problem.

Usage: python3 probe_gc_fst_offsets.py [iso]
"""
import os
import struct
import sys

sys.path.insert(0, os.path.expanduser("~/gBox/system"))
from gbox.gcdisc import GCDisc

DRS = bytes.fromhex("cab6be20")
DEFAULT = os.path.expanduser("~/gBox_alt/re4-lab/gc/re4-d1.iso")


def main(argv=None) -> int:
    argv = argv or sys.argv[1:]
    path = argv[0] if argv else DEFAULT
    disc = GCDisc(path)
    rows = {"ok": [], "bad": []}
    for key, (offset, size) in disc.files.items():
        if not key.lower().endswith((".drs", ".das")):
            continue
        head = disc._r(offset, 4)
        rows["ok" if head == DRS else "bad"].append((key, offset, head.hex()))
    total = len(rows["ok"]) + len(rows["bad"])
    print(f"{os.path.basename(path)}: {total} archives | magic at parsed offset: {len(rows['ok'])} | "
          f"not the magic: {len(rows['bad'])}")
    for key, offset, head in rows["bad"][:12]:
        print(f"   {key:26s} offset {offset:>12} head {head}")
    if rows["bad"]:
        print("\nA parsed offset that does not carry the archive's magic means the path and the offset were paired "
              "wrongly by parse_fst: a patch written there changes unrelated bytes and the game never sees it.")
    # the raw tables, for the fix: entry 0's third word is the entry count, names follow the entries
    fst_off, fst_size = struct.unpack(">II", disc._r(0x424, 8))
    fst = disc._r(fst_off, fst_size)
    count = struct.unpack_from(">I", fst, 8)[0]
    print(f"FST: offset {fst_off} size {fst_size} | entry count {count} | entry table bytes {count * 12} | "
          f"name table bytes {fst_size - count * 12}")
    return 0 if not rows["bad"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
