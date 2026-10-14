import struct

import numpy as np
import pytest

from gbox import ff7_models as F
from gbox.ff7_swap import BattleAtlas, lzs_encode, write_battle


def _fixture():
    # Same native TIM layout as Cloud, synthetic pixels and one untextured weapon.
    tim = (struct.pack('<II', 16, 8) + struct.pack('<I4H', 76, 0, 480, 16, 2)
           + bytes(64) + struct.pack('<I4H', 7692, 320, 0, 60, 64) + bytes(7680))
    mesh = struct.pack('<I', 24) + bytes(24) + bytes(16)
    parts = [struct.pack('<I HhI', 0, 0, 0, 12) + mesh, b'cfg!', b'anim', tim,
             struct.pack('<IHhI', 0, 0, 42, 12) + mesh]
    offsets = []
    at = 4 + len(parts)*4
    for p in parts:
        offsets.append(at)
        at += len(p)
    raw = struct.pack('<I5I', 5, *offsets) + b''.join(parts)
    return F.read_battle_model(lzs_encode(raw)), parts


def _primitive():
    texture = np.full((4, 4, 4), 255, np.uint8)
    texture[1:3, 1:3, :3] = (255, 0, 0)
    texture[0, 1, :3] = 0
    texture[0, 2, 3] = 0
    return {'tex': texture, 'color': (255, 255, 255, 255),
            'uv': np.array([(0, 0), (1, 0), (0, 1)])}


def test_atlas_retains_texture_interior_opaque_black_and_transparency():
    bm, _ = _fixture()
    p = _primitive()
    atlas = BattleAtlas(bm, [p])
    decoded = F.tim_rgba(F.read_tim(atlas.tim, 0), 0)
    assert tuple(decoded[1, 1]) == (255, 0, 0, 255)
    assert tuple(decoded[0, 1]) == (0, 0, 0, 255)
    assert decoded[0, 2, 3] == 0
    assert atlas.uv(p, [0, 1, 2]) == [(0, 0), (3, 0), (0, 3)]


def test_textured_native_roundtrip_preserves_animation_settings_and_weapon():
    bm, original = _fixture()
    p = _primitive()
    atlas = BattleAtlas(bm, [p])
    geo = {0: {'verts': [(0, 0, 0), (100, 0, 0), (0, 100, 0)], 'tris': [], 'quads': [],
               'texture_page': atlas.page, 'tex_tris': [((0, 1, 2), atlas.uv(p, [0, 1, 2]), atlas.clut)]}}
    raw, report = write_battle(bm, geo, atlas.tim)
    rebuilt = F.read_battle_model(lzs_encode(raw))
    mesh = rebuilt['bones'][0]['mesh']
    assert mesh['tt'] == [([0, 1, 2], [(0, 0), (3, 0), (0, 3)], 480 << 6)]
    assert mesh['tt_page'] == 5
    assert report['textured_triangles'] == report['triangles'] == 1
    assert report['gpu_buffer'] == 32
    assert report['budget_gpu_buffer'] == 0  # the synthetic stock mesh contains no draw primitives
    # Native battle renderer (0x80 model flag) reads the fourth index WORD as
    # texture brightness, not another vertex or padding. 0x80 is neutral PS1
    # texture modulation; zero turns even a white/red texel black.
    section = rebuilt['sections'][0]
    mesh_offset = struct.unpack_from('<I', raw, section + 8)[0]
    vertex_bytes = struct.unpack_from('<I', raw, section + mesh_offset)[0]
    polygon = section + mesh_offset + 4 + vertex_bytes + 4
    attributes = struct.unpack_from('<H', raw, polygon + 6)[0]
    brightness = attributes & 255
    source_texel = F.tim_rgba(rebuilt['tim'], 0)[1, 1, :3].astype(int)
    rendered = np.clip(source_texel * brightness // 128, 0, 255)
    assert tuple(rendered) == (255, 0, 0)
    assert attributes == 0x80  # no per-face packet/texture-page override bits
    ends = rebuilt['sections'][1:] + [len(raw)]
    for i in (1, 2, 4):
        assert raw[rebuilt['sections'][i]:ends[i]] == original[i]


def test_shared_weapon_textures_refuse_repainting():
    bm, _ = _fixture()
    bm['weapons'][0]['mesh']['tt'] = [([0, 1, 2], [(0, 0)]*3, 0)]
    with pytest.raises(ValueError, match='weapon textures share'):
        BattleAtlas(bm, [_primitive()])


def test_atlas_refuses_overflow_instead_of_discarding_or_resizing_detail():
    bm, _ = _fixture()
    p = _primitive()
    p['tex'] = np.full((65, 4, 4), 255, np.uint8)
    with pytest.raises(ValueError, match='exceeds'):
        BattleAtlas(bm, [p])
