import io
import json
import os
import struct
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PIL import Image
import pytest

from gbox import re2gc_models as M, characters as C, char_coverage as CC
from gbox.re2gc_native import Model
from test_re2gc_native import fixture


def model():
    data = bytearray(fixture()); m = Model(data)
    # Known PS1 palette: index 1 = red; index 2 = opaque black.
    struct.pack_into('<2H', data, m.offsets[3] + 22, 31, 0x8000)
    return Model(data)


def parse_glb(path):
    raw = path.read_bytes()
    assert struct.unpack_from('<3I', raw) == (0x46546c67, 2, len(raw))
    size, kind = struct.unpack_from('<2I', raw, 12)
    assert kind == 0x4e4f534a
    gl = json.loads(raw[20:20 + size])
    bsize, kind = struct.unpack_from('<2I', raw, 20 + size)
    assert kind == 0x004e4942 and 28 + size + bsize == len(raw)
    blob = raw[28 + size:]
    for view in gl['bufferViews']:
        assert view['byteOffset'] % 4 == 0
        assert view['byteOffset'] + view['byteLength'] <= len(blob)
    return gl, blob


def test_palette_selection_and_zero_alpha_are_exact():
    image = M.palette_image(model(), 0)
    assert image.shape == (1, 4, 4)
    assert image[0].tolist() == [[0, 0, 0, 255], [255, 0, 0, 255], [0, 0, 0, 0], [0, 0, 0, 0]]
    with pytest.raises(ValueError, match='CLUT'):
        M.palette_image(model(), 64)


def test_bind_world_and_independent_glb_structure(tmp_path):
    m = model(); out = tmp_path / 'model.glb'
    rep = M.export_glb(m, out)
    gl, blob = parse_glb(out)
    assert rep['triangles'] == 1 and rep['bones'] == 1 and not rep['roles']
    assert gl['extras']['native_source_sha256'] == M.sha(m.data)
    assert gl['skins'][0]['joints'] == [2]
    assert not gl['materials'][0]['doubleSided']
    img = gl['bufferViews'][gl['images'][0]['bufferView']]
    assert np.array(Image.open(io.BytesIO(blob[img['byteOffset']:img['byteOffset'] + img['byteLength']]))).tolist() == M.palette_image(m, 0).tolist()
    with pytest.raises(FileExistsError):
        M.export_glb(m, out)


def test_extra_mesh_parts_are_not_silently_omitted(tmp_path):
    m = model(); m.objects = m.objects * 2
    with pytest.raises(ValueError, match='extra-part attachments'):
        M.export_glb(m, tmp_path / 'bad.glb')
    assert not (tmp_path / 'bad.glb').exists()


def test_bad_texture_depth_or_uv_is_not_wrapped(tmp_path):
    for offset, value in ((6, 128), (0, 99)):
        m = model(); raw = bytearray(m.objects[0][0]['uv_bytes']); raw[offset] = value
        m.objects[0][0]['uv_bytes'] = bytes(raw)
        with pytest.raises(ValueError):
            M.export_glb(m, tmp_path / 'bad.glb')


def test_md1_quad_uses_native_013_and_023_diagonal():
    m = model()
    m.objects[0][0]['indices'] = []; m.objects[0][0]['uv_bytes'] = b''
    quad = m.objects[0][1]
    quad['vertices'] = [(0, 0, 0, 0), (10, 0, 0, 0), (0, 10, 0, 0), (10, 10, 0, 0)]
    quad['indices'] = [(0, 0, 0, 1, 0, 2, 0, 3)]; quad['uv_bytes'] = bytes(16)
    _parents, _world, groups = M.geometry(m, scale=1)
    positions = np.asarray(groups[0]['pos'])
    native = np.asarray([v[:3] for v in quad['vertices']]) @ M.C.T
    ids = [int(np.flatnonzero(np.all(native == point, axis=1))[0]) for point in positions]
    assert set(ids[:3]) == {0, 1, 3} and set(ids[3:]) == {0, 2, 3}


def test_roster_keeps_all_variants_and_exact_port_guard(tmp_path, monkeypatch):
    rows = M.roster()
    assert len(rows) == len({r['key'] for r in rows}) == len({r['slug'] for r in rows}) == 40
    assert {'Pl0/PLD/PL01.PLD', 'Pl1/PLD/PL0F.PLD'} <= {r['key'] for r in rows}
    good = {'game_id': M.GAME_ID, 'title': 'Resident Evil 2 (USA)', 'platform': 'gamecube'}
    assert CC.extractor_for(good)[0] == 're2gc'
    assert CC.extractor_for(good | {'game_id': 'f' * 16})[0] is None
    assert CC.extractor_for(good | {'platform': 'n64'})[0] != 're2gc'
    monkeypatch.setattr(C, '_rom', lambda *a: pytest.fail('wrong identity must fail before source access'))
    with pytest.raises(ValueError, match='exact'):
        M.extract_run(SimpleNamespace(), good | {'game_id': 'f' * 16}, rows[0], tmp_path)
    with pytest.raises(ValueError, match='unknown RE2'):
        M.extract_run(SimpleNamespace(), good, rows[0] | {'key': '../outside'}, tmp_path)


def test_owned_export_all_supported_models_without_hiding_missing_parts(tmp_path):
    path = os.environ.get('GBOX_RE2GC_SOURCE')
    if not path:
        pytest.skip('set GBOX_RE2GC_SOURCE to owned GHAE08 image')
    from gbox.gcdisc import GCDisc
    disc = GCDisc(path)
    success, pending = [], []
    try:
        for row in M.roster():
            m = Model(disc.read(row['key']))
            out = tmp_path / (row['slug'] + '.glb')
            if len(m.objects) != m.skeleton['bones']:
                with pytest.raises(ValueError, match='extra-part attachments'):
                    M.export_glb(m, out)
                pending.append(row['key']); continue
            rep = M.export_glb(m, out)
            gl, blob = parse_glb(out)
            assert rep['triangles'] == m.summary()['triangles'] + 2 * m.summary()['quads']
            assert rep['bones'] == 15
            assert len(gl['skins'][0]['joints']) == 15
            assert m.data == disc.read(row['key'])
            success.append(row['key'])
        assert len(success) == 23 and len(pending) == 17
    finally:
        disc.f.close()


def test_owned_normal_collection_route_preserves_provenance(tmp_path, monkeypatch):
    path = os.environ.get('GBOX_RE2GC_SOURCE')
    if not path:
        pytest.skip('set GBOX_RE2GC_SOURCE to owned GHAE08 image')
    from gbox.config import Config
    root = tmp_path / 'characters'; root.mkdir()
    cfg = Config(cache=str(tmp_path / 'cache'))
    ctx = SimpleNamespace(config=cfg, progress=lambda *a: None)
    game = {'game_id': M.GAME_ID, 'title': 'Resident Evil 2 (USA)', 'platform': 'gamecube'}
    monkeypatch.setattr(C, '_rom', lambda *a: Path(path))
    result = C.extract_dedicated(ctx, game, 'RE2 GC Pl0 PL00', root)
    assert result['status'] == 'extracted' and result['extractor'] == 're2gc'
    entry = result['entry']
    assert entry['source']['game_id'] == M.GAME_ID
    assert entry['re2gc_reader'] == M.READER_VERSION
    assert entry['native_evidence']['source_sha256'] == '02ccf44b0a3b1123e004db054e1bf47f1817d4d41184b1d00516715545f5996a'
    assert C.verify_entry(root, entry)['ok']
    assert entry['rig']['roles']['head'] == 'j08'
