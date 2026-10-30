"""Native inventory storage is independent of the nine visible UI positions."""
import struct

from gbox.mercs.titles import re5_switch as R


def test_visible_main_weapon_in_later_native_record_is_observed():
    player = 0x200000000
    raw = bytearray(24 * 0x38)
    # A native add can use any free physical record. It places the gun at UI
    # grid zero; neither its storage index nor the UI position is a D-pad key.
    off = 15 * 0x38
    struct.pack_into('<I', raw, off + 8, 0x119)
    struct.pack_into('<ii', raw, off + 12, 30, 30)
    struct.pack_into('<ii', raw, off + 28, 0, 1)
    raw[off + 0x2d] = 1

    class Memory:
        def rd(self, address, size):
            assert address == player + 0x30f0
            assert size <= len(raw), 'Reader must stay within the native manager'
            return bytes(raw[:size])

    result = R.inventory(Memory(), player)
    assert len(result) == 1
    gun = result[0]
    assert (gun['slot'], gun['grid'], gun['id'], gun['hand']) == (15, 0, 0x119, True)
    assert gun['addr'] == player + 0x30f0 + off
