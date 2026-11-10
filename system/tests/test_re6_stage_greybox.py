"""RE6 stage greybox writer on synthetic fixtures: no game asset is read.

The fixture mirrors what was measured on s1208.arc: bone-less MOD v 0xD3 scene pieces under data\\stage\\sNNNN\\scr\\
whose parts use the float-position formats - a signed-byte normal at +12 and the albedo UV at +20 (0x2AE06DB8,
0x29F0B449), or no normal and the UV at +16 (0x37607D20); MRL v36 materials whose texture commands name tAlbedoMap by
its shader-object id (re6_switch_tex.texture_set_materials' decoding) and whose FTransparency selects
FTransparencyAlpha on the cut-out one; 0x2B albedos (BC3 holding Y'CbCr) in the measured Tegra layout; a 0x14 _NUKI
cut-out albedo; every entry a level-6 zlib stream in an ARC.
"""
import hashlib
import struct
import zlib

import numpy as np
import pytest
from PIL import Image

from gbox import mt_arc, mt_model, mtf_author, re6_stage_greybox as G, re6_switch_tex as T

SCOPE = 'data\\stage\\s1208\\scr\\scr00\\'
LIT, VERTEX, PLAIN = 0x2AE06DB8, 0x29F0B449, 0x37607D20


# --- fixtures -------------------------------------------------------------------------------------------------------

def albedo(width=32, height=32, rgb=(150, 100, 80), opacity=255):
    """A 0x2B TEX whose every mip is the colour through the Y'CbCr encoder (full mip chain)."""
    image = np.zeros((height, width, 4), np.uint8)
    image[..., :3], image[..., 3] = rgb, opacity
    levels = []
    for mip in range(max(width, height).bit_length()):
        w, h = max(1, width >> mip), max(1, height >> mip)
        levels.append(T.encode_albedo(Image.fromarray(image).resize((w, h)), opacity=True))
    return T.pack_tex(0x2B, width, height, levels)


def nuki(width=32, height=32):
    """A one-mip 0x14 TEX (the _NUKI cut-outs' format; no writer encodes it)."""
    size = width * height // 2
    header = b'TEX\0\xa1\x20\0\x20' + struct.pack('<3I', 1 | width << 6 | height << 19, 0x10001 | 0x14 << 8, size)
    return header + struct.pack('<I', 0) + bytes(n % 251 for n in range(size))


def pack(fmt, points, normals, uvs):
    stride = mt_model.fvf_stride(fmt)
    out = bytearray()
    for p, n, uv in zip(points, normals, uvs):
        record = bytearray(stride)
        struct.pack_into('<3f', record, 0, *p)
        if G.STAGE_LAYOUT[fmt]['normal'] is None:              # no s8 normal: packed junk at +12, UV at +16, colour
            struct.pack_into('<I', record, 12, 0xDFDFDFDF)
            struct.pack_into('<2e', record, 16, *uv)
            record[20:24] = bytes((200, 200, 200, 255))
        elif fmt not in (LIT, VERTEX):                          # the 2026-11-10 formats: normal +12, tangent +16, UV +20
            struct.pack_into('<4b', record, 12, *(max(-127, min(127, round(c * 127))) for c in n), -1)
            struct.pack_into('<4b', record, 16, 127, 0, 0, 127)
            struct.pack_into('<2e', record, 20, *uv)
        else:
            struct.pack_into('<4b', record, 12, *(max(-127, min(127, round(c * 127))) for c in n), -1)
            struct.pack_into('<4b', record, 16, 127, 0, 0, 127)
            struct.pack_into('<2e', record, 20, *uv)
            if fmt == LIT:
                struct.pack_into('<2e', record, 24, 0.5, 0.5)
            else:
                record[24:28] = bytes((200, 200, 200, 255))
        out += record
    return bytes(out)


def stage_mod(parts, materials):
    """A bone-less MOD v 0xD3 in the measured layout (test_re5_stage_greybox's, with this title's vertex packing)."""
    records, vertices, words, envelopes = b'', b'', [], b''
    for number, part in enumerate(parts):
        stride = mt_model.fvf_stride(part['fmt'])
        offset = len(vertices)
        vertices += pack(part['fmt'], part['points'], part['normals'], part['uvs'])
        strip = []
        for k, piece in enumerate(part['strips']):
            strip += ([0xFFFF] if k else []) + list(piece)
        record = bytearray(56)
        struct.pack_into('<HHI', record, 0, 0xFFFF, len(part['points']),
                         0 | part['material'] << 12 | part.get('lod', 0xFF) << 24)
        record[8:12] = bytes((1, 0, stride, 4))
        struct.pack_into('<II', record, 0x0C, 0, offset)
        struct.pack_into('>I', record, 0x14, part['fmt'])
        struct.pack_into('<III', record, 0x18, len(words), len(strip), 0)
        record[0x25] = 1
        struct.pack_into('<HHH', record, 0x26, number + 1, 0, len(part['points']) - 1)
        records += record
        words += strip + [0xFFFF]
        envelopes += mtf_author.pack_weight_bound(0, part['points'])
    if len(words) % 2 == 0:
        words.append(0)
    indices = struct.pack(f'<{len(words)}H', *words)
    every = [p for part in parts for p in part['points']]
    low = [min(p[a] for p in every) for a in range(3)]
    high = [max(p[a] for p in every) for a in range(3)]
    centre = [(a + b) / 2 for a, b in zip(low, high)]
    tail = struct.pack('<12f', *centre, 1000.0, *low, 0.0, *high, 0.0) + struct.pack('<5I', 500, 1000, 3, 0, len(parts))
    group_block = struct.pack('<I12x4f', 0, 0, 10, 0, 30)
    material_block = b''.join(name.encode().ljust(128, b'\0') for name in materials)
    blocks = (b'', group_block, material_block, records + envelopes, vertices, indices)
    offsets = [0]
    running = 0x28 + 56 + len(tail)
    for block in blocks[1:]:
        offsets.append(running)
        running += len(block)
    offsets.append(running)
    out = mt_model.MOD_MAGIC + bytes((0xD3, 0)) + struct.pack('<3H', 0, len(parts), len(materials))
    out += struct.pack('<3I2I2I', len(every), len(words), 9, len(vertices), 0, 1, 0)
    out += struct.pack('<7Q', *offsets) + tail + b''.join(blocks) + bytes(4)
    return out


def obj(name):
    """An MRL shader-object id: the 20-bit name hash over an index (re6_switch_tex.object_hash)."""
    return T.object_hash(name) << 12 | 7


def mrl36(materials, paths):
    """An MRL v36: `materials` is [(name, albedo path index (1-based), alpha_tested)]; 88-byte texture records with
    the path at +24, 72-byte materials (name hash +8, command bytes +12, blend +16, command count +28, region +56),
    24-byte commands (kind, value, object)."""
    table = 40 + len(paths) * 88
    cursor = (table + 72 * len(materials) + 15) & ~15
    raw = bytearray(cursor + 24 * 2 * len(materials))
    struct.pack_into('<4sIIIQQQ', raw, 0, b'MRL\0', 36, len(materials), len(paths), 0x1234, 40, table)
    for i, path in enumerate(paths):
        raw[40 + i * 88 + 24:40 + i * 88 + 24 + len(path)] = path.encode()
    for i, (name, texture, alpha) in enumerate(materials):
        base = table + 72 * i
        struct.pack_into('<II', raw, base + 8, zlib.crc32(name.encode()) ^ 0xFFFFFFFF, 48)
        struct.pack_into('<I', raw, base + 16, obj('BSSolid'))
        struct.pack_into('<I', raw, base + 28, 2)
        struct.pack_into('<Q', raw, base + 56, cursor)
        struct.pack_into('<IIQII', raw, cursor, T.KIND_TEXTURE, 0, texture, obj('tAlbedoMap'), 0)
        choice = obj('FTransparencyAlpha' if alpha else 'FTransparency')
        struct.pack_into('<IIQII', raw, cursor + 24, T.KIND_FUNCTION, 0, choice, obj('FTransparency'), 0)
        cursor += 48
    return bytes(raw)


def quad(x0, x1, y0, y1, z0, z1, axis_normal, uv_scale, up=True):
    """Two triangles over a rectangle (strip 0 1 2 3: counter-clockwise from the side its normal faces)."""
    if axis_normal == 'y':
        points = [(x0, y0, z0), (x0, y0, z1), (x1, y0, z0), (x1, y0, z1)]
        if not up:
            points = [points[0], points[2], points[1], points[3]]
        uvs = [(0, 0), (0, (z1 - z0) * uv_scale), ((x1 - x0) * uv_scale, 0), ((x1 - x0) * uv_scale, (z1 - z0) * uv_scale)]
        normal = (0.0, 1.0 if up else -1.0, 0.0)
    else:
        points = [(x0, y0, z0), (x1, y0, z0), (x0, y1, z0), (x1, y1, z0)]
        uvs = [(0, 0), ((x1 - x0) * uv_scale, 0), (0, (y1 - y0) * uv_scale), ((x1 - x0) * uv_scale, (y1 - y0) * uv_scale)]
        normal = (0.0, 0.0, 1.0)
    return {'points': points, 'normals': [normal] * 4, 'uvs': uvs, 'strips': [[0, 1, 2, 3]]}


def stage_arc(*, floor_tile_cm=400.0, wall_tile_cm=200.0, opacity=255, extra=()):
    """(archive, names): a floor on the lit format, a wall on the vertex-lit one (alpha-tested), a floor on the
    no-normal format, a sky piece, a _NUKI cut-out, a normal map and an untouched layout; `extra` appends
    (name, payload) entries."""
    floor = quad(0, 1600, 0, 0, 0, 800, 'y', 1.0 / floor_tile_cm) | {'fmt': LIT, 'material': 0, 'lod': 1}
    wall = quad(0, 600, 0, 300, 0, 0, 'z', 1.0 / wall_tile_cm) | {'fmt': VERTEX, 'material': 1, 'lod': 1}
    deck = quad(0, 500, 50, 50, 1000, 1500, 'y', 1.0 / 250.0) | {'fmt': PLAIN, 'material': 2, 'lod': 1}
    fish = quad(0, 100, 0, 100, 2000, 2000, 'z', 0.01) | {'fmt': VERTEX, 'material': 3, 'lod': 1}
    names = ('XfB_L__m00_1', 'XfBAW_0__m00_2', 'XfB_W__m00_3', 'XfBA0__m00_4')
    paths = [SCOPE + 'x_yuka_BM', SCOPE + 'x_kabe_BM', SCOPE + 'x_deck_BM', SCOPE + 'x_fish_NUKI', SCOPE + 'x_sky_dome_BM']
    piece = stage_mod([floor, wall, deck, fish], names)
    piece_mrl = mrl36([(names[0], 1, False), (names[1], 2, True), (names[2], 3, False), (names[3], 4, True)], paths)
    dome = quad(-5000, 5000, 3000, 3000, -5000, 5000, 'y', 0.0001, up=False) | {'fmt': LIT, 'material': 0, 'lod': 1}
    sky = stage_mod([dome], ('XfB__m00_9',))
    sky_mrl = mrl36([('XfB__m00_9', 5, False)], paths)
    contents = [(SCOPE + 'x_yuka_BM', albedo(64, 32, (90, 120, 60))),
                (SCOPE + 'x_kabe_BM', albedo(32, 32, (150, 100, 80), opacity)),
                (SCOPE + 'x_deck_BM', albedo(32, 32)),
                (SCOPE + 'x_sky_dome_BM', albedo(64, 32, (60, 90, 140))),
                (SCOPE + 'x_unused_BM', albedo(32, 32)),
                (SCOPE + 'x_fish_NUKI', nuki()),
                (SCOPE + 'x_yuka_NM', nuki()),
                ('soft\\stage\\s1208\\s1208_em00', b'XFS\0kept'),
                (SCOPE + 'piece', piece_mrl), (SCOPE + 'piece', piece),
                (SCOPE + 'sky', sky_mrl), (SCOPE + 'sky', sky), *extra]
    entries = [mt_arc.Entry(name=name, hash=0x241F5DEB, tag=0x40000000 | len(data), size=0, offset=0,
                            data=zlib.compress(data, 6)) for name, data in contents]
    return mt_arc.build(mt_arc.Arc(7, entries)), [name for name, _ in contents]


# --- the measurement ------------------------------------------------------------------------------------------------

def test_the_measured_layouts_give_positions_normals_and_the_albedo_uv():
    model = mt_model.parse_mod(stage_mod([quad(0, 400, 0, 0, 0, 400, 'y', 0.01) | {'fmt': LIT, 'material': 0},
                                          quad(0, 400, 0, 0, 0, 400, 'y', 0.01) | {'fmt': PLAIN, 'material': 0}],
                                         ('m',)))
    lit, plain = G.mesh_geometry(model, 0), G.mesh_geometry(model, 1)
    assert np.allclose(lit[1][0], (0, 1, 0), atol=0.01) and np.allclose(lit[2][3], (4, 4), atol=0.01)
    assert np.allclose(plain[1], 0) and np.allclose(plain[2][3], (4, 4), atol=0.01)   # UV at +16, no normal
    assert np.allclose(plain[0], lit[0]) and lit[3].shape == (2, 3)


def test_a_format_that_is_not_measured_is_skipped_never_guessed(monkeypatch):
    model = mt_model.parse_mod(stage_mod([quad(0, 1, 0, 0, 0, 1, 'y', 1) | {'fmt': PLAIN, 'material': 0}], ('m',)))
    monkeypatch.setattr(G, 'STAGE_LAYOUT', {k: v for k, v in G.STAGE_LAYOUT.items() if k != PLAIN})
    assert G.mesh_geometry(model, 0) is None


@pytest.mark.parametrize('fmt, normal', [(0x2FC0B663, True), (0x287029D8, True), (0x3870A4D1, False),
                                         (0x3C004EA1, False)])
def test_the_formats_measured_on_the_other_nine_stages(fmt, normal):
    """2026-11-10: 0x2FC0B663 / 0x287029D8 carry the s8 normal at +12 and the UV at +20; 0x3870A4D1 / 0x3C004EA1 no
    normal and the UV at +16 (the geometric face normal decides)."""
    model = mt_model.parse_mod(stage_mod([quad(0, 400, 0, 0, 0, 400, 'y', 0.01) | {'fmt': fmt, 'material': 0}], ('m',)))
    positions, normals, uvs, triangles = G.mesh_geometry(model, 0)
    assert np.allclose(uvs[3], (4, 4), atol=0.01) and triangles.shape == (2, 3)
    assert np.allclose(normals[0], (0, 1, 0), atol=0.01) if normal else np.allclose(normals, 0)
    assert G.STAGE_LAYOUT[0x35E0A437] == {'normal': 12, 'uv': 20}


def test_the_re6_mrl_resolves_each_material_albedo_and_its_alpha_test():
    archive, _names = stage_arc()
    arc = mt_arc.parse(archive)
    mod, mrl = (next(i for i, e in enumerate(arc.entries) if e.name == SCOPE + 'piece' and G._raw(e)[:4] == magic)
                for magic in (b'MOD\0', b'MRL\0'))
    rows = G.material_bindings(G._raw(arc.entries[mod]), arc.entries[mrl])
    assert [r['albedo'].rsplit('\\', 1)[-1] for r in rows] == ['x_yuka_BM', 'x_kabe_BM', 'x_deck_BM', 'x_fish_NUKI']
    assert [r['alpha_tested'] for r in rows] == [False, True, False, True]
    assert [r['family'] for r in rows] == ['XfB_L', 'XfBAW_0', 'XfB_W', 'XfBA0']


def test_measure_charges_floors_walls_and_the_no_normal_format_and_lists_what_stays_native():
    archive, _names = stage_arc()
    surfaces, notes = G.measure(mt_arc.parse(archive), G.stage_scope('s1208'))
    floor, wall, deck = (surfaces[SCOPE + n] for n in ('x_yuka_BM', 'x_kabe_BM', 'x_deck_BM'))
    assert floor.shares()['up'] == pytest.approx(1.0) and wall.shares()['side'] == pytest.approx(1.0)
    assert deck.shares()['up'] == pytest.approx(1.0)                 # the geometric normal, winding as measured
    assert floor.tile_u_cm == pytest.approx(400.0, rel=0.02) and wall.tile_u_cm == pytest.approx(200.0, rel=0.02)
    assert wall.alpha_tested and not floor.alpha_tested
    assert notes['geometric_normal_meshes'] == 1 and notes['sky_textures'] == [SCOPE + 'x_sky_dome_BM']
    assert notes['albedos_kept_native'] == {SCOPE + 'x_fish_NUKI': '0x14'}
    assert SCOPE + 'x_unused_BM' in surfaces and surfaces[SCOPE + 'x_unused_BM'].area_cm2 == 0


def test_the_plan_uses_re5s_label_rule_and_the_sky_piece():
    archive, _names = stage_arc()
    surfaces, notes = G.measure(mt_arc.parse(archive), G.stage_scope('s1208'))
    rows = {r['name'].rsplit('\\', 1)[-1]: r for r in G.plan(surfaces, notes['sky_textures'])}
    assert (rows['x_yuka_BM']['variant'], rows['x_yuka_BM']['label'], rows['x_yuka_BM']['corner']) == ('floor', '64', '04 m')
    assert (rows['x_kabe_BM']['variant'], rows['x_kabe_BM']['label']) == ('wall', '02 m')
    assert rows['x_sky_dome_BM']['variant'] == 'sky' and rows['x_sky_dome_BM']['rule'] == 'model:sky'
    assert rows['x_unused_BM']['rule'] == 'unbound'
    forced = {r['name'].rsplit('\\', 1)[-1]: r for r in G.plan(surfaces, (), {'x_yuka_BM': 'wall'})}
    assert (forced['x_yuka_BM']['variant'], forced['x_yuka_BM']['rule']) == ('wall', 'override')


# --- the overlay ----------------------------------------------------------------------------------------------------

def test_build_rewrites_only_the_scope_albedos_and_keeps_headers_and_opacity():
    archive, names = stage_arc(opacity=128)
    written, receipt = G.build(archive, stage='s1208')
    before, after = mt_arc.parse(archive), mt_arc.parse(written)
    changed = [e.name for a, e in zip(before.entries, after.entries) if a.data != e.data]
    assert sorted(changed) == sorted(SCOPE + n for n in ('x_yuka_BM', 'x_kabe_BM', 'x_deck_BM', 'x_sky_dome_BM',
                                                         'x_unused_BM'))
    for a, b in zip(before.entries, after.entries):
        assert (a.name, a.hash, a.tag) == (b.name, b.hash, b.tag)
        if a.name.endswith('_BM'):
            ra, rb = G._raw(a), G._raw(b)
            head = 20 + 4 * T.Surface(ra).mip_count
            assert len(ra) == len(rb) and ra[:head] == rb[:head]
    kabe = T.Surface(G._raw(after.find(SCOPE + 'x_kabe_BM')))
    _rgb, opacity = kabe.albedo(0)
    assert abs(int(opacity.mean()) - 128) <= 3                       # the cut-out's opacity kept
    assert receipt['live_verified'] is False and receipt['variants'] == {'floor': 2, 'other': 1, 'sky': 1, 'wall': 1}
    assert G.verify(archive, written, receipt)['changed'] == receipt['changed_entries']
    assert receipt['written_sha256'] == hashlib.sha256(written).hexdigest()


def test_the_luma_build_writes_the_native_neutral_colour_block():
    archive, _names = stage_arc()
    written, receipt = G.build(archive, stage='s1208', chroma=False)
    floor = T.Surface(G._raw(mt_arc.parse(written).find(SCOPE + 'x_yuka_BM')))
    blocks = np.frombuffer(floor.linear_blocks(0), np.uint8).reshape(-1, 16)
    assert all(bytes(b[8:]) == T.NEUTRAL_COLOUR_BLOCK for b in blocks) and receipt['chroma'] is False


def test_verify_refuses_other_changes_and_a_mismatched_receipt():
    archive, _names = stage_arc()
    written, receipt = G.build(archive, stage='s1208')
    arc = mt_arc.parse(written)
    layout = next(e for e in arc.entries if e.name.endswith('_em00'))
    layout.data = zlib.compress(b'XFS\0edited', 6)
    with pytest.raises(G.GreyboxError):
        G.verify(archive, mt_arc.build(arc), receipt)
    with pytest.raises(G.GreyboxError):
        G.verify(archive, written, dict(receipt, changed_entries=receipt['changed_entries'][:-1]))


def test_build_refuses_a_bad_code_and_a_scope_without_albedos():
    archive, _names = stage_arc()
    with pytest.raises(G.GreyboxError):
        G.build(archive, stage='s400')
    with pytest.raises(G.GreyboxError):
        G.build(archive, stage='s1209')
    assert G.MERCS_SETS['s1208'] == ('s1208Soft', 's1218Soft') and G.STAGE_NAMES['s1208'] == 'Creature Workshop'


# --- the ten stages -------------------------------------------------------------------------------------------------

def test_the_stage_table_names_every_geometry_archive_in_the_bots_select_order():
    from gbox.mercs.titles import re6_switch
    assert sorted(G.SELECT_ORDER) == sorted(G.MERCS_STAGES) == sorted(G.STAGE_NAMES)
    assert [G.STAGE_NAMES[code] for code in G.SELECT_ORDER] == list(re6_switch.STAGES)
    assert G.SELECT_ORDER[2] == 's1203' and G.STAGE_NAMES['s1203'] == 'Mining the Depths'


def test_a_campaign_stages_pieces_beside_the_stages_own_are_written_too():
    extra_scope = 'data\\stage\\s0204\\scr\\scr00\\'
    archive, _names = stage_arc(extra=[(extra_scope + 'x_kanban_BM', albedo(32, 32))])
    arc = mt_arc.parse(archive)
    assert G.scene_scopes(arc, 's1208') == ('data\\stage\\s1208\\scr\\', 'data\\stage\\s0204\\scr\\')
    assert G.scene_scopes(arc, 's1203') == ('data\\stage\\s1203\\scr\\',)        # no own folder: nothing borrowed
    written, receipt = G.build(archive, stage='s1208')
    after = mt_arc.parse(written)
    assert G._raw(after.find(extra_scope + 'x_kanban_BM')) != G._raw(arc.find(extra_scope + 'x_kanban_BM'))
    assert receipt['scopes'] == list(G.scene_scopes(arc, 's1208')) and receipt['stage_select_index'] == 9
    assert G.verify(archive, written, receipt)['changed'] == receipt['changed_entries']
    with pytest.raises(G.GreyboxError):
        G.build(archive, stage='s1203')                       # the campaign folder alone is not a stage


def test_suffixed_base_maps_are_albedos_and_get_their_grid():
    assert all(G.is_albedo_name(SCOPE + n) for n in ('x_BM', 's0023_BM-ground02', 'om1309_BM_04', 's1201_ten_BM_HQ'))
    assert not any(G.is_albedo_name(SCOPE + n) for n in ('x_NM', 'x_BMX', 'x_MM', 'x_bm'))
    archive, _names = stage_arc(extra=[(SCOPE + 's0023_BM-ground02', albedo(32, 32)),
                                       (SCOPE + 'om1309_BM_04', albedo(32, 32))])
    written, receipt = G.build(archive, stage='s1208')
    names = {r['name'].rsplit('\\', 1)[-1] for r in receipt['textures']}
    assert {'s0023_BM-ground02', 'om1309_BM_04'} <= names
    assert G.verify(archive, written, receipt)['changed'] == receipt['changed_entries']


def test_build_all_writes_each_present_stage_with_one_receipt(tmp_path):
    archive, _names = stage_arc()
    inputs = tmp_path / 'NX'
    inputs.mkdir()
    (inputs / 's1208.arc').write_bytes(archive)
    receipt = G.build_all(inputs, tmp_path / 'out', stages=('s1203', 's1208'), preview=False, rebuild_check=True,
                          log=lambda *_: None)
    path = 'romfs/nativeNXx64/arc/NX/s1208.arc'
    written = (tmp_path / 'out' / path).read_bytes()
    assert list(receipt['files']) == [path] and receipt['files'][path]['sha256'] == hashlib.sha256(written).hexdigest()
    assert receipt['stages']['s1203'] == {'skipped': f'{inputs / "s1203.arc"} not present'}
    assert receipt['stages']['s1208']['stage_name'] == 'Creature Workshop'
    assert receipt['stages']['s1208']['rebuild_identical'] is True and receipt['live_verified'] is False
    assert (tmp_path / 'out' / 'receipt.json').is_file()
    with pytest.raises(G.GreyboxError):
        G.build_all(inputs, tmp_path / 'none', stages=('s1203',), preview=False, log=lambda *_: None)
