import io
import json
import os
import struct
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from gbox.re5ps3_arc import Arc, sha
from gbox.re5ps3_models import Model, Texture, export_glb, export_archive, triangles


def texture(kind='DXT1'):
    data = bytearray(40)
    data[:4] = b'\0XET'
    struct.pack_into('>HHBBHHH', data, 4, 102, 0x2200, 1, 1, 4, 4, 0)
    data[16:20] = kind.encode()[::-1]
    struct.pack_into('>4fI', data, 20, 1, 1, 1, 0, 40)
    if kind == 'DXT5':
        data += bytes([255, 0]) + bytes(6)
    data += struct.pack('<HHI', 0xf800, 0, 0)
    return bytes(data)


def model(eight=False):
    nb, nm, nmat, nv, nt, ng, npal = 2, 1, 1, 3, 1, 1, 1
    bones = 176; groups = bones + nb * 152 + 256 + 68
    mats = groups + 32; meshes = mats + 64 + 160
    vertices = meshes + 56; indices = vertices + 96
    data = bytearray(indices + 6); data[:4] = b'\0DOM'
    struct.pack_into('>4H15I', data, 4, 412, nb, nm, nmat, nv, 4, 0, 96, 0,
                     nt, ng, npal, bones, groups, mats, meshes, vertices, indices, indices)
    struct.pack_into('>3f', data, 96, 0, 0, 0); struct.pack_into('>3f', data, 112, 2, 2, 2)
    data[140] = 2
    for i in range(2):
        data[bones + i * 24] = i; data[bones + i * 24 + 1] = 255 if i == 0 else 0
        local = np.eye(4); local[:3, 3] = [0, 1, 0] if i == 0 else [1, 0, 0]
        world = np.eye(4); world[:3, 3] = [i, 1, 0]
        struct.pack_into('>16f', data, bones + nb * 24 + i * 64, *local.T.reshape(-1))
        struct.pack_into('>16f', data, bones + nb * 88 + i * 64, *np.linalg.inv(world).T.reshape(-1))
    maps = bones + nb * 152; data[maps:maps + 256] = bytes(range(256))
    struct.pack_into('>I', data, maps + 256, 2); data[maps + 260:maps + 262] = bytes([1, 0])
    name = b'pawn\\test\\body'; data[mats:mats + len(name)] = name
    struct.pack_into('>II', data, mats + 64, 0xc0400005 if eight else 0xc0400001, 0x40844000 if eight else 0x30844000)
    struct.pack_into('>I', data, mats + 88, 1)
    data[meshes + 4:meshes + 10] = bytes([1, 1, 0, 8 if eight else 1, 32, 0])
    struct.pack_into('>HH', data, meshes + 12, 3, 2)
    struct.pack_into('>I', data, meshes + 32, 3)
    data[meshes + 46] = 0
    for i, position in enumerate([(0, 0, 0), (32767, 0, 0), (0, 32767, 0)]):
        at = vertices + i * 32
        struct.pack_into('>4h', data, at, *position, 32767)
        if eight:
            data[at + 8:at + 16] = bytes([0, 1] * 4)
            data[at + 16:at + 24] = bytes([32] * 7 + [31])
            data[at + 24:at + 28] = bytes([127, 127, 255, 255])
            struct.pack_into('>2e', data, at + 28, i / 2, i / 2)
        else:
            data[at + 8:at + 12] = bytes([i % 2, 255, 255, 255])
            data[at + 12:at + 16] = bytes([255, 0, 0, 0])
            data[at + 16:at + 20] = bytes([127, 127, 255, 255])
            struct.pack_into('>2e', data, at + 24, i / 2, i / 2)
    struct.pack_into('>3H', data, indices, 0, 1, 2)
    return bytes(data)


def glb(path):
    raw = path.read_bytes()
    assert struct.unpack_from('<3I', raw) == (0x46546c67, 2, len(raw))
    size, kind = struct.unpack_from('<2I', raw, 12)
    assert kind == 0x4e4f534a
    doc = json.loads(raw[20:20 + size])
    binary_size, kind = struct.unpack_from('<2I', raw, 20 + size)
    assert kind == 0x004e4942
    binary = raw[28 + size:]
    assert len(binary) == binary_size
    def acc(i):
        a = doc['accessors'][i]; v = doc['bufferViews'][a['bufferView']]
        components = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4, 'MAT4': 16}[a['type']]
        dtype = {5126: '<f4', 5123: '<u2', 5125: '<u4'}[a['componentType']]
        size = a['count'] * components * np.dtype(dtype).itemsize
        assert size == v['byteLength']
        assert v['byteOffset'] % 4 == 0
        assert v['byteOffset'] + size <= len(binary)
        return np.frombuffer(binary, dtype=dtype, count=a['count'] * components, offset=v['byteOffset']).reshape(-1, components)
    for i in range(len(doc['accessors'])):
        acc(i)
    return doc, binary, acc


@pytest.mark.parametrize('kind', ['DXT1', 'DXT5'])
def test_texture_decodes_known_red_block(kind):
    tex = Texture(texture(kind))
    im = tex.image()
    assert im.size == (4, 4)
    assert np.asarray(im).reshape(-1, 4).tolist() == [[255, 0, 0, 255]] * 16
    with pytest.raises(ValueError, match='mip index'):
        tex.image(1)


@pytest.mark.parametrize('offset,fmt,value,error', [
    (4, '>H', 112, 'version'), (8, '>B', 9, 'mip count'), (10, '>H', 65535, 'dimensions'),
    (36, '>I', 39, 'overlapping'), (36, '>I', 44, 'outside'), (20, '>f', float('nan'), 'non-finite')])
def test_texture_rejects_corrupt_headers(offset, fmt, value, error):
    data = bytearray(texture()); struct.pack_into(fmt, data, offset, value)
    with pytest.raises(ValueError, match=error):
        Texture(data)


def test_strip_restarts_and_degenerate_parity():
    # The duplicated vertex still advances strip parity. Restart resets it.
    assert triangles([0, 1, 2, 2, 3, 4, 65535, 5, 6, 7, 8]).tolist() == [[0, 1, 2], [3, 2, 4], [5, 6, 7], [7, 6, 8]]


@pytest.mark.parametrize('eight', [False, True])
def test_independent_glb_geometry_skin_texture_readback(tmp_path, eight):
    src = model(eight); m = Model(src); out = tmp_path / 'model.glb'
    receipt = export_glb(m, {'pawn\\test\\body': texture()}, out)
    doc, binary, acc = glb(out); p = doc['meshes'][0]['primitives'][0]; a = p['attributes']
    assert acc(a['POSITION']).tolist() == pytest.approx(np.array([[0, 0, 0], [.02, 0, 0], [0, .02, 0]]))
    assert acc(p['indices']).ravel().tolist() == [0, 1, 2]
    weights = acc(a['WEIGHTS_0']).sum(1)
    if eight:
        weights += acc(a['WEIGHTS_1']).sum(1)
        assert acc(a['JOINTS_1'])[0].tolist() == [1, 0, 1, 0]
    else:
        assert acc(a['JOINTS_0'])[:, 0].tolist() == [1, 0, 1]
        assert 'JOINTS_1' not in a
    assert np.allclose(weights, 1)
    assert doc['nodes'][2]['children'] == [3]
    locals_ = [np.asarray(n['matrix']).reshape(4, 4).T for n in doc['nodes'][2:]]
    worlds = [locals_[0], locals_[0] @ locals_[1]]
    inverse = acc(doc['skins'][0]['inverseBindMatrices']).reshape(2, 4, 4).transpose(0, 2, 1)
    assert np.allclose(np.asarray(worlds) @ inverse, np.eye(4), atol=1e-8)
    iv = doc['bufferViews'][doc['images'][0]['bufferView']]
    im = Image.open(io.BytesIO(binary[iv['byteOffset']:iv['byteOffset'] + iv['byteLength']]))
    assert im.getpixel((2, 2)) == (255, 0, 0, 255)
    assert receipt['source_sha256'] == sha(src) and m.data == src
    assert receipt['gameplay_verified'] is False
    with pytest.raises(FileExistsError):
        export_glb(m, {'pawn\\test\\body': texture()}, out)


def test_missing_texture_and_invalid_lod_create_no_artifact(tmp_path):
    out = tmp_path / 'bad.glb'
    with pytest.raises(ValueError, match='missing exact'):
        export_glb(Model(model()), {}, out)
    with pytest.raises(ValueError, match='LOD'):
        export_glb(Model(model()), {}, out, lod=3)
    assert not out.exists()


@pytest.mark.parametrize('case,error', [
    ('version', 'expected PS3'), ('topology', 'strip topology'), ('bone_cycle', 'cycle'), ('bone_parent', 'parent outside'),
    ('bind', 'matrices disagree'), ('overlap', 'overlapping MOD'), ('palette_size', '64-entry'),
    ('palette_bone', 'absent joint'), ('mesh_palette', 'absent material/group/palette'),
    ('vertex_range', 'vertex range'), ('vertex_budget', 'header budget'),
    ('index_range', 'strip index'), ('weights', 'sum near'), ('uv_nan', 'non-finite'),
    ('texture_index', 'texture index'), ('vertex_format', 'vertex/shader')])
def test_native_corruption_rejected(case, error):
    b = bytearray(model()); bones, groups, mats, meshes, vertices, v2, indices = struct.unpack_from('>7I', b, 44)
    if case == 'version': struct.pack_into('>H', b, 4, 156)
    elif case == 'topology': b[140] = 1
    elif case == 'bone_cycle': b[bones + 1] = 1
    elif case == 'bone_parent': b[bones + 1] = 30
    elif case == 'bind': struct.pack_into('>f', b, bones + 48 + 12 * 4, 9)
    elif case == 'overlap': struct.pack_into('>I', b, 48, bones)
    elif case == 'palette_size': struct.pack_into('>I', b, bones + 304 + 256, 65)
    elif case == 'palette_bone': b[bones + 304 + 260] = 2
    elif case == 'mesh_palette': b[meshes + 46] = 1
    elif case == 'vertex_range': struct.pack_into('>H', b, meshes + 42, 1)
    elif case == 'vertex_budget': struct.pack_into('>I', b, 12, 2)
    elif case == 'index_range': struct.pack_into('>H', b, indices, 3)
    elif case == 'weights': b[vertices + 12] = 0
    elif case == 'uv_nan': struct.pack_into('>e', b, vertices + 24, float('nan'))
    elif case == 'texture_index': struct.pack_into('>I', b, mats + 88, 2)
    elif case == 'vertex_format': struct.pack_into('>I', b, mats + 64, 0xc0400009)
    with pytest.raises(ValueError, match=error):
        Model(b)


def test_owned_chris_sheva_all_lods_and_glb(tmp_path):
    root = Path(os.environ.get('GBOX_RE5_EVIDENCE', str(Path.home() / 'gbox-pr-audit-20261017/re-export-evidence')))
    archives = sorted(root.glob('re5/**/*.arc'))
    if not archives:
        pytest.skip('owned RE5 PS3 ARC evidence unavailable')
    expected = {
        'uPl00ChrisNormal.arc': ('51df8884b6a114101356e19fcc608b69c196e7c0cd56c626a3f7660aeb99d867', 'pawn\\pl\\pl00\\model\\pl0000', 130, 162, 18633),
        'uPl01ShebaNormal.arc': ('27ce670e29438738d024e5ec5a7b729ea5da19eab98a668ada42da9630d92d6f', 'pawn\\pl\\pl01\\model\\pl0100', 147, 179, 18070)}
    assert {p.name for p in archives} == set(expected)
    for path in archives:
        source = path.read_bytes(); digest, name, bones, meshes, lod1_triangles = expected[path.name]
        assert sha(source) == digest
        arc = Arc(source)
        for lod in (1, 2, 4):
            out = tmp_path / (path.stem + f'-lod{lod}.glb')
            result = export_archive(arc, name, out, lod=lod)
            doc, binary, acc = glb(out)
            assert result['bones'] == bones and result['native_meshes'] == meshes
            assert result['bind_matrix_max_error'] < 2e-5
            assert result['archive_sha256'] == digest
            if lod == 1:
                assert result['triangles'] == lod1_triangles
            for primitive in doc['meshes'][0]['primitives']:
                a = primitive['attributes']; pos = acc(a['POSITION']); idx = acc(primitive['indices'])
                assert idx.max() < len(pos)
                sums = np.zeros(len(pos))
                for slot in (0, 1):
                    if f'JOINTS_{slot}' in a:
                        joints = acc(a[f'JOINTS_{slot}']); weights = acc(a[f'WEIGHTS_{slot}'])
                        assert joints.max() < bones
                        sums += weights.sum(1)
                assert np.allclose(sums, 1, atol=1e-6)
            for image in doc['images']:
                v = doc['bufferViews'][image['bufferView']]
                Image.open(io.BytesIO(binary[v['byteOffset']:v['byteOffset'] + v['byteLength']])).verify()
        assert path.read_bytes() == source
