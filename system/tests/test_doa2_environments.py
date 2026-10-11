"""Portable native stage records, mip offsets, provenance and tool routing."""
import hashlib
import json
import math
import struct
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from gbox import doa2_environments as E, doa2_geometry as G, doa2_lab as L, doa2_textures as T
from test_doa2_geometry import archive


def stage(pixel=1, fmt=1, width=8):
    data = bytearray(archive(1))
    table = struct.unpack_from('<I', data, 8)[0]
    struct.pack_into('<3I', data, table, width | width << 16, pixel | fmt << 8, 0x0d200000)
    return bytes(data), bytes(T.texture_size(width, width, pixel, fmt))


def sentinel_fixture():
    data, body = stage()
    record = G.decode_chr(data)['models'][0]['meshes'][0]['records'][0]
    changed = bytearray(data)
    changed[record['offset'] + 28:record['offset'] + 32] = bytes.fromhex('ffffbf7f')
    return bytes(changed), body, record['offset']


def test_source_preview_requires_exact_explicit_sentinel_and_roundtrips_raw_bytes():
    data, _, offset = sentinel_fixture()
    with pytest.raises(ValueError, match='non-finite'):
        G.decode_chr(data)
    decoded = G.decode_chr(data, preview_v_sentinel_offsets=[offset])
    assert decoded['preview_uv_substitutions'] == [
        {'model': 0, 'mesh': 0, 'offset': offset, 'vertex': 0, 'source_word': '7fbfffff', 'preview_v': 0.0}]
    assert decoded['models'][0]['meshes'][0]['vertices'][0][-1] == 0.0
    assert G.roundtrip_chr(decoded) == data
    # No arbitrary NaN receives the original STAGE03 identity's preview policy.
    with pytest.raises(ValueError, match='non-finite'):
        E.decode_archive(data, 'STAGE03')


@pytest.mark.parametrize('attribute', [0, 12, 24])
def test_uv_exception_does_not_allow_nonfinite_position_normal_or_u(attribute):
    data, _, offset = sentinel_fixture()
    data = bytearray(data)
    struct.pack_into('<f', data, offset + attribute, math.inf)
    with pytest.raises(ValueError, match='non-finite'):
        G.decode_chr(bytes(data), preview_v_sentinel_offsets=[offset])


def test_preview_offsets_must_match_inline_sentinel_and_exact_word():
    data, _, offset = sentinel_fixture()
    with pytest.raises(ValueError, match='inline vertex'):
        G.decode_chr(stage()[0], preview_v_sentinel_offsets=[len(data) + 50])
    with pytest.raises(ValueError, match='pinned record'):
        G.decode_chr(stage()[0], preview_v_sentinel_offsets=[offset])
    corrupt = bytearray(data)
    struct.pack_into('<I', corrupt, offset + 28, 0x7fc00000)
    with pytest.raises(ValueError, match='pinned record'):
        G.decode_chr(bytes(corrupt), preview_v_sentinel_offsets=[offset])
    for value in (-1, '4'):
        with pytest.raises(ValueError, match='invalid preview'):
            G.decode_chr(data, preview_v_sentinel_offsets=[value])


@pytest.mark.parametrize('side,offset,size', [(16, 176, 704), (64, 2736, 10944), (128, 10928, 43712)])
def test_raw_mipmap_reserved_prefix_native_base_offset_and_trailing_padding(side, offset, size):
    assert T.base_level_offset(side, side, 2) == offset
    assert T.texture_size(side, side, 1, 2) == size
    c, b = stage(fmt=2, width=side)
    tex = T.descriptors(c, b)[0]
    # Smaller levels and alignment bytes deliberately differ from the base.
    b = bytearray(b'\x1f\x00' * (len(b) // 2))
    b[offset:offset + 2 * side * side] = b'\x00\xf8' * (side * side)
    chunk = T.pvr_chunk(tex, bytes(b))
    assert len(chunk) == 16 + offset + 2 * side * side
    assert chunk[16:] == b[:tex.payload_size]
    image = T.decode(tex, bytes(b))
    assert image.getpixel((0, 0)) == (255, 0, 0, 255)
    assert image.getpixel((side - 1, side - 1)) == (255, 0, 0, 255)


@pytest.mark.parametrize('side,offset,size', [(64, 2390, 3424), (256, 7510, 23904), (512, 23894, 89440)])
def test_vq_mipmap_native_offsets_with_padding(side, offset, size):
    assert T.base_level_offset(side, side, 4) == offset
    assert T.texture_size(side, side, 1, 4) == size
    c, b = stage(fmt=4, width=side)
    tex = T.descriptors(c, b)[0]
    body = bytearray(b)
    # Code0 blue, code1 red; smaller levels choose0, base chooses1, pad0xff.
    body[:8] = b'\x1f\x00' * 4
    body[8:16] = b'\x00\xf8' * 4
    body[offset:tex.payload_size] = bytes([1]) * (side * side // 4)
    body[tex.payload_size:] = bytes([255]) * (tex.size - tex.payload_size)
    image = T.decode(tex, bytes(body))
    assert image.getpixel((0, 0)) == (255, 0, 0, 255)
    assert image.getpixel((side - 1, side - 1)) == (255, 0, 0, 255)


def test_mips_reject_rectangle_truncation_and_authored_replacement():
    with pytest.raises(ValueError, match='square'):
        T.texture_size(16, 8, 1, 2)
    from PIL import Image
    for fmt in (2, 4):
        c, b = stage(fmt=fmt, width=16)
        with pytest.raises(ValueError, match='allocation'):
            T.descriptors(c, b[:-1])
        with pytest.raises(ValueError, match='encoded'):
            T.replace(c, b, {0: Image.new('RGBA', (16, 16), 'red')})


def test_select_native_archives_without_inventing_arena_names_or_supplements():
    files = {'DOA2/STAGE03.CHR': (1, 2), 'DOA2/STAGE03.BIN': (1, 2),
             'DOA2/STAGE04.CHR': (1, 2), 'DOA2/EFC00.CHR': (1, 2),
             'DOA2/STAGE00_EXTRA.CHR': (1, 2), 'DOA2/KAS00.CHR': (1, 2)}
    assert [r['name'] for r in E.select(files)] == ['STAGE03', 'STAGE04']
    assert E.select(files, '3')[0]['available'] is True
    assert E.select(files, 'DOA2/STAGE04.CHR')[0]['available'] is False
    for value in ('../STAGE03', 'Kasumi', '', '100'):
        with pytest.raises(ValueError, match='explicit'):
            E.select(files, value)
    with pytest.raises(ValueError, match='absent'):
        E.select(files, 'STAGE05')


def test_editable_export_preserves_native_files_geometry_identity_and_pvr_chain(tmp_path):
    c, b = stage(pixel=0, fmt=2, width=16)
    out = tmp_path / 'new-stage'
    report = E.export_assets(c, b, out, 'STAGE00', source={'game_id': 'owned-fixture'})
    assert (out / 'native/STAGE00.CHR').read_bytes() == c
    assert (out / 'native/STAGE00.BIN').read_bytes() == b
    assert (out / 'native/tex000.pvr').read_bytes() == T.pvr_chunk(T.descriptors(c, b)[0], b)
    manifest = json.loads((out / 'manifest.json').read_text())
    assert manifest['skeleton'] == manifest['animations'] == manifest['collision'] == []
    assert manifest['meshes'][0]['positions'] == [list(v[:3]) for v in G.decode_chr(c)['models'][0]['meshes'][0]['vertices']]
    assert report['triangles'] == 2 and report['images_decoded'] == 1
    assert report['gameplay_verified'] is report['native_reimport_supported'] is False
    assert report['parts'][0]['model_id'] == 0
    assert manifest['provenance'][0]['sha256'] == hashlib.sha256(c).hexdigest()
    gltf = json.loads((out / 'STAGE00_parts.gltf').read_text())
    assert gltf['materials'][0]['alphaMode'] == 'MASK'
    assert not gltf.get('skins')
    glb = (out / 'STAGE00_parts.glb').read_bytes()
    assert struct.unpack_from('<III', glb) == (0x46546c67, 2, len(glb))
    glb_json = json.loads(glb[20:20 + struct.unpack_from('<I', glb, 12)[0]])
    assert glb_json['materials'] == gltf['materials']
    assert 'uri' not in glb_json['images'][0] and glb_json['images'][0]['mimeType'] == 'image/png'
    original = {p.relative_to(out): p.read_bytes() for p in out.rglob('*') if p.is_file()}
    with pytest.raises(FileExistsError):
        E.export_assets(c, b, out, 'STAGE00')
    assert original == {p.relative_to(out): p.read_bytes() for p in out.rglob('*') if p.is_file()}


def test_corrupt_texture_or_material_does_not_create_completed_output(tmp_path):
    c, b = stage()
    out = tmp_path / 'bad'
    with pytest.raises(ValueError, match='allocation'):
        E.export_assets(c, b[:-1], out, 'STAGE00')
    assert not out.exists()
    changed = bytearray(c)
    mesh = G.decode_chr(c)['models'][0]['meshes'][0]
    struct.pack_into('<i', changed, mesh['offset'] + 32, 1)
    with pytest.raises(ValueError, match='texture slot'):
        E.export_assets(bytes(changed), b, out, 'STAGE00')
    assert not out.exists()


def test_environment_tool_route_is_independent_of_fighter_rig_and_reports_missing_pair(tmp_path, monkeypatch):
    from gbox import characters as C, doa2_swap as S, gdrom
    c, b = stage()
    bodies = {'1ST_READ.BIN': b'exact-test-code', 'DOA2/STAGE00.CHR': c, 'DOA2/STAGE00.BIN': b,
              'DOA2/STAGE01.CHR': c}
    monkeypatch.setattr(gdrom, 'GDRom', lambda _: SimpleNamespace(files=bodies, read=bodies.__getitem__))
    monkeypatch.setattr(C, '_api', lambda *a: {})
    monkeypatch.setattr(C, '_dc_gdi', lambda *a: 'owned-test.gdi')
    monkeypatch.setattr(S, 'EXECUTABLE_SHA256', hashlib.sha256(bodies['1ST_READ.BIN']).hexdigest())
    def reject_fighter(*args):
        raise AssertionError('Environment route must not select a fighter')
    monkeypatch.setattr(L, 'selected_costumes', reject_fighter)
    artifacts = {}
    ctx = SimpleNamespace(config=SimpleNamespace(data_dir=tmp_path), progress=lambda *a: None,
                          artifact=lambda name, body, *a, **kw: artifacts.update({name: body}))
    result = L.doa2_assets(L.Doa2In(op='environments'), ctx)['result']
    assert result['verified_archives'] == result['unsupported_archives'] == 1
    assert result['inventory_archives'] == result['selected_archives'] == 2
    assert result['available_archives'] == 1
    assert result['environments'][1]['reason'] == 'Corresponding native BIN is absent'
    assert result['gameplay_verified'] is False
    assert json.loads(artifacts['doa2-details.json']) == result
    inp = L.Doa2In(op='environments', environment='STAGE00', environment_action='decompose')
    first = L.doa2_assets(inp, ctx)['result']['environments'][0]
    second = L.doa2_assets(inp, ctx)['result']['environments'][0]
    assert first['path'] != second['path']
    assert (tmp_path / 'analysis/doa2' / inp.game_id / 'environments').is_dir()
    assert first['images_decoded'] == 1
    assert L.Doa2In().op == 'inspect'
    with pytest.raises(ValidationError):
        L.Doa2In(op='environments', environment_action='build')
    monkeypatch.setattr(S, 'EXECUTABLE_SHA256', '0' * 64)
    with pytest.raises(ValueError, match='Unsupported executable identity'):
        L.doa2_assets(inp, ctx)
