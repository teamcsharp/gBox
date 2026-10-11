"""Representation, alpha, budget and byte-preservation allocator regressions."""
import copy
import struct

import numpy as np
import pytest
from PIL import Image

from gbox import doa2_materials as A


def fixture(spec):
    textures, meshes, binary = [], [], bytearray()
    for index, entry in enumerate(spec):
        w, h, pixel, fmt = entry[:4]
        mode = entry[4] if len(entry) > 4 else (2 if pixel in (0, 2) else 0)
        textures.append((w | (h << 16), pixel | (fmt << 8), 0x0D200000 + len(binary)))
        binary.extend(bytes([index + 1]) * A.T.texture_size(w, h, pixel, fmt))
        # Genuinely textured PVR polygon header with stored source-alpha blend.
        pcw = 0x8000002C | (mode << 24)
        tsp = (4 << 29) | (5 << 26) | (int(np.log2(w // 8)) << 3) | int(np.log2(h // 8))
        tcw = (pixel << 27) | ((fmt == 3) << 30)
        header = bytearray(80)
        struct.pack_into('<4I', header, 0, pcw, 0, tsp, tcw)
        struct.pack_into('<2i', header, 32, index, 1)
        meshes.append({'header': bytes(header)})
    return {'textures': textures, 'models': [{'id': 0, 'meshes': meshes}]}, bytes(binary)


def primitive(color=(255, 255, 255, 255), shape=(8, 8), alpha=None):
    tex = np.full((shape[1], shape[0], 4), 255, dtype=np.uint8)
    if alpha is not None:
        tex[..., 3] = alpha
    return {'tex': tex, 'color': color}


def test_fully_opaque_rgba_uses_rgb_and_base_color_is_baked():
    archive, binary = fixture([(8, 8, 1, 1), (8, 8, 2, 1)])
    result = A.allocate(archive, binary, [primitive((255, 0, 0, 255))])
    assert result['primitives'][0]['texture_id'] == 0
    tex = A.T.descriptors(A.texture_directory(archive), binary)[0]
    assert A.T.decode(tex, result['bin_data']).getpixel((0, 0)) == (255, 0, 0, 255)
    assert result['report']['donor'][0]['alpha'] == 'opaque'


def test_graded_alpha_requires_argb4444_and_translucent_header():
    archive, binary = fixture([(8, 8, 0, 1), (8, 8, 2, 1), (8, 8, 2, 1, 0)])
    source = primitive(alpha=136)
    result = A.allocate(archive, binary, [source])
    assert result['primitives'][0]['texture_id'] == 1
    tex = A.T.descriptors(A.texture_directory(archive), binary)[1]
    assert A.T.decode(tex, result['bin_data']).getpixel((0, 0))[3] == 136


def test_binary_alpha_can_use_native_punch_through():
    archive, binary = fixture([(8, 8, 0, 1, 4)])
    source = primitive()
    source['tex'][:4, :, 3] = 0
    result = A.allocate(archive, binary, [source])
    tex = A.T.descriptors(A.texture_directory(archive), binary)[0]
    image = A.T.decode(tex, result['bin_data'])
    assert image.getpixel((0, 0))[3] == 0
    assert image.getpixel((7, 7))[3] == 255


def test_alpha_capacity_error_has_actionable_candidates():
    archive, binary = fixture([(8, 8, 1, 1), (8, 8, 0, 1)])
    with pytest.raises(A.MaterialCapacityError, match='no compatible native slot') as exc:
        A.allocate(archive, binary, [primitive(alpha=136)])
    assert exc.value.report['donor'][0]['alpha'] == 'graded'
    assert exc.value.report['donor'][0]['candidate_slots'] == 0


def test_assignment_reserves_scarce_alpha_slot_instead_of_greedy_failure():
    archive, binary = fixture([(8, 8, 2, 1), (16, 16, 1, 1)])
    result = A.allocate(archive, binary, [primitive(), primitive(alpha=136)], encode=False)
    assert [m['texture_id'] for m in result['primitives']] == [1, 0]


def test_identical_materials_are_deduplicated_and_textureless_color_is_valid():
    archive, binary = fixture([(8, 8, 1, 1)])
    result = A.allocate(archive, binary, [{'tex': None, 'color': (0, 255, 0, 255)}] * 2)
    assert result['report']['donor_materials'] == 1
    assert len(result['primitives']) == 2
    tex = A.T.descriptors(A.texture_directory(archive), binary)[0]
    assert A.T.decode(tex, result['bin_data']).getpixel((0, 0)) == (0, 255, 0, 255)


def test_native_headers_descriptors_and_all_other_bytes_are_preserved():
    archive, binary = fixture([(8, 8, 1, 1), (8, 8, 2, 1), (16, 16, 1, 1)])
    original = copy.deepcopy(archive)
    result = A.allocate(archive, binary, [primitive((255, 0, 0, 255))])
    assert archive == original
    assert result['descriptor_bytes'] == b''.join(struct.pack('<3I', *d) for d in archive['textures'])
    assert result['materials'][0]['header'] == archive['models'][0]['meshes'][0]['header']
    selected = A.T.descriptors(A.texture_directory(archive), binary)[0]
    assert result['bin_data'][selected.size:] == binary[selected.size:]


@pytest.mark.parametrize('field,value,rejection', [
    (8, (4 << 29) | (5 << 26) | (1 << 3), 'header_dimensions_mismatch'),
    (12, 2 << 27, 'header_pixel_mismatch'),
    (12, (1 << 27) | (1 << 30), 'header_compression_mismatch'),
    (12, (1 << 27) | (1 << 31), 'mipmapped_header'),
    (36, 2, 'unsupported_shader'),
])
def test_header_descriptor_mismatch_is_rejected(field, value, rejection):
    archive, binary = fixture([(8, 8, 1, 1)])
    header = bytearray(archive['models'][0]['meshes'][0]['header'])
    struct.pack_into('<I', header, field, value)
    archive['models'][0]['meshes'][0]['header'] = bytes(header)
    with pytest.raises(A.MaterialCapacityError) as exc:
        A.allocate(archive, binary, [primitive()])
    assert exc.value.report['rejected_headers'][rejection] == 1


def test_original_retained_texture_slots_can_be_protected():
    archive, binary = fixture([(8, 8, 1, 1), (16, 16, 1, 1)])
    result = A.allocate(archive, binary, [primitive((255, 0, 0, 255))], excluded_slots=[0])
    assert result['materials'][0]['texture_id'] == 1
    assert result['bin_data'][:128] == binary[:128]


def test_downsampling_requires_explicit_opt_in_and_reports_target_size():
    archive, binary = fixture([(8, 8, 1, 1)])
    donor = primitive(shape=(16, 16))
    with pytest.raises(A.MaterialCapacityError):
        A.allocate(archive, binary, [donor])
    result = A.allocate(archive, binary, [donor], allow_downscale=True)
    assert result['materials'][0]['source_size'] == (16, 16)
    assert result['materials'][0]['target_size'] == (8, 8)
    assert result['report']['allow_downscale']


def test_empty_donor_and_deterministic_distinct_assignment():
    archive, binary = fixture([(8, 8, 1, 1), (8, 8, 1, 1)])
    assert A.allocate(archive, binary, [])['bin_data'] == binary
    donor = [primitive((255, 0, 0, 255)), primitive((0, 255, 0, 255))]
    first = A.allocate(archive, binary, donor)
    second = A.allocate(archive, binary, donor)
    assert first['bin_data'] == second['bin_data']
    assert len(set(m['texture_id'] for m in first['materials'])) == 2
