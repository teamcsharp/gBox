import struct

import numpy as np
import pytest

from gbox.re5ps3_arc import Arc, sha
from gbox.re5ps3_models import Model, export_archive, export_glb
from test_re5ps3_group_ids import owned_pack
from test_re5ps3_models import glb, model, texture


def ranged_model(*, eight=False, secondary=0):
    """Seven allocated vertices, with a three-vertex referenced interior."""
    data = bytearray(model(eight))
    h = list(struct.unpack_from('>4H15I', data, 4))
    meshes, vertices = h[15], h[16]
    original = [bytes(data[vertices + i * 32:vertices + (i + 1) * 32]) for i in range(3)]
    allocation = b''.join(original[i] for i in (0, 1, 0, 1, 2, 1, 2))
    # One stream-offset row + two vertexStart rows precede the allocation.
    # They are deliberately invalid vertex data and must never be decoded.
    primary = bytes([255]) * 96 + allocation
    second = bytes(40 if secondary == 4 else 80 if secondary == 8 else 0)
    indices = struct.pack('>7H', 4, 5, 6, 65535, 6, 5, 4)
    data[vertices:] = primary + second + indices
    h[4], h[5], h[7], h[8] = 7, 8, len(primary), len(second)
    h[17], h[18] = vertices + len(primary), vertices + len(primary) + len(second)
    struct.pack_into('>4H15I', data, 4, *h)
    data[meshes + 9] = secondary
    struct.pack_into('>HH6I', data, meshes + 12, 7, 6, 2, 32, secondary, 0, 7, 0)
    struct.pack_into('>H', data, meshes + 42, 4)
    return bytes(data)


@pytest.mark.parametrize('eight', [False, True])
@pytest.mark.parametrize('secondary', [0, 4, 8])
def test_referenced_interior_preserves_allocation_and_native_triangle_attributes(tmp_path, eight, secondary):
    native = ranged_model(eight=eight, secondary=secondary)
    parsed = Model(native)
    mesh = parsed.meshes[0]
    assert mesh['positions'].shape == (7, 3)
    expected_positions = np.array([[0, 0, 0], [2, 0, 0], [0, 0, 0], [2, 0, 0],
                                   [0, 2, 0], [2, 0, 0], [0, 2, 0]])
    assert np.array_equal(mesh['positions'], expected_positions)
    assert mesh['triangles'].tolist() == [[2, 3, 4], [4, 3, 2]]
    assert np.array_equal(mesh['uv'], [[0, 0], [.5, .5], [0, 0], [.5, .5], [1, 1], [.5, .5], [1, 1]])
    assert np.allclose(mesh['weights'].sum(1), 1)
    output = tmp_path / 'ranged.glb'
    export_glb(parsed, {r'pawn\test\body': texture()}, output)
    document, _, accessor = glb(output)
    primitive = document['meshes'][0]['primitives'][0]
    actual_indices = accessor(primitive['indices']).reshape(-1, 3)
    assert np.array_equal(actual_indices, [[2, 3, 4], [4, 3, 2]])
    assert np.allclose(accessor(primitive['attributes']['POSITION']), expected_positions * .01)
    assert np.array_equal(accessor(primitive['attributes']['TEXCOORD_0']), mesh['uv'])
    assert parsed.data == native


@pytest.mark.parametrize('field,fmt,value,error', [
    (42, '>H', 1, 'mesh vertex range'),  # minimum before allocation
    (42, '>H', 7, 'mesh vertex range'),  # minimum after maximum
    (14, '>H', 9, 'mesh vertex range'),  # maximum at allocation end
    (16, '>I', 5, 'mesh vertex range'),  # allocation starts after minimum
    (36, '>I', 1, 'mesh vertex range'),  # still unsupported index-value offset
    (8, '>B', 31, 'mesh vertex range'),  # still unsupported primary stride
    (9, '>B', 3, 'mesh vertex range'),  # still unsupported secondary stride
    (20, '>I', 64, 'vertices outside vertex section'),
    (24, '>I', 8, 'secondary vertices outside vertex section'),
])
def test_bad_allocations_and_stride_declarations_remain_rejected_without_output(tmp_path, field, fmt, value, error):
    native = bytearray(ranged_model(secondary=4))
    mesh_at = struct.unpack_from('>I', native, 56)[0]
    struct.pack_into(fmt, native, mesh_at + field, value)
    output = tmp_path / 'bad.glb'
    with pytest.raises(ValueError, match=error):
        export_glb(Model(native), {r'pawn\test\body': texture()}, output)
    assert not output.exists()


@pytest.mark.parametrize('index', [2, 3, 7, 8, 9])
def test_strip_indices_must_stay_in_declared_used_range_even_within_allocation(tmp_path, index):
    native = bytearray(ranged_model())
    at = struct.unpack_from('>I', native, 68)[0]
    struct.pack_into('>H', native, at, index)
    output = tmp_path / 'bad.glb'
    with pytest.raises(ValueError, match='strip index outside mesh vertices'):
        export_glb(Model(native), {r'pawn\test\body': texture()}, output)
    assert not output.exists()


def _independent_strip(indices):
    result, segment = [], []
    for index in indices:
        if index == 65535:
            segment = []
            continue
        segment.append(int(index))
        if len(segment) >= 3:
            a, b, c = segment[-3:]
            if len({a, b, c}) == 3:
                result.append((a, b, c) if len(segment) % 2 else (b, a, c))
    return np.array(result)


def test_owned_jill_range_matches_independent_referenced_surface_and_keeps_uv_failure(tmp_path):
    path = owned_pack('uPl02JillCos1.arc')
    source = path.read_bytes()
    assert sha(source) == '91dcabf061cf6c164114609d16c5b141aed2ced044cef8a0ffe7c97903dcf585'
    arc = Arc(source)
    member = r'pawn\pl\pl02\model\Pl0200'
    native = arc.read(next(e for e in arc.entries if e.name == member))
    assert sha(native) == '3371880dc7c213b4604bb73e3c2cc51dde6798ed6655a65128e8c90a105dc5fb'
    # Inspect the successfully decoded prefix only after construction fails.
    # This deliberately does not make a partial Model available for export.
    parsed = Model.__new__(Model)
    with pytest.raises(ValueError, match='MOD UVs has a non-finite'):
        Model.__init__(parsed, native)
    assert len(parsed.meshes) == 96
    mesh = parsed.meshes[13]
    h = struct.unpack_from('>4H15I', native, 4)
    descriptor = h[15] + 13 * 52
    count, maximum, start, offset, _, first, ni, base = struct.unpack_from('>HH6I', native, descriptor + 12)
    minimum = struct.unpack_from('>H', native, descriptor + 42)[0]
    assert (count, start, minimum, maximum, base) == (208, 5418, 5420, 5625, 0)
    indices = np.frombuffer(native, dtype='>u2', count=ni, offset=h[18] + first * 2)
    native_triangles = _independent_strip(indices)
    assert (int(indices[indices != 65535].min()), int(indices[indices != 65535].max())) == (minimum, maximum)
    assert np.array_equal(mesh['triangles'] + start, native_triangles)
    assert mesh['positions'].shape == (208, 3)
    # An independent cropped reader addresses only [minimum, maximum]. Its
    # referenced geometry must equal the full-allocation reader's triangles.
    rows = [native[h[16] + offset + i * 32:h[16] + offset + (i + 1) * 32]
            for i in range(minimum, maximum + 1)]
    bounds_min = np.array(struct.unpack_from('>3f', native, 96))
    bounds_max = np.array(struct.unpack_from('>3f', native, 112))
    positions = np.array([struct.unpack_from('>3h', row) for row in rows]) / 32767 * (bounds_max - bounds_min) + bounds_min
    normals = np.array([list(row[16:19]) for row in rows]) / 127.5 - 1
    normals /= np.linalg.norm(normals, axis=1)[:, None]
    uv = np.array([struct.unpack_from('>2e', row, 24) for row in rows])
    weights = np.array([list(row[12:16]) for row in rows], dtype=float)
    weights /= weights.sum(1)[:, None]
    palette_at = h[12] + h[1] * 152 + 256 + native[descriptor + 46] * 68
    palette_n = struct.unpack_from('>I', native, palette_at)[0]
    palette = native[palette_at + 4:palette_at + 4 + palette_n]
    fallback = native[h[12] + h[1] * 152:h[12] + h[1] * 152 + 256]
    joints = np.array([[0 if not weights[v, c] else palette[j] if j < len(palette) else fallback[j]
                       for c, j in enumerate(row[8:12])] for v, row in enumerate(rows)])
    for key, expected in [('positions', positions), ('normals', normals), ('uv', uv), ('weights', weights), ('joints', joints)]:
        assert np.allclose(mesh[key][mesh['triangles']], expected[native_triangles - minimum], rtol=0, atol=1e-12)
    bad_at = h[15] + 96 * 52
    bad_start, bad_off = struct.unpack_from('>2I', native, bad_at + 16)
    assert native[h[16] + bad_off + bad_start * 32 + 24:h[16] + bad_off + bad_start * 32 + 28] == bytes.fromhex('ffffffff')
    output = tmp_path / 'jill.glb'
    with pytest.raises(ValueError, match='MOD UVs has a non-finite'):
        export_archive(arc, member, output)
    assert not output.exists()
    assert path.read_bytes() == source and sha(native) == '3371880dc7c213b4604bb73e3c2cc51dde6798ed6655a65128e8c90a105dc5fb'
