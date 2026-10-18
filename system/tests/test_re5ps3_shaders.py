import json
import os
from pathlib import Path
import struct

import pytest

from gbox import re5ps3_shaders as shaders


# Literal instructions independently decoded with the pinned RPCS3 unions.
# Vertex ADD input 8.xy + C461.xy -> numeric output 7.xy, plus end flag.
VERTEX = bytes.fromhex('401f9c6c00dcd8080106c08200619f9d')
# Fragment TEX from input TEX0 (attribute 4), texture 0, condition mask 7,
# end flag is bit 16 of the first stored BE word (half-word swapped).
FRAGMENT = bytes.fromhex('9e011700c8011c9dc8000001c8003fe1')


def cg(code, profile):
    domain = (len(code) // 16, 0, 0, 0x100, 0, 0) if profile == 7003 else (len(code) // 16, 0x4000, 0, 0, 0, 0)
    return (struct.pack('>8I', profile, 6, 64 + len(code), 0, 0, 32, len(code), 64)
            + struct.pack('>6I', *domain) + bytes(8) + code)


def bfx():
    """Small independent layout: 6 binary dimensions, 3 VS, 2 PS.

    Selector 1 deliberately uses vertex 2/fragment 1 so transposed halves
    or an incorrectly chosen permutation cannot pass.
    """
    body = bytearray(1380)
    struct.pack_into('>15I', body, 0, 64, 6, 64, 2, 3, 60, 1024, 1280, 1292, 0, 0, 0, 0, 0, 0)
    string_at = 180
    for i, name in enumerate(shaders.FUNCTIONS):
        names = [name, name + '_ZERO', name + '_ONE']
        pointers = []
        for text in names:
            pointers.append(string_at)
            raw = text.encode() + b'\0'
            body[string_at:string_at + len(raw)] = raw
            string_at += len(raw)
        struct.pack_into('>3I', body, 60 + i * 12, pointers[0], ((1 << i) << 8) | 2, 132 + i * 8)
        struct.pack_into('>2I', body, 132 + i * 8, *pointers[1:])
    struct.pack_into('>I', body, 1028, 0x00010002)
    struct.pack_into('>3I', body, 1280, 1300, 1316, 1332)
    struct.pack_into('>2I', body, 1292, 1348, 1364)
    programs = [cg(VERTEX, 7003) for _ in range(3)] + [cg(FRAGMENT, 7004) for _ in range(2)]
    cursor = 0
    for i, code in enumerate(programs):
        values = (cursor, 0, len(code), 0x100) if i < 3 else (cursor, 0, 0, len(code))
        struct.pack_into('>4I', body, 1300 + i * 16, *values)
        cursor += len(code)
    header = struct.pack('>4sHHI7I', b'\0XFB', 0x2004, 1, 0, shaders.TECHNIQUE,
                         len(body), cursor, 0, 0, 0, 0)
    return header + body + b''.join(programs)


def archive(payload):
    name = shaders.MEMBER.encode()
    return (struct.pack('>4sHH', b'\0CRA', 8, 1) + name.ljust(64, b'\0')
            + struct.pack('>4I', shaders.TYPE_HASH, len(payload), len(payload) << 3, 88) + payload)


def test_literal_native_instructions_have_exact_operands_and_no_fake_runtime_claim():
    v = shaders.vertex_instructions(VERTEX)[0]
    assert v['vector_opcode'] == 3 and v['scalar_opcode'] == 0
    assert v['input_operands'] == [0] and v['input_attribute'] == 8
    assert v['sources'][1]['position'] == 2 and v['sources'][1]['constant_index'] == 461
    assert v['sources'][0]['swizzle'] == 'xyxx'  # only xy is written
    assert v['vector_result'] and v['destination'] == 7 and v['vector_write_mask'] == 12
    assert not v['condition_test'] and not v['saturate']
    f = shaders.fragment_instructions(FRAGMENT)[0]
    assert f['opcode'] == 23 and f['input_attribute'] == 4 and f['texture_unit'] == 0
    assert f['condition_mask'] == 7 and f['input_operands'] == [0]
    assert f['embedded_constant_hex'] == ''


def test_selector_dimensions_and_halves_select_actual_program_bytes():
    result = shaders.report(archive(bfx()), [0x10000000])
    row = result['materials'][0]
    assert row['selector_index'] == 1 and row['vertex_index'] == 2 and row['fragment_index'] == 1
    assert row['function_values'] == [1, 0, 0, 0, 0, 0]
    assert row['vertex']['sha256'] == shaders.sha(cg(VERTEX, 7003))
    assert row['fragment']['sha256'] == shaders.sha(cg(FRAGMENT, 7004))
    assert result['source']['archive_member'] == shaders.MEMBER
    assert 'no runtime vertex-buffer binding' in result['scope']


@pytest.mark.parametrize('offset,fmt,value,error', [
    (4, '>H', 0x2005, 'envelope'), (6, '>H', 2, 'envelope'),
    (8, '>I', 4097, 'envelope'), (12, '>I', 0, 'technique layout'),
    (16, '>I', 0xffffffff, 'technique layout'), (28, '>I', 1, 'technique layout'),
    (40 + 8, '>I', 63, 'selector counts'),
    (40 + 24, '>I', 0xffffffff, 'relative field'),
    (40 + 64, '>I', 0x302, 'function dimension'),
    (40 + 68, '>I', 0xffffffff, 'relative field'),
    (40 + 1024, '>I', 3, 'program index'),
    (40 + 1024, '>I', 0x20000, 'program index'),
    (40 + 1284, '>I', 1300, 'contiguous'),
    (40 + 1300, '>I', 1, 'contiguous'),
    (40 + 1308, '>I', 0xffffffff, 'compiled program'),
    (40 + 1312, '>I', 0, 'masks disagree'),
    (1420, '>I', 7004, 'profile'), (1424, '>I', 5, 'revision'),
    (1428, '>I', 79, 'envelope'), (1432, '>I', 1, 'envelope'),
    (1448, '>I', 65, 'envelope'), (1444, '>I', 32, 'instruction extent'),
    (1452, '>I', 2, 'slot count'), (1456, '>I', 4, 'load slot'),
])
def test_malformed_container_is_rejected_before_output(tmp_path, offset, fmt, value, error):
    data = bytearray(bfx())
    struct.pack_into(fmt, data, offset, value)
    source = tmp_path / 'bad.bfx'
    source.write_bytes(data)
    output = tmp_path / 'report.json'
    with pytest.raises(ValueError, match=error):
        shaders.main([str(source), '--material', '10000000', '--out', str(output)])
    assert not output.exists()
    assert source.read_bytes() == data


def test_permutation_sentinel_and_invalid_function_rejected():
    data = bytearray(bfx())
    struct.pack_into('>I', data, 40 + 1028, 0xffffffff)
    parsed = shaders.StandardShader(data)
    with pytest.raises(ValueError, match='unsupported by this BFX'):
        parsed.inspect_material(0x10000000)
    with pytest.raises(ValueError, match='outside BFX dimension'):
        parsed.inspect_material(0x20000000)
    for value in (-1, 2**32, True):
        with pytest.raises(ValueError, match='uint32'):
            parsed.inspect_material(value)


def test_fragment_constant_is_data_not_an_instruction_and_must_fit():
    # MOV constant, end flag; embedded 16 bytes deliberately look invalid.
    stored = bytes.fromhex('0001010000021c9d0000000000000000')
    row = shaders.fragment_instructions(stored + bytes([255]) * 16)[0]
    assert row['source_types'] == [2] and not row['input_operands']
    assert row['embedded_constant_hex'] == 'ff' * 16
    with pytest.raises(ValueError, match='embedded constant'):
        shaders.fragment_instructions(stored)


@pytest.mark.parametrize('kind,code,error', [
    ('vertex', VERTEX[:-1], 'extent'),
    ('fragment', FRAGMENT[:-1], 'extent'),
    ('vertex', VERTEX[:-1] + bytes([VERTEX[-1] & 254]), 'end flag'),
    ('fragment', bytes.fromhex('9e001700') + FRAGMENT[4:], 'end flag'),
    ('vertex', VERTEX + VERTEX, 'end flag'),
    ('fragment', FRAGMENT + FRAGMENT, 'end flag'),
    ('vertex', bytes.fromhex('401f9c6cf8dcd808') + VERTEX[8:], 'opcode'),
    ('fragment', bytes.fromhex('9e013f00') + FRAGMENT[4:], 'opcode'),
    ('vertex', bytes.fromhex('481f9c6c') + VERTEX[4:], 'indexed vertex'),
])
def test_unsupported_or_truncated_instruction_stream_fails(kind, code, error):
    with pytest.raises(ValueError, match=error):
        getattr(shaders, kind + '_instructions')(code)


def test_vertex_bri_target_is_bounded_and_never_reported_as_an_input():
    # BRI immediate target zero, no vector op, no scalar source operands.
    code = struct.pack('>4I', 0, 9 << 27, 0, 1)
    row = shaders.vertex_instructions(code)[0]
    assert row['branch_target'] == 0 and row['input_operands'] == []
    with pytest.raises(ValueError, match='branch target'):
        shaders.vertex_instructions(struct.pack('>4I', 0, 9 << 27, 0, (1 << 29) | 1))


def test_cli_is_exclusive_and_retains_exact_source(tmp_path):
    source, output = tmp_path / 'shader.arc', tmp_path / 'report.json'
    original = archive(bfx())
    source.write_bytes(original)
    args = [str(source), '--material', '10000000', '--out', str(output)]
    assert shaders.main(args) == 0
    saved = output.read_bytes()
    assert json.loads(saved)['source']['sha256'] == shaders.sha(original)
    with pytest.raises(FileExistsError):
        shaders.main(args)
    assert output.read_bytes() == saved and source.read_bytes() == original


def test_selected_code_budget_checked_before_instruction_expansion(monkeypatch):
    monkeypatch.setattr(shaders, 'MAX_REPORT_CODE', 31)
    monkeypatch.setattr(shaders, 'vertex_instructions', lambda _: pytest.fail('allocated before budget'))
    with pytest.raises(ValueError, match='report budget'):
        shaders.report(bfx(), [0])


@pytest.fixture(scope='module')
def owned_shader():
    base = Path(os.environ.get('GBOX_RE5_EVIDENCE', str(Path.home() / 'gbox-pr-audit-20261017/re-export-evidence')))
    source = base / 're5-shader-evidence-v2/shader.arc'
    if not source.exists():
        pytest.skip('requires exact owned RE5 PS3 shader.arc evidence')
    data = source.read_bytes()
    assert shaders.sha(data) == '15fabaa9c14c41d3bac8c85286aa6454a86455f36d1e9ebcc2012cf7a29f2f1d'
    return source, data


def test_owned_material_selector_and_instruction_evidence(owned_shader, tmp_path):
    source, original = owned_shader
    output = tmp_path / 'owned-shaders.json'
    shaders.main([str(source), '--material', '30800000', '--material', '30844000',
                  '--material', '40844000', '--out', str(output)])
    result = json.loads(output.read_text())
    assert result['source']['decoded_sha256'] == '8365be586941efd7fce15151546327909c57f593cd0b222f39a44865008f7981'
    assert (result['envelope']['selectors'], result['envelope']['vertex_programs'], result['envelope']['fragment_programs']) == (80640, 47, 82)
    assert [(r['selector_index'], r['vertex_index'], r['fragment_index']) for r in result['materials']] == [(19, 3, 0), (379, 8, 9), (380, 9, 9)]
    vertex_hashes = ['03ed9fe54e867340b11bbfa02e7f655ff1113902aebc538190e1591d0a524ff7',
                     'd7ebcf3d7e36b225da45cf6947f0201f599f5f448865aa03bd6ae47a3a1ff581',
                     'c24b4312fd0808deadc8b6b64e9053948ca284f55aaf6d3c65c10f1d0d4f9f8b']
    for row, expected, at in zip(result['materials'], vertex_hashes, (51, 51, 63)):
        assert row['vertex']['sha256'] == expected
        uv = [r for r in row['vertex']['direct_input_instructions'] if r['input_attribute'] == 8]
        assert uv[0]['instruction'] == at and uv[0]['vector_opcode'] == 3
        assert uv[0]['destination'] == 7 and uv[0]['vector_write_mask'] == 12
        assert uv[0]['input_operands'] == [0] and not uv[0]['condition_test']
        assert len(row['vertex']['branch_instructions']) == 3  # static observations, not execution proof
    for row, offset, count, expected in zip(result['materials'], (5264, 7184, 7184), (249, 343, 343),
        ('0a6c3287be83514f1b94f8a58c6c2b1dfbd562fe2d8d165c10a1f34c72feae0d',
         '2410d454d1f102b8737c3d72fecbba027b572a430fdf4c423897bd8969725b02',
         '2410d454d1f102b8737c3d72fecbba027b572a430fdf4c423897bd8969725b02')):
        assert row['fragment']['sha256'] == expected and row['fragment']['decoded_instructions'] == count
        sample = [r for r in row['fragment']['texture_instructions'] if r['code_byte_offset'] == offset][0]
        assert sample['opcode'] == 23 and sample['input_attribute'] == 4 and sample['texture_unit'] == 0
        assert sample['condition_mask'] == 7 and sample['input_operands'] == [0]
        assert sample['raw_hex'] in ('9e001700c8011c9dc8000001c8003fe1', '9e061700c8011c9dc8000001c8003fe1')
    assert source.read_bytes() == original
