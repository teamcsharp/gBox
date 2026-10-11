import struct
from pathlib import Path

import pytest

from gbox import naomilib

GDI = Path.home() / 'gbox-cache/dc/1de2e7634f3161ff/disc.gdi'  # owned DOA2 LE (Japan)


def _vertex(x, y, z, u, v):
    return struct.pack('<3f3f2f', x, y, z, 0.0, 0.0, 1.0, u, v)


def _model(texture=3, declared=None):
    """One NaomiLib model: a 4-record strip whose last record references vertex 0."""
    poly = bytearray(struct.pack('<2I', 0x10, 4))
    first = len(poly)
    poly += _vertex(0, 0, 0, 0, 0) + _vertex(1, 0, 0, 1, 0) + _vertex(0, 1, 0, 0, 1)
    ref_at = len(poly)
    poly += struct.pack('<Ii', 0x5ff00000, first - (ref_at + 8))
    header = bytearray(80)
    struct.pack_into('<I', header, 0, 0x80000000 | 0x0a)
    struct.pack_into('<2i', header, 32, texture, -1)
    struct.pack_into('<I', header, 76, len(poly))
    head = struct.pack('<2I4f', 0x15, 0, 0.5, 0.5, 0.0, 0.8)
    end = struct.pack('<2I', 0, 4 if declared is None else declared)
    return head + bytes(header) + bytes(poly) + end


def test_scan_finds_model_without_archive_table():
    junk = bytes(range(100))
    blob = junk + _model() + b'\xff' * 12 + _model(texture=7) + junk
    found = naomilib.scan(blob)
    assert [m['offset'] for m in found] == [100, 100 + len(_model()) + 12]
    first = found[0]
    assert first['vertex_count'] == 4 and first['triangle_count'] == 2
    mesh = first['meshes'][0]
    assert mesh['texture_id'] == 3 and len(mesh['vertices']) == 3
    assert mesh['triangles'] == [(0, 1, 2), (2, 1, 0)]
    assert found[1]['meshes'][0]['texture_id'] == 7


def test_scan_rejects_wrong_vertex_total():
    assert naomilib.scan(b'\0' * 8 + _model(declared=5)) == []


def test_obj_export_and_cli(tmp_path):
    blob = b'\0' * 8 + _model()
    obj = naomilib.to_obj(naomilib.scan(blob))
    assert obj.count('\nf ') == 2 and obj.count('\nv ') == 3
    src = tmp_path / 'X.CHR'
    src.write_bytes(blob)
    assert naomilib.main([str(src), '--obj', str(tmp_path / 'out')]) == 0
    assert (tmp_path / 'out/X.CHR.obj').read_text().count('\nf ') == 2


@pytest.mark.skipif(not GDI.exists(), reason='owned DOA2 LE disc not unpacked on this node')
def test_scan_matches_doa2_chr_model_table():
    from gbox.gdrom import GDRom
    data = GDRom(str(GDI)).read('DOA2/KAS00.CHR')
    assert struct.unpack_from('<I', data)[0] == 24
    table, _, count, _ = struct.unpack_from('<4I', data, 4)
    pointers = struct.unpack_from(f'<{count}I', data, table)
    expected = [p - pointers[0] + 24 for p in pointers]
    found = naomilib.scan(data)
    assert [m['offset'] for m in found] == expected
    assert all(m['triangle_count'] > 0 for m in found)
