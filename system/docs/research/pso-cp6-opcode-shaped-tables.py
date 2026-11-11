"""CP6.1: narrow the dispatch-table candidates to opcode-table shape.

An opcode table is: modest length (16..96), every target inside the event-script code region, and - the useful part - its
entries are *distinct functions* rather than one another's vtable slots. The known calibration cases are the five object
constructors at 0x8049eee8 (CP7.2) and the appearance of 0x8015bb8c..0x8018cbf0 (the "EVT NO" debug helpers) inside that
region.
"""
import struct
import sys

sys.path.insert(0, r"C:\_tools\gBox\.tmp\main-repo\system")

from gbox.gcdisc import GCDisc  # noqa: E402

DISC = r"D:\gBox\cache\mods\436e0bb84d5337d1\pso_city_npc_moved\Phantasy Star Online Episode I & II Plus (USA).iso"
MIN_RUN, MAX_RUN = 16, 96
EVT_LO, EVT_HI = 0x80140000, 0x801A0000          # where the event system's own code sits (CP6.1/CP7 findings)


def main():
    dol = GCDisc(DISC).read("PsoV3.dol")
    offs = struct.unpack_from(">18I", dol, 0x00)
    addrs = struct.unpack_from(">18I", dol, 0x48)
    sizes = struct.unpack_from(">18I", dol, 0x90)
    sections = [(offs[i], addrs[i], sizes[i]) for i in range(18) if sizes[i]]
    text = [(addrs[i], addrs[i] + sizes[i]) for i in range(18)
            if sizes[i] and 0x8000C000 <= addrs[i] <= 0x80433F20 and addrs[i] + sizes[i] <= 0x80433F20]
    if not text:
        text = [(0x8000C000, 0x80433F20)]

    def in_text(word: int) -> bool:
        return any(lo <= word < hi for lo, hi in text)

    hits = []
    for file_off, addr, size in sections:
        i = 0
        while i + 4 <= size:
            if not in_text(struct.unpack_from(">I", dol, file_off + i)[0]):
                i += 4
                continue
            start, run = i, 0
            while i + 4 <= size and in_text(struct.unpack_from(">I", dol, file_off + i)[0]):
                run += 1
                i += 4
            if MIN_RUN <= run <= MAX_RUN:
                words = [struct.unpack_from(">I", dol, file_off + start + 4 * k)[0] for k in range(run)]
                evt = sum(1 for w in words if EVT_LO <= w < EVT_HI)
                unique = len(set(words))
                if evt >= run * 0.6 and unique >= run * 0.6:
                    hits.append((addr + start, run, evt, unique, words[:6]))
            i = max(i, start + 4)
    hits.sort(key=lambda h: (-h[2], h[1]))
    print(f"opcode-shaped tables (16..96 entries, >=60% in the event region, >=60% distinct): {len(hits)}")
    for where, run, evt, unique, words in hits[:12]:
        print(f"  {where:#010x}: {run} entries, {evt} in {EVT_LO:#x}..{EVT_HI:#x}, {unique} distinct, "
              f"first {[hex(w) for w in words]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
