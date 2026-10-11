"""Native container semantics, input boundaries, and full decomposition export."""
import json
import struct

import pytest

from gbox import doa2_chars as C, doa2_geometry as G, uap


def native_chr():
    header = bytearray(80)
    struct.pack_into('<4I', header, 0, 0x8000002c, 0x83000000, 0x20282452, 0x08000000)
    struct.pack_into('<ii', header, 32, 0, 1)
    mesh = {'header': bytes(header), 'vertices': [
        (0, 0, 0, 0, 0, 1, 0, 0), (1, 0, 0, 0, 0, 1, 1, 0), (0, 1, 0, 0, 0, 1, 0, 1)],
        'triangles': [(0, 1, 2)]}
    model = G.encode_model({'global_flags': (1, 1)}, [mesh])
    data = bytearray(24) + model + bytes(8)
    models = len(data)
    data += struct.pack('<I', 0x0c300000)
    textures = len(data)
    data += struct.pack('<3I', 8 | (8 << 16), 0x101, 0x0d200000) + bytes(4)
    struct.pack_into('<6I', data, 0, 24, models, textures, 1, 1, 0)
    return bytes(data)


def native_sup():
    return struct.pack('<3I', 12, 20, 0) + struct.pack('<4f', 0, 1, 2, 3)


def test_chr_reports_real_models_and_textures():
    r = C.parse_chr(native_chr())
    assert r['n_models'] == r['n_objects'] == 1
    assert r['n_textures'] == 1 and r['objects'] == [24]
    assert r['textures'] == [{'width': 8, 'height': 8, 'pixel': 1, 'format': 1, 'address': 0x0d200000}]
    assert 'n_bones' not in r and 'tail' not in r


@pytest.mark.parametrize('offset,value', [(0, 32), (4, 0xfffffffc), (8, 4), (12, 0x9999)])
def test_chr_rejects_bad_boundaries(offset, value):
    b = bytearray(native_chr())
    struct.pack_into('<I', b, offset, value)
    with pytest.raises(ValueError):
        C.parse_chr(bytes(b))


def test_sup_validates_record_boundaries_without_inventing_bones():
    assert C.parse_sup(native_sup()) == {'n_records': 2, 'offsets': [12, 20],
                                        'records': [{'offset': 12, 'size': 8}, {'offset': 20, 'size': 8}]}
    for bad in [b'', struct.pack('<I', 44), struct.pack('<3I', 12, 4, 0) + bytes(16)]:
        with pytest.raises(ValueError):
            C.parse_sup(bad)


def test_motion_pointer_table_allows_shared_tracks():
    b = struct.pack('<4I', 16, 24, 16, 0) + bytes(24)
    assert C.parse_mot_table(b) == {'n_clips': 3, 'offsets': [16, 24, 16]}


def test_roster_uses_disc_costumes_and_excludes_stage():
    files = {f'DOA2/{name}': (0, 0) for name in ['KAS00.CHR', 'KAS09.CHR', 'AYA00.CHR', 'STAGE01.CHR']}
    assert next(e for e in C.roster(files) if e['key'] == 'KAS')['costumes'] == ['00', '09']
    assert not any(e['key'] == 'STAGE' for e in C.roster(files))


def test_export_has_real_geometry_textures_native_bytes_and_no_false_rig(monkeypatch, tmp_path):
    from gbox import gdrom
    assets = {'DOA2/KAS00.CHR': native_chr(), 'DOA2/KAS00.BIN': b'\xff' * 128,
              'DOA2/KAS00.SUP': native_sup()}
    class Disc:
        files = assets
        def __init__(self, _): pass
        def read(self, name): return assets[name]
    monkeypatch.setattr(gdrom, 'GDRom', Disc)
    r = C.export('fixture.gdi', str(tmp_path), 'KAS')
    m = uap.load(tmp_path)
    assert len(m.meshes) == 1 and len(m.meshes[0].indices) == 3
    assert len(m.materials) == 1 and m.confidence['textures'] == 'verified'
    assert m.skeleton == [] and m.confidence['skeleton'] == 'missing'
    assert uap.validate(m, tmp_path) == []
    assert (tmp_path/'KAS00.CHR').read_bytes() == assets['DOA2/KAS00.CHR']
    assert (tmp_path/'textures/tex000.png').read_bytes().startswith(b'\x89PNG')
    assert (tmp_path/'KAS00_parts.glb').read_bytes()[:4] == b'glTF'
    assert r['manifest']['container_facts']['n_textures'] == 1
    assert all(p['sha256'] for p in json.loads((tmp_path/'manifest.json').read_text())['provenance'])


@pytest.mark.parametrize('key,costume', [('STAGE', '00'), ('KAS', '../'), ('KAS', '100')])
def test_invalid_export_identity_rejected_before_disc_access(key, costume, tmp_path):
    with pytest.raises(ValueError):
        C.export('does-not-exist', str(tmp_path), key, costume)
