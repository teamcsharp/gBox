"""CP9: find the instruction that stores the seed object pointer, stw rX,-0x4694(r13)."""
import struct
import sys

sys.path.insert(0, r"C:\_tools\gBox\.tmp\main-repo\system")
from gbox.gcdisc import GCDisc  # noqa: E402

DISC = r"D:\gBox\cache\mods\436e0bb84d5337d1\pso_city_npc_moved\Phantasy Star Online Episode I & II Plus (USA).iso"


def main():
    dol = GCDisc(DISC).read("PsoV3.dol")
    offs, addrs, sizes = (struct.unpack_from(">18I", dol, o) for o in (0x00, 0x48, 0x90))
    secs = [(offs[i], addrs[i], sizes[i]) for i in range(18) if sizes[i]]
    want_ra, want_imm = 13, 0xB96C          # stw rX, -0x4694(r13): imm16 = -0x4694 & 0xFFFF
    hits = []
    for file_off, addr, size in secs:
        if addr >= 0x80434000:              # code sections only
            continue
        for i in range(0, size - 3, 4):
            word = struct.unpack_from(">I", dol, file_off + i)[0]
            if (word & 0xFC1F0000) == 0x900D0000 and (word & 0x0000FFFF) == want_imm:
                hits.append((addr + i, word, (word >> 21) & 0x1F))
            elif (word & 0xFC1F0000) == 0x900D0000 and (word & 0x0000FFFF) == 0xB96C:
                hits.append((addr + i, word, (word >> 21) & 0x1F))
    print(f"stores to -0x4694(r13): {len(hits)}")
    for va, word, rs in hits[:10]:
        print(f"  {va:#010x} word {word:#010x} (rS={rs})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
