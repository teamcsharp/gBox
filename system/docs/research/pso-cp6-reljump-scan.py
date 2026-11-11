"""CP6.1: find the dispatch table when it is a switch's RELATIVE-OFFSET table, not a pointer array.

The PowerPC compiler emits a big `switch` as a table of 4-byte offsets whose entries are resolved against the table (or each
entry's own) address with `bctr`. Two formulas are in common use:

    A: target_i = table_addr + 4 * i + offset_i        (offsets relative to each entry)
    B: target_i = table_addr + offset_i                (offsets relative to the table base)

The scan first collects runs of *small non-zero words* (|value| < 0x200000) - ordinary data rarely produces such runs - and then
tests both formulas, keeping a run when almost all of its targets land inside the text sections. The output is a candidate table
with its targets, so the handlers can be decompiled and named.
"""
import struct
import sys

sys.path.insert(0, r"C:\_tools\gBox\.tmp\main-repo\system")

from gbox.gcdisc import GCDisc  # noqa: E402

DISC = r"D:\gBox\cache\mods\436e0bb84d5337d1\pso_city_npc_moved\Phantasy Star Online Episode I & II Plus (USA).iso"
SMALL = 0x200000
MIN_RUN = 16
TOLERANCE = 0.95


def main():
    dol = GCDisc(DISC).read("PsoV3.dol")
    offs = struct.unpack_from(">18I", dol, 0x00)
    addrs = struct.unpack_from(">18I", dol, 0x48)
    sizes = struct.unpack_from(">18I", dol, 0x90)
    sections = [(offs[i], addrs[i], sizes[i]) for i in range(18) if sizes[i]]
    text = [(addrs[i], addrs[i] + sizes[i]) for i in range(18)
            if sizes[i] and 0x8000C000 <= addrs[i] <= 0x80433F20 and addrs[i] + sizes[i] <= 0x80433F20]

    def in_text(word: int) -> bool:
        return any(lo <= word < hi for lo, hi in text)

    def signed(word: int) -> int:
        return word - 0x100000000 if word & 0x80000000 else word

    candidates = []
    for file_off, addr, size in sections:
        i = 0
        while i + 4 <= size:
            value = struct.unpack_from(">I", dol, file_off + i)[0]
            if not (0 < abs(signed(value)) < SMALL):
                i += 4
                continue
            start, run = i, 0
            while i + 4 <= size:
                value = struct.unpack_from(">I", dol, file_off + i)[0]
                if not (0 < abs(signed(value)) < SMALL):
                    break
                run += 1
                i += 4
            if run >= MIN_RUN:
                table_addr = addr + start
                words = [struct.unpack_from(">I", dol, file_off + start + 4 * k)[0] for k in range(run)]
                offsets = [signed(w) for w in words]
                for label, targets in (
                        ("A", [table_addr + 4 * k + offsets[k] for k in range(run)]),
                        ("B", [table_addr + offsets[k] for k in range(run)])):
                    hits = sum(1 for t in targets if in_text(t))
                    if hits >= run * TOLERANCE:
                        candidates.append((table_addr, run, label, hits, len(set(targets)), targets[:8]))
                        break
            i = max(i, start + 4)
    candidates.sort(key=lambda c: (-c[3], -c[1]))
    print(f"relative-offset table candidates: {len(candidates)}")
    for where, run, label, hits, distinct, first in candidates[:14]:
        print(f"  {where:#010x}: {run} entries ({label}, {hits} in text, {distinct} distinct) "
              f"first {[hex(t) for t in first]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
