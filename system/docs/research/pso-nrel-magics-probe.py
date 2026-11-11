"""CP6.2/CP7.3: the n.rel magic table at 0x804c8b08 - magics and handlers - checked against the real files."""
import struct
import sys

sys.path.insert(0, r"C:\_tools\gBox\.tmp\main-repo\system")
from gbox.gcdisc import GCDisc  # noqa: E402

DISC = r"D:\gBox\cache\mods\436e0bb84d5337d1\pso_city_npc_moved\Phantasy Star Online Episode I & II Plus (USA).iso"
SECTIONS = None


def sections(dol):
    offs, addrs, sizes = (struct.unpack_from(">18I", dol, o) for o in (0x00, 0x48, 0x90))
    return [(offs[i], addrs[i], sizes[i]) for i in range(18) if sizes[i]]


def off_of(dol, va):
    for f, a, s in sections(dol):
        if a <= va < a + s:
            return f + (va - a)
    return None


def cstr(dol, va, limit=64):
    off = off_of(dol, va)
    if off is None:
        return None
    end = dol.find(b"\x00", off, off + limit)
    return dol[off:end].decode("latin-1", "replace") if end > off else None


def main():
    dol = GCDisc(DISC).read("PsoV3.dol")
    table = 0x804C8B08
    print(f"table at {table:#x}, file {off_of(dol, table):#x}")
    for i in range(32):
        magic_va, handler_va = struct.unpack_from(">II", dol, off_of(dol, table) + 8 * i)
        if magic_va == 0:
            print(f"  [{i}] terminator")
            break
        print(f"  [{i}] magic_va={magic_va:#x} handler={handler_va:#x} magic={cstr(dol, magic_va)!r}")
    # the real files' first bytes
    d = GCDisc(DISC)
    for name in ("Scene/map_aancient01_00n.rel", "Scene/map_aancient01_00r.rel", "Scene/map_aancient01_00c.rel"):
        data = d.read(name)
        print(f"\n{name}: {len(data)} bytes, first 16: {data[:16].hex(' ')} ascii "
              f"{''.join(chr(b) if 32 <= b < 127 else '.' for b in data[:16])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
