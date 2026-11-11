"""CP6.1/CP7: find code that loads object+0x84 (the event number) and check what it does with it.

PowerPC `lwz rD, 0x84(rA)` = opcode 32 (0x80000000) | rD<<21 | rA<<16 | 0x0084.
"""
import struct
import sys

sys.path.insert(0, r"C:\_tools\gBox\.tmp\main-repo\system")
from gbox.gcdisc import GCDisc  # noqa: E402

DISC = r"D:\gBox\cache\mods\436e0bb84d5337d1\pso_city_npc_moved\Phantasy Star Online Episode I & II Plus (USA).iso"


def main():
    dol = GCDisc(DISC).read("PsoV3.dol")
    offs, addrs, sizes = (struct.unpack_from(">18I", dol, o) for o in (0x00, 0x48, 0x90))
    secs = [(offs[i], addrs[i], sizes[i]) for i in range(18) if sizes[i]]
    hits = []
    for file_off, addr, size in secs:
        if addr >= 0x80434000:                    # code sections only
            continue
        for i in range(0, size - 3, 4):
            word = struct.unpack_from(">I", dol, file_off + i)[0]
            if (word & 0xFC000000) == 0x80000000 and (word & 0xFFFF) == 0x0084:
                hits.append(addr + i)
    print(f"lwz ...,0x84(..) instructions: {len(hits)}")
    for va in hits[:24]:
        print(f"  {va:#010x}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
