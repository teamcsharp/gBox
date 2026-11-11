"""CP6.1: candidate dispatch tables - runs of consecutive words that point into the executable's text."""
import struct
import sys

sys.path.insert(0, r"C:\_tools\gBox\.tmp\main-repo\system")

from gbox.gcdisc import GCDisc  # noqa: E402

DISC = r"D:\gBox\cache\mods\436e0bb84d5337d1\pso_city_npc_moved\Phantasy Star Online Episode I & II Plus (USA).iso"


def main():
    dol = GCDisc(DISC).read("PsoV3.dol")
    offs = struct.unpack_from(">18I", dol, 0x00)
    addrs = struct.unpack_from(">18I", dol, 0x48)
    sizes = struct.unpack_from(">18I", dol, 0x90)
    sections = [(offs[i], addrs[i], sizes[i]) for i in range(18) if sizes[i]]
    text = [(addrs[i], addrs[i] + sizes[i]) for i in range(18)
            if sizes[i] and 0x80004000 <= addrs[i] < 0x80400000 and addrs[i] + sizes[i] <= 0x80433F20]
    print("text ranges:", [(hex(a), hex(b)) for a, b in text])

    def in_text(word: int) -> bool:
        return any(lo <= word < hi for lo, hi in text)

    found = []
    for file_off, addr, size in sections:
        if addr >= 0x80400000:                       # data-only; skip .bss-like tail
            pass
        limit = min(size, len(dol) - file_off)
        i = 0
        while i + 4 <= limit:
            if not in_text(struct.unpack_from(">I", dol, file_off + i)[0]):
                i += 4
                continue
            start, run = i, 0
            while i + 4 <= limit and in_text(struct.unpack_from(">I", dol, file_off + i)[0]):
                run += 1
                i += 4
            if run >= 6:
                words = [struct.unpack_from(">I", dol, file_off + start + 4 * k)[0] for k in range(min(run, 8))]
                found.append((addr + start, run, words))
            i = max(i, start + 4)
    found.sort(key=lambda f: -f[1])
    print(f"runs of >= 6 text pointers: {len(found)}")
    for where, run, words in found[:14]:
        print(f"  {where:#010x}: {run} pointers  first {[hex(w) for w in words[:5]]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
