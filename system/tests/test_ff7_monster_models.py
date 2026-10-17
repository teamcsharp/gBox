import struct

from gbox import ff7_models as F
from gbox.ff7_swap import lzs_encode


def _tim():
    # Same native TIM layout as the synthetic party model in test_ff7_battle_textures.
    return (struct.pack('<II', 16, 8) + struct.pack('<I4H', 76, 0, 480, 16, 2)
            + bytes(64) + struct.pack('<I4H', 7692, 320, 0, 60, 64) + bytes(7680))


def _skeleton():
    # One root bone and an empty mesh (0 vertex bytes, 4 empty polygon groups).
    mesh = struct.pack('<I', 24) + bytes(24) + bytes(16)
    return struct.pack('<I HhI', 0, 0, 0, 12) + mesh


def _model(*parts):
    offsets = []
    at = 4 + len(parts) * 4
    for p in parts:
        offsets.append(at)
        at += len(p)
    raw = struct.pack('<I%uI' % len(parts), len(parts), *offsets) + b''.join(parts)
    return F.read_battle_model(lzs_encode(raw))


def test_monster_tail_sections_are_not_weapons():
    # Vincent's limit-break forms (GALL/HELLMASK/DEATHGIG/CHAOS) end their section table with
    # a TIM-fill tail, not weapon sections. Each tail entry looks like a weapon header but its
    # u32 marker is non-zero (0x1A30) and its mesh offset lands past the end of the buffer.
    fill = struct.pack('<III', 0x1A30, 0x1A30, 0x1A30)            # _z=6704, wo=6704 -> out of bounds
    short = struct.pack('<I', 0)                                  # no room for a 12-byte weapon header
    zero_but_oob = struct.pack('<IHhI', 0, 0, 42, 1 << 20)        # _z == 0 but mesh offset past the end
    model = _model(_skeleton(), b'cfg!', b'anim', _tim(), fill, short, zero_but_oob)
    assert model['weapons'] == []


def test_real_weapon_sections_are_still_parsed():
    mesh = struct.pack('<I', 24) + bytes(24) + bytes(16)
    weapon = struct.pack('<IHhI', 0, 0, 42, 12) + mesh
    model = _model(_skeleton(), b'cfg!', b'anim', _tim(), weapon)
    assert len(model['weapons']) == 1
    assert model['weapons'][0]['length'] == 42
