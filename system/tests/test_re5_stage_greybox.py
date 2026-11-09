"""RE5 stage greybox writer on synthetic fixtures: no game asset is read.

The stage fixture mirrors what was measured on s400.arc: bone-less MODs (bones offset 0, groups at 164) whose parts use
the float-position formats with the normal at +12 and the albedo UV at +20, a light-map UV at +24 in the lightmapped
format and an RGBA colour there in the vertex-lit one; MRL v34 materials binding an albedo, the light map and the
NullWhite slots; BC7 TEX entries with the measured Tegra mip storage; every entry a wrapped zlib stream in an ARC.
The prop fixture is a one-bone object with a depth proxy part and a drawn part in the short-position formats.
"""
import hashlib
import json
import struct
import zlib

import numpy as np
import pytest
from PIL import Image

from gbox import mt_arc, mt_model, mtf_author, mtf_mrl, mtf_tex, re5_stage_greybox as G

SCOPE = 'stage\\s400\\scr\\scr01\\'
LIT, VERTEX = 0x2AE06DB8, 0x29F0B449


# --- fixtures -------------------------------------------------------------------------------------------------------

def tex(fmt, width=32, height=None):
    """A Switch TEX with the measured per-mip Tegra block storage and a non-zero payload pattern."""
    height = height or width
    bpb = {0x19: 8, 0x1F: 16, 0x30: 16, 0x13: 8}[fmt]
    offsets, total = [], 0
    for level in range(max(width, height).bit_length()):
        bx, by = (max(1, width >> level) + 3) // 4, (max(1, height >> level) + 3) // 4
        bh = max(1, min(16, (1 << (by - 1).bit_length()) // 8))
        offsets.append(total)
        total += ((bx * bpb + 63) // 64) * 64 * ((by + 8 * bh - 1) // (8 * bh)) * 8 * bh
    header = b'TEX\0\xa1\x80\0\x20' + struct.pack('<3I', len(offsets) | width << 6 | height << 19,
                                                  0x10001 | fmt << 8, total)
    return header + struct.pack(f'<{len(offsets)}I', *offsets) + bytes((n * 37 + fmt) % 256 for n in range(total))


def bc7_tex(width=32, height=None, rgba=(90, 120, 60, 255)):
    """A BC7 TEX whose mip 0 actually decodes: a flat colour encoded through the writer's own encoder."""
    pytest.importorskip('ispc_texcomp')
    height = height or width
    return mtf_tex.replace_image(tex(0x30, width, height), Image.new('RGBA', (width, height), rgba))


def pack_stage(fmt, points, normals, uvs, lightmap_uvs=None):
    stride = mt_model.fvf_stride(fmt)
    out = bytearray()
    for i, (p, n, uv) in enumerate(zip(points, normals, uvs)):
        record = bytearray(stride)
        struct.pack_into('<3f', record, 0, *p)
        struct.pack_into('<4b', record, 12, *(max(-127, min(127, round(c * 127))) for c in n), -1)
        struct.pack_into('<4b', record, 16, 127, 0, 0, 127)
        struct.pack_into('<2e', record, 20, *uv)
        if fmt == LIT:
            struct.pack_into('<2e', record, 24, *(lightmap_uvs[i] if lightmap_uvs else (0.5, 0.5)))
        else:
            record[24:28] = bytes((200, 200, 200, 255))
        out += record
    return bytes(out)


def stage_mod(parts, materials):
    """A bone-less stage MOD in the measured layout: parts are dicts with fmt, material, lod, points, normals, uvs,
    strips (lists of local indices, 0xFFFF between them)."""
    records, vertices, words, envelopes = b'', b'', [], b''
    for number, part in enumerate(parts):
        stride = mt_model.fvf_stride(part['fmt'])
        offset = len(vertices)
        vertices += pack_stage(part['fmt'], part['points'], part['normals'], part['uvs'], part.get('lightmap_uvs'))
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
    out = mt_model.MOD_MAGIC + bytes((211, 0)) + struct.pack('<3H', 0, len(parts), len(materials))
    out += struct.pack('<3I2I2I', len(every), len(words), 9, len(vertices), 0, 1, 0)
    out += struct.pack('<7Q', *offsets) + tail + b''.join(blocks) + bytes(4)
    return out


def stage_mrl(materials, bindings, paths):
    """An MRL v34 whose materials bind (shader hash, 1-based texture index) commands; `paths` is the texture table."""
    table = 40 + len(paths) * 88
    cursor = (table + 72 * len(materials) + 15) & ~15
    raw = bytearray(cursor + 24 * sum(len(bindings[m]) for m in materials))
    struct.pack_into('<4sIIIQQQ', raw, 0, b'MRL\0', 34, len(materials), len(paths), mtf_mrl.RE5_SHADER_VERSION, 40, table)
    for i, path in enumerate(paths):
        raw[40 + i * 88 + 24:40 + i * 88 + 24 + len(path)] = path.encode()
    for i, name in enumerate(materials):
        commands = bindings[name]
        struct.pack_into('<QII', raw, table + 72 * i, mtf_mrl.MATERIAL_STD, zlib.crc32(name.encode()) ^ 0xFFFFFFFF,
                         24 * len(commands))
        struct.pack_into('<I', raw, table + 72 * i + 28, len(commands))
        struct.pack_into('<Q', raw, table + 72 * i + 56, cursor)
        for shader, value in commands:
            struct.pack_into('<IIQQ', raw, cursor, 3, 0xCDCDCDCD, value, shader << 12 | 0x375)
            cursor += 24
    return bytes(raw)


def quad(x0, x1, y0, y1, z0, z1, axis_normal, uv_scale):
    """Two triangles over a rectangle; `uv_scale` is UV units per centimetre along each in-plane axis."""
    if axis_normal == 'y':                                   # floor: spans x and z at height y0
        points = [(x0, y0, z0), (x1, y0, z0), (x0, y0, z1), (x1, y0, z1)]
        uvs = [(0, 0), ((x1 - x0) * uv_scale, 0), (0, (z1 - z0) * uv_scale), ((x1 - x0) * uv_scale, (z1 - z0) * uv_scale)]
        normal = (0.0, 1.0, 0.0)
    else:                                                    # wall: spans x and y at depth z0
        points = [(x0, y0, z0), (x1, y0, z0), (x0, y1, z0), (x1, y1, z0)]
        uvs = [(0, 0), ((x1 - x0) * uv_scale, 0), (0, (y1 - y0) * uv_scale), ((x1 - x0) * uv_scale, (y1 - y0) * uv_scale)]
        normal = (0.0, 0.0, 1.0)
    return {'points': points, 'normals': [normal] * 4, 'uvs': uvs, 'strips': [[0, 1, 2, 3]]}


def stage_arc(*, floor_tile_cm=400.0, wall_tile_cm=200.0, alpha=255):
    """(archive, names): a floor quad on the lightmapped format, a wall quad on the vertex-lit one, one unbound
    albedo, a sky albedo, a normal map, a light map and an untouched entry."""
    floor = quad(0, 1600, 0, 0, 0, 800, 'y', 1.0 / floor_tile_cm) | {'fmt': LIT, 'material': 0, 'lod': 1,
                                                                      'lightmap_uvs': [(0, 0), (1, 0), (0, 1), (1, 1)]}
    wall = quad(0, 600, 0, 300, 0, 0, 'z', 1.0 / wall_tile_cm) | {'fmt': VERTEX, 'material': 1, 'lod': 1}
    materials = ('floorMesh.None.XfB_L_1', 'wallMesh.None.XfBAW_2')
    mod = stage_mod([floor, wall], materials)
    paths = [SCOPE + 'y_floor_BM', 'system\\texture\\NullWhite', SCOPE + 'L_floor_LM', SCOPE + 'y_kabe_BM',
             SCOPE + 'y_kabe_NM']
    mrl = stage_mrl(materials, {'floorMesh.None.XfB_L_1': [(G.ALBEDO_HASH, 1), (0x9333B, 2), (G.LIGHTMAP_HASH, 3)],
                                'wallMesh.None.XfBAW_2': [(G.NORMAL_HASH, 5), (G.ALBEDO_HASH, 4), (0x9333B, 2)]},
                    paths)
    contents = [(SCOPE + 'y_floor_BM', bc7_tex(64, 32, (90, 120, 60, 255))),
                (SCOPE + 'y_kabe_BM', bc7_tex(32, 32, (150, 100, 80, alpha))),
                (SCOPE + 'y_unused_BM', bc7_tex(32)),
                (SCOPE + 'y_s400_skyA_BM', bc7_tex(64, 32, (100, 150, 220, 255))),
                (SCOPE + 'y_kabe_NM', tex(0x1F)), (SCOPE + 'L_floor_LM', tex(0x13)),
                ('stage\\s400\\soft\\merce\\s400_fsm', b'XFS\0kept'),
                (SCOPE + 'piece', mrl), (SCOPE + 'piece', mod)]
    entries = [mt_arc.Entry(name=name, hash=0x241F5DEB, tag=0x40000000 | len(data), size=0, offset=0,
                            data=zlib.compress(data, 6)) for name, data in contents]
    return mt_arc.build(mt_arc.Arc(7, entries)), [name for name, _ in contents]


# --- grid textures ---------------------------------------------------------------------------------------------------

def test_grid_image_variants_have_the_requested_size_and_distinct_looks():
    floor = G.grid_image(128, 64, 'floor', 4, 2, '1024', '04 m')
    wall = G.grid_image(128, 64, 'wall', 2, 1, '02 m')
    other = G.grid_image(64, 64, 'other', 2, 2, '02 m')
    sky = G.grid_image(64, 32, 'sky')
    assert floor.size == (128, 64) and wall.size == (128, 64) and other.size == (64, 64) and sky.size == (64, 32)
    f, w, o = (np.asarray(im) for im in (floor, wall, other))
    assert f[..., 2].mean() > f[..., 0].mean()                 # floors are blue
    assert abs(int(w[..., 0].mean()) - int(w[..., 2].mean())) < 3  # walls are grey
    assert len(np.unique(o.reshape(-1, 3), axis=0)) >= 3       # checker: two cell tones plus lines
    assert len(np.unique(np.asarray(sky).reshape(-1, 3), axis=0)) == 1
    # a major line runs the full height at the first cell boundary
    assert (f[:, 32] == G.PALETTE['floor']['major']).all(1).all()


def test_grid_image_refuses_bad_arguments():
    with pytest.raises(G.GreyboxError):
        G.grid_image(32, 32, 'plaid')
    with pytest.raises(G.GreyboxError):
        G.grid_image(0, 32, 'wall')
    with pytest.raises(G.GreyboxError):
        G.grid_image(32, 32, 'wall', 0, 1)


def test_cells_and_labels_follow_the_measured_tile_span():
    assert [G.grid_cells(v) for v in (None, 0.0, 40.0, 149.0, 151.0, 437.0, 9000.0)] == [1, 1, 1, 1, 2, 4, 32]
    assert [G.span_label(v) for v in (None, 437.0, 99.0, 20.0, 4.8)] == ['?? m', '04 m', '01 m', '0.2 m', '5 cm']


def test_greybox_texture_keeps_container_format_mips_and_the_native_alpha():
    native = bc7_tex(32, 32, (10, 20, 30, 77))
    out, report = G.greybox_texture(native, 'wall', 1, 1, '01 m')
    assert len(out) == len(native) and out[:44] == native[:44]
    tex_in, tex_out = mtf_tex.parse(native), mtf_tex.parse(out)
    assert (tex_out.width, tex_out.height, tex_out.format, len(tex_out.mips)) == (32, 32, 0x30, 6)
    decoded = np.asarray(mtf_tex.decode(out, 0))
    assert abs(int(decoded[..., 3].mean()) - 77) <= 3           # the native alpha came through
    assert decoded[..., :3].std() > 5                           # and there is a grid, not a flat tile
    assert report['alpha'].startswith('native alpha kept') and report['cells'] == [1, 1]
    with pytest.raises(G.GreyboxError):
        G.greybox_texture(tex(0x1F), 'wall', 1, 1, '')


# --- measurement and classification ----------------------------------------------------------------------------------

def test_measure_charges_triangles_to_the_bound_albedo_and_reads_the_uv_scale():
    archive, _ = stage_arc(floor_tile_cm=400.0, wall_tile_cm=200.0)
    surfaces, notes = G.measure(mt_arc.parse(archive), SCOPE)
    assert notes['models'] == 1 and notes['meshes'] == 2 and notes['triangles'] == 4
    floor, wall = surfaces[SCOPE + 'y_floor_BM'], surfaces[SCOPE + 'y_kabe_BM']
    assert floor.shares()['up'] == pytest.approx(1.0) and wall.shares()['side'] == pytest.approx(1.0)
    assert floor.tile_u_cm == pytest.approx(400.0, rel=0.01) and floor.tile_v_cm == pytest.approx(400.0, rel=0.01)
    assert wall.tile_u_cm == pytest.approx(200.0, rel=0.01)
    assert floor.area_cm2 == pytest.approx(1600 * 800) and wall.area_cm2 == pytest.approx(600 * 300)
    assert floor.families == ['XfB_L'] and wall.families == ['XfBAW'] and wall.alpha_tested and not floor.alpha_tested
    unused = surfaces[SCOPE + 'y_unused_BM']
    assert unused.area_cm2 == 0 and unused.tile_u_cm is None
    assert G.classify(floor) == ('floor', 'geometry:up')
    assert G.classify(wall) == ('wall', 'geometry:side')
    assert G.classify(unused) == ('other', 'unbound')
    assert G.classify(surfaces[SCOPE + 'y_s400_skyA_BM']) == ('sky', 'name:sky')


def test_classify_falls_back_to_names_only_where_the_geometry_is_mixed():
    mixed = G.Surface(name=SCOPE + 'y_kabeX_BM', entry=0, width=32, height=32, format=0x30, mips=6,
                      area_cm2=100.0, up_cm2=40.0, side_cm2=40.0, down_cm2=20.0)
    assert G.classify(mixed) == ('wall', 'name:kabe')
    mixed.name = SCOPE + 'y_jimenX_BM'
    assert G.classify(mixed) == ('floor', 'name:jimen')
    mixed.name = SCOPE + 'y_thing_BM'
    assert G.classify(mixed) == ('other', 'default')
    roof = G.Surface(name=SCOPE + 'y_yane_BM', entry=0, width=32, height=32, format=0x30, mips=6,
                     area_cm2=100.0, up_cm2=100.0)
    assert G.classify(roof) == ('other', 'name:roof')
    clear = G.Surface(name=SCOPE + 'y_kabe_BM', entry=0, width=32, height=32, format=0x30, mips=6,
                      area_cm2=100.0, up_cm2=90.0)
    assert G.classify(clear) == ('floor', 'geometry:up')          # geometry beats the name where it is clear


def test_plan_puts_the_pixel_size_on_floors_and_the_metre_span_on_walls():
    archive, _ = stage_arc(floor_tile_cm=400.0, wall_tile_cm=200.0)
    surfaces, _ = G.measure(mt_arc.parse(archive), SCOPE)
    rows = {row['name'].rsplit('\\', 1)[-1]: row for row in G.plan(surfaces)}
    assert rows['y_floor_BM']['variant'] == 'floor' and rows['y_floor_BM']['label'] == '64'
    assert rows['y_floor_BM']['corner'] == '04 m' and rows['y_floor_BM']['cells'] == [4, 4]
    assert rows['y_kabe_BM']['variant'] == 'wall' and rows['y_kabe_BM']['label'] == '02 m'
    assert rows['y_kabe_BM']['cells'] == [2, 2]
    assert rows['y_unused_BM'] == rows['y_unused_BM'] | {'variant': 'other', 'rule': 'unbound', 'cells': [1, 1]}
    overridden = {row['name'].rsplit('\\', 1)[-1]: row for row in G.plan(surfaces, {'y_kabe_BM': 'other'})}
    assert overridden['y_kabe_BM']['variant'] == 'other' and overridden['y_kabe_BM']['rule'] == 'override'
    with pytest.raises(G.GreyboxError):
        G.plan(surfaces, {'y_kabe_BM': 'plaid'})


# --- the stage overlay -----------------------------------------------------------------------------------------------

def test_build_rewrites_every_scope_albedo_and_nothing_else(tmp_path):
    archive, names = stage_arc(alpha=128)
    written, receipt = G.build(archive, stage='s400')
    before, after = mt_arc.parse(archive), mt_arc.parse(written)
    assert [e.name for e in after.entries] == names
    albedos = {i for i, name in enumerate(names) if name.endswith('_BM')}
    assert set(receipt['changed_entries']) == albedos and len(albedos) == 4
    for i, (a, b) in enumerate(zip(before.entries, after.entries)):
        assert (a.name, a.hash, a.tag) == (b.name, b.hash, b.tag)
        if i in albedos:
            assert a.data != b.data
            ta, tb = mtf_tex.parse(zlib.decompress(a.data)), mtf_tex.parse(zlib.decompress(b.data))
            assert (ta.width, ta.height, ta.format, len(ta.mips)) == (tb.width, tb.height, tb.format, len(tb.mips))
        else:
            assert a.data == b.data
    assert mt_arc.build(after) == written
    assert receipt['live_verified'] is False and receipt['variants'] == {'floor': 1, 'wall': 1, 'other': 1, 'sky': 1}
    assert receipt['written_sha256'] == hashlib.sha256(written).hexdigest()
    wall = next(row for row in receipt['textures'] if row['name'].endswith('y_kabe_BM'))
    assert wall['alpha'].startswith('native alpha kept') and wall['payload_sha256']
    decoded = np.asarray(mtf_tex.decode(zlib.decompress(after.entries[wall['entry']].data), 0))
    assert abs(int(decoded[..., 3].mean()) - 128) <= 3          # the alpha-tested wall keeps its cut-out channel
    assert G.verify(archive, written, receipt)['changed'] == sorted(albedos)
    # the same inputs give the same bytes
    again, _ = G.build(archive, stage='s400')
    assert again == written
    # the overlay tree and the previews
    path = G.write_overlay(tmp_path, 's400.arc', written, receipt)
    assert path == tmp_path / 'romfs' / 'nativeNXx64' / 'ImgNX' / 'Archive' / 's400.arc' and path.read_bytes() == written
    assert json.loads((tmp_path / 'receipt.json').read_text())['written_sha256'] == receipt['written_sha256']
    G.contact_sheet(written, receipt['textures'], tmp_path / 'textures.png')
    assert Image.open(tmp_path / 'textures.png').size[0] > 0
    view = G.render_stage(written, tmp_path / 'view.png', stage='s400', size=96)
    assert view['triangles'] == 4 and Image.open(tmp_path / 'view.png').size == (96, 96)


def test_verify_refuses_changes_outside_the_albedos_and_mismatched_receipts():
    archive, names = stage_arc()
    written, receipt = G.build(archive)
    arc = mt_arc.parse(written)
    tampered = mt_arc.replace_at(written, names.index(SCOPE + 'y_kabe_NM'), arc.entries[names.index(SCOPE + 'y_kabe_NM')].data[:-1] + b'\0')
    with pytest.raises(G.GreyboxError, match='not an albedo'):
        G.verify(archive, tampered)
    wrong = json.loads(json.dumps(receipt))
    wrong['textures'][0]['payload_sha256'] = '00' * 32
    with pytest.raises(G.GreyboxError, match='receipt'):
        G.verify(archive, written, wrong)
    assert G.verify(archive, written)['unchanged'] == len(names) - 4


def test_build_refuses_a_scope_without_albedos_and_a_bad_stage_code():
    archive, _ = stage_arc()
    with pytest.raises(G.GreyboxError):
        G.build(archive, stage='s401')
    with pytest.raises(G.GreyboxError):
        G.stage_scope('stage400')


def test_mesh_geometry_skips_unmeasured_formats_and_checks_the_index_window():
    floor = quad(0, 100, 0, 0, 0, 100, 'y', 0.01) | {'fmt': LIT, 'material': 0, 'lod': 1}
    mod = stage_mod([floor], ('m.None.XfB_L_1',))
    model = mt_model.parse_mod(mod)
    positions, normals, uvs, triangles = G.mesh_geometry(model, 0)
    assert positions.shape == (4, 3) and uvs.shape == (4, 2) and len(triangles) == 2
    assert np.allclose(normals[:, 1], 1.0, atol=0.01)
    broken = bytearray(mod)
    struct.pack_into('>I', broken, model.header()['offsets']['meshes'] + 0x14, 0x37607D20)
    broken[model.header()['offsets']['meshes'] + 0x0A] = 24
    assert G.mesh_geometry(mt_model.parse_mod(bytes(broken)), 0) is None


# --- the prop path ------------------------------------------------------------------------------------------------

COMPRESSION = np.diag([200., 200., 200., 1.])
COMPRESSION[3, :3] = (-50., 0., -40.)


def prop_mod():
    """A one-bone object: a depth proxy part (0x133098B0) and a drawn part (0x18B0FAA8), 30 vertices each."""
    transform = tuple(COMPRESSION.ravel())
    points = [(-50. + 100. * (i % 2), 10. * (i % 7), -40. + 80. * ((i // 2) % 2)) for i in range(30)]
    headers = bytes((0, 255, 0, 0)) + bytes(20)
    world = np.eye(4)
    local = struct.pack('<16f', *world.ravel())
    inverse = struct.pack('<16f', *(COMPRESSION @ np.linalg.inv(world)).ravel())
    bone_block = headers + local + inverse + bytes(256)
    parts = [(0x133098B0, 12, 0x1020, 132, 1), (0x18B0FAA8, 20, 0xFFFF, 4, 1),
             (0x133098B0, 12, 0x1020, 132, 254), (0x18B0FAA8, 20, 0xFFFF, 4, 254)]
    records, vertices, words, envelopes = b'', b'', [], b''
    for number, (fmt, stride, kind, mode, lod) in enumerate(parts):
        offset = len(vertices)
        if fmt == 0x18B0FAA8:
            vertices += mt_model.pack_vertices([{'position': p, 'normal': (0., 1., 0.), 'uv': (.5, .5), 'bones': [0]}
                                                for p in points], fmt, stride, position_transform=transform)
        else:
            vertices += mt_model.pack_vertices([{'position': p, 'bones': [0]} for p in points], fmt, stride,
                                               position_transform=transform)
        strip = []
        for k in range(0, 28, 4):
            strip += ([0xFFFF] if k else []) + [k, k + 1, k + 2, k + 3]
        record = bytearray(56)
        struct.pack_into('<HHI', record, 0, kind, len(points), 0 | (number // 2) << 12 | lod << 24)
        record[8:12] = bytes((9, 0, stride, mode))
        struct.pack_into('<II', record, 0x0C, 0, offset)
        struct.pack_into('>I', record, 0x14, fmt)
        struct.pack_into('<III', record, 0x18, len(words), len(strip), 0)
        record[0x25] = 1
        struct.pack_into('<HHH', record, 0x26, number + 1, 0, len(points) - 1)
        records += record
        words += strip + [0xFFFF]
        envelopes += mtf_author.pack_weight_bound(0, points)
    if len(words) % 2 == 0:
        words.append(0)
    indices = struct.pack(f'<{len(words)}H', *words)
    tail = struct.pack('<12f', 0, 30, 0, 80, -50, 0, -40, 0, 50, 60, 40, 0) + struct.pack('<5I', 500, 1000, 3, 0, 4)
    group_block = struct.pack('<I12x4f', 0, 0, 30, 0, 80)
    material_block = b''.join(name.encode().ljust(128, b'\0') for name in ('near.None.XfB_N__E', 'far.None.XfB_N__E1'))
    blocks = (bone_block, group_block, material_block, records + envelopes, vertices, indices)
    offsets = [0x28 + 56 + len(tail)]
    for block in blocks:
        offsets.append(offsets[-1] + len(block))
    out = mt_model.MOD_MAGIC + bytes((211, 0)) + struct.pack('<3H', 1, len(parts), 2)
    out += struct.pack('<3I2I2I', len(points) * 4, len(words), 9, len(vertices), 0, 1, 0)
    out += struct.pack('<7Q', *offsets) + tail + b''.join(blocks) + bytes(4)
    return out


def prop_arc():
    model = 'pawn\\om\\om0889\\model\\om0889'
    contents = [('pawn\\om\\om0889\\model\\om_kibakoC01_01_BM', bc7_tex(32)),
                ('pawn\\om\\om0889\\model\\om_kibakoC01_01_NM', tex(0x1F)),
                ('pawn\\om\\om0889\\model\\om_kibakoC01_02_BM', bc7_tex(16)),
                (model, b'MRL\0kept-as-is'), (model, prop_mod()), ('pawn\\om\\om0889\\model\\om0889_01', prop_mod())]
    entries = [mt_arc.Entry(name=name, hash=0x241F5DEB, tag=0x40000000 | len(data), size=0, offset=0,
                            data=zlib.compress(data, 6)) for name, data in contents]
    return mt_arc.build(mt_arc.Arc(7, entries)), [name for name, _ in contents]


def test_box_geometry_is_a_closed_outward_box_with_metre_uvs():
    bounds = {'min': {'x': -50., 'y': 0., 'z': -40.}, 'max': {'x': 50., 'y': 60., 'z': 40.}}
    vertices, triangles, quads = G.box_geometry(bounds)
    assert len(vertices) == 24 and len(triangles) == 12 and len(quads) == 6
    points = np.asarray([v['position'] for v in vertices])
    assert points.min(0).tolist() == [-50., 0., -40.] and points.max(0).tolist() == [50., 60., 40.]
    centre = np.array([0., 30., 0.])
    for a, b, c in triangles:
        p = points[[a, b, c]]
        assert np.dot(np.cross(p[1] - p[0], p[2] - p[0]), p.mean(0) - centre) > 0
    uvs = np.asarray([v['uv'] for v in vertices])
    assert uvs.max() == pytest.approx(1.0) and uvs.min() == pytest.approx(0.0)   # the 100 cm edges span one tile, centred
    with pytest.raises(G.GreyboxError):
        G.box_geometry({'min': bounds['min'], 'max': bounds['min']})


def test_box_model_rewrites_parts_in_place_and_keeps_the_table():
    mod = prop_mod()
    boxed, report = G.box_model(mod, lods=(0, 1))
    model, after = mt_model.parse_mod(mod), mt_model.parse_mod(boxed)
    assert len(boxed) == len(mod) and after.header() == model.header() and after.meshes() == model.meshes()
    assert [p['part'] for p in report['parts']] == [0, 1, 2, 3] and report['triangles'] == 12
    offsets = model.header()['offsets']
    # outside the vertex and index buffers nothing changed
    assert boxed[:offsets['vertex_buffer']] == mod[:offsets['vertex_buffer']]
    assert boxed[offsets['end']:] == mod[offsets['end']:]
    for k in range(4):
        triangles = mtf_author.mesh_triangles(after, k)
        assert len(triangles) == 12
        points = np.asarray(after.positions(k))[:24]
        assert np.allclose(points.min(0), [-50., 0., -40.], atol=0.5) and np.allclose(points.max(0), [50., 60., 40.], atol=0.5)
    # the drawn part carries the box normals and metre UVs
    normals = np.asarray(after.normals(1))[:24]
    assert np.allclose(np.linalg.norm(normals, axis=1), 1.0, atol=0.02)
    assert np.asarray(after.uvs(1))[:24].max() == pytest.approx(1.0, abs=0.01)
    # the bone id of every rewritten vertex is still the native one
    assert all(ids == (0,) for ids in after.bone_ids(1)[:24])
    with pytest.raises(G.GreyboxError):
        G.box_model(mod, lods=(9,))                    # no part carries LOD bit 9


def test_build_prop_box_changes_only_the_model_and_its_albedos():
    archive, names = prop_arc()
    written, receipt = G.build_prop_box(archive, G.CRATE)
    before, after = mt_arc.parse(archive), mt_arc.parse(written)
    assert receipt['changed_entries'] == [0, 2, 4] and receipt['live_verified'] is False
    for i, (a, b) in enumerate(zip(before.entries, after.entries)):
        assert (a.name, a.hash, a.tag) == (b.name, b.hash, b.tag)
        assert (a.data == b.data) == (i not in (0, 2, 4))
    assert receipt['model']['payload_sha256'] == hashlib.sha256(zlib.decompress(after.entries[4].data)).hexdigest()
    assert [t['variant'] for t in receipt['textures']] == ['prop', 'prop']
    assert mt_arc.build(after) == written
    with pytest.raises(G.GreyboxError):
        G.build_prop_box(archive, G.DESK)
