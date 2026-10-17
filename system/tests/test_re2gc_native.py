import copy
import json
import os
import struct
from pathlib import Path

import pytest

from gbox.re2gc_native import Model, sha, inventory


def fixture():
    # Independent one-part PLD: one EDD frame, one-bone EMR, one MD1
    # triangle with shared empty quad arrays, and a 4bpp 4x1 TIM.
    edd = struct.pack('<HHI', 1, 4, 0)
    emr = struct.pack('<4H3hHH', 14, 18, 1, 18, 0, 0, 0, 0, 4) + bytes(18)
    verts = struct.pack('<3hH3hH3hH', 1, 2, 3, 0, 4, 5, 6, 0, 7, 8, 9, 0)
    normals = struct.pack('<3hH', 0, 0, 4096, 0)
    indices = struct.pack('<6H', 0, 0, 0, 1, 0, 2)
    table = struct.pack('<14I', 56, 3, 80, 1, 88, 1, 100, 56, 3, 80, 1, 100, 0, 100)
    md1 = struct.pack('<3I', 112, 0, 2) + table + verts + normals + indices + bytes(12)
    tim = struct.pack('<3I4H', 16, 8, 44, 0, 0, 16, 1) + bytes(32)
    tim += struct.pack('<I4H', 14, 0, 0, 1, 1) + b'\x12\x30'
    offsets = [8]
    for s in (edd, emr, md1):
        offsets.append(offsets[-1] + len(s))
    directory = offsets[-1] + len(tim)
    return struct.pack('<II', directory, 4) + edd + emr + md1 + tim + struct.pack('<4I', *offsets)


def test_independent_layout_and_offset_base():
    data = fixture(); m = Model(data)
    assert m.objects[0][0]['vertices'][0] == (1, 2, 3, 0)
    assert m.objects[0][0]['indices'] == [(0, 0, 0, 1, 0, 2)]
    assert m.skeleton['bones'] == 1
    assert m.texture['width'] == 4
    assert m.build() == data


def test_guarded_edit_preserves_every_other_byte_and_shared_array():
    data = fixture(); m = Model(data)
    out = m.edit_vertices([dict(object=0, group='triangles', vertex=0, xyz=[11, -2, 100])], expected_sha256=sha(data))
    at = m.offsets[2] + 68
    assert out[:at] == data[:at] and out[at + 6:] == data[at + 6:]
    assert Model(out).objects[0][1]['vertices'][0] == (11, -2, 100, 0)
    with pytest.raises(ValueError, match='source hash'):
        m.edit_vertices([], expected_sha256='0' * 64)
    with pytest.raises(ValueError, match='conflicting'):
        m.edit_vertices([dict(object=0, group=g, vertex=0, xyz=xyz) for g, xyz in
                         [('triangles', [1, 2, 3]), ('quads', [4, 5, 6])]], expected_sha256=sha(data))


def test_complete_geometry_write_and_budgets():
    data = fixture(); m = Model(data)
    objects = copy.deepcopy(m.objects)
    for g in objects[0]:
        g['vertices'][0] = (100, 200, -300, 0)
    out = m.replace_mesh(objects, expected_sha256=sha(data))
    back = Model(out)
    assert back.objects[0][0]['vertices'][0] == (100, 200, -300, 0)
    assert out[:m.offsets[2]] == data[:m.offsets[2]]
    assert out[m.offsets[3]:] == data[m.offsets[3]:]
    objects[0][0]['indices'] *= 30
    objects[0][0]['uv_bytes'] *= 30
    with pytest.raises(ValueError, match='allocation'):
        m.replace_mesh(objects, expected_sha256=sha(data))


@pytest.mark.parametrize('offset,value', [(0, 0xffffffff), (4, 8), (8 + 2, 0xffff)])
def test_rejects_bad_directory_or_animation(offset, value):
    d = bytearray(fixture())
    struct.pack_into('<I' if offset < 8 else '<H', d, offset, value)
    with pytest.raises(ValueError):
        Model(d)


def test_rejects_mesh_offsets_indices_and_truncation():
    d = fixture(); m = Model(d)
    for at, fmt, value in [(m.offsets[2] + 12, '<I', 0xffffffff),
                           (m.offsets[2] + 12 + 88 + 2, '<H', 99),
                           (m.offsets[1] + 2, '<H', 0xffff)]:
        bad = bytearray(d); struct.pack_into(fmt, bad, at, value)
        with pytest.raises(ValueError):
            Model(bad)
    for n in (0, 8, 22, len(d) - 1):
        with pytest.raises(ValueError):
            Model(d[:n])


def test_invalid_writer_arguments():
    m = Model(fixture())
    for edit in [dict(object=-1, group='triangles', vertex=0, xyz=[1, 2, 3]),
                 dict(object=0, group='triangles', vertex=0, xyz=[32768, 0, 0]),
                 dict(object=0, group='bogus', vertex=0, xyz=[1, 2, 3]),
                 dict(object=0, group='triangles', vertex=True, xyz=[1, 2, 3])]:
        with pytest.raises(ValueError):
            m.edit_vertices([edit], expected_sha256=sha(m.data))


def test_cli_native_write_readback_and_no_overwrite(tmp_path, monkeypatch, capsys):
    from gbox.re2gc_native import main
    src, dst, recipe = (tmp_path / n for n in ('source.pld', 'changed.pld', 'edits.json'))
    src.write_bytes(fixture())
    recipe.write_text(json.dumps([dict(object=0, group='triangles', vertex=0, xyz=[11, 22, 33])]))
    monkeypatch.setattr('sys.argv', ['re2gc_native', str(src), '--out', str(dst), '--edit-json', str(recipe),
                                    '--expected-sha256', sha(fixture())])
    main()
    receipt = json.loads(capsys.readouterr().out)
    assert receipt['readback_verified'] and not receipt['gameplay_verified']
    assert src.read_bytes() == fixture()
    assert Model(dst.read_bytes()).objects[0][0]['vertices'][0] == (11, 22, 33, 0)
    with pytest.raises(FileExistsError):
        main()


def test_owned_all_player_models_and_changed_native_write():
    path = os.environ.get('GBOX_RE2GC_SOURCE')
    if not path:
        pytest.skip('set GBOX_RE2GC_SOURCE to the owned GHAE08 GCZ/ISO')
    report = inventory(path)
    assert len(report['player_models']) == 40
    assert all(r['noop_identical'] for r in report['player_models'])
    from gbox.gcdisc import GCDisc
    disc = GCDisc(path)
    try:
        data = disc.read('Pl0/PLD/PL00.PLD'); m = Model(data)
        assert sha(data) == '02ccf44b0a3b1123e004db054e1bf47f1817d4d41184b1d00516715545f5996a'
        assert len(m.objects) == m.skeleton['bones'] == 15
        groups = copy.deepcopy(m.objects)
        for group in groups[0]:
            x, y, z, w = group['vertices'][0]
            group['vertices'][0] = (x + 1, y, z, w)
        changed = m.replace_mesh(groups, expected_sha256=sha(data))
        readback = Model(changed)
        assert readback.objects[0][0]['vertices'][0][0] == m.objects[0][0]['vertices'][0][0] + 1
        assert changed[:m.offsets[2]] == data[:m.offsets[2]]
        assert changed[m.offsets[3]:] == data[m.offsets[3]:]
        assert disc.read('Pl0/PLD/PL00.PLD') == data
    finally:
        disc.f.close()
