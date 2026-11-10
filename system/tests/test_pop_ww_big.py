import os
import struct

import pytest

from gbox.pop_ww_big import parse_toc, BigError, payload_size

GCZ = "/mnt/gbox/hyperspin/Arcade/collections/Nintendo GameCube/roms/Prince of Persia - Warrior Within (USA).gcz"


def _synthetic():
    head = b"BIG\0" + struct.pack("<II", 0x26, 3) + b"\0" * (0x44 - 12)
    for off, key in ((0x1000, 1), (0x2000, 2), (0x3800, 3)):
        head += struct.pack("<II", off, key)
    return head


def test_synthetic_toc():
    v, e = parse_toc(_synthetic(), 0x5000)
    assert v == 0x26 and [x.offset for x in e] == [0x1000, 0x2000, 0x3800]
    assert [x.slot_size for x in e] == [0x1000, 0x1800, 0x1800]
    with pytest.raises(BigError):
        parse_toc(b"XXXX" + _synthetic()[4:], 0x5000)
    with pytest.raises(BigError):
        parse_toc(_synthetic(), 0x2000)


@pytest.mark.skipif(not os.path.exists(GCZ), reason="owned GCZ not present")
def test_owned_prince_bf_toc():
    from gbox.pop_ww_inventory import PoPWWDisc
    from gbox.pop_ww_big import open_from_disc
    with PoPWWDisc(GCZ) as d:
        base, size, version, entries = open_from_disc(d)
        assert (base, size, version, len(entries)) == (438532488, 343834624, 0x26, 2490)
        assert entries[0].offset == 0x2565800 and entries[-1].offset == 0x147e7800
        for e in entries:
            n = payload_size(d.read_range(base + e.offset, 4))
            assert n + 4 <= e.slot_size < n + 4 + 0x800
