"""CP6.2: the GC n.rel directory (0x18-byte entries) and the fmt2 block header."""
import struct
import sys

sys.path.insert(0, r"C:\_tools\gBox\.tmp\main-repo\system")
from gbox.gcdisc import GCDisc  # noqa: E402

DISC = r"D:\gBox\cache\mods\436e0bb84d5337d1\pso_city_npc_moved\Phantasy Star Online Episode I & II Plus (USA).iso"


def main():
    d = GCDisc(DISC)
    data = d.read("Scene/map_aancient01_00n.rel")
    print(f"n.rel {len(data)} bytes")
    print(f"{'off':>7} {'tag':>6} {'words 1..5':<44} ascii")
    for i in range(16):
        off = i * 0x18
        w = struct.unpack_from(">6I", data, off)
        tail = data[off:off + 0x18]
        print(f"{off:#07x} {w[0]:#06x} {[hex(x) for x in w[1:6]]!s:<44} "
              f"{''.join(chr(b) if 32 <= b < 127 else '.' for b in tail)}")
    tag = data.find(b"fmt2")
    print(f"\nfmt2 at {tag:#x}; 0x40 bytes from tag-0x20:")
    for off in range(tag - 0x20, tag + 0x40, 16):
        chunk = data[off:off + 16]
        print(f"  {off:#07x} {chunk.hex(' ')}  {''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)}")
    print("\nfmt2 block as u32 BE from tag-0x20:")
    for off in range(tag - 0x20, tag + 0x40, 4):
        print(f"  {off:#07x} {struct.unpack_from('>I', data, off)[0]:#010x}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
