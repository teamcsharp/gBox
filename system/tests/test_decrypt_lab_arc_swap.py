"""Entry swaps address duplicate resource names and compose in a tracked overlay."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException

from gbox import decrypt_lab as L, mt_arc, switch_mods as S
from gbox.config import Config

TID, GID = '010018100CD46000', '52d15709be0fda1a'
PREFIX = 'nativeNXx64/ImgNX/Archive/'
NAME = r'pawn\em\em10\model\em1000'


def archive(material, model):
    return mt_arc.build(mt_arc.Arc(7, [
        mt_arc.Entry(NAME, 1, 0x40000000 | len(data), len(data), 0, data)
        for data in (material, model)]))


@pytest.fixture
def panel(tmp_path, monkeypatch):
    cfg = Config(data_dir=tmp_path / 'data', cache_dir=tmp_path / 'cache')
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    monkeypatch.setattr(S, 'running_users', lambda *a: [])
    root = tmp_path / 'gBox_alt' / 'switch' / 'romfs' / TID
    (root / PREFIX).mkdir(parents=True)
    (root / PREFIX / 'target.arc').write_bytes(archive(b'MRL base', b'MOD base'))
    (root / PREFIX / 'donor.arc').write_bytes(archive(b'MRL donor', b'MOD replacement'))
    rows = [(GID, json.dumps({'serial': TID}))]
    store = SimpleNamespace(db=SimpleNamespace(execute=lambda *a: SimpleNamespace(fetchall=lambda: rows)))
    app = FastAPI()
    L.install(app, store, cfg, lambda: None)
    endpoint = next(r.endpoint for r in app.routes if r.path == '/api/decrypt-lab/arc-swap')
    return cfg, root, endpoint


def request(**updates):
    return L.ArcSwapIn(title='re5_switch', build='entry-test', arc_path=PREFIX + 'target.arc',
                       donor_arc=PREFIX + 'donor.arc', entry=NAME, donor_entry=NAME, **updates)


@pytest.mark.parametrize('indices, label', [({}, 'target'), ({'entry_index': 1}, 'donor')])
def test_duplicate_name_requires_index_without_writing(panel, indices, label):
    cfg, _, endpoint = panel
    with pytest.raises(HTTPException, match=label + ' entry name is ambiguous') as error:
        endpoint(request(**indices))
    assert error.value.status_code == 409
    assert not S.build_dir(cfg, GID, 'entry-test').exists()


def test_explicit_mod_index_preserves_material_and_updates_length(panel):
    cfg, root, endpoint = panel
    result = endpoint(request(entry_index=1, donor_index=1))
    folder = S.build_dir(cfg, GID, 'entry-test')
    entries = mt_arc.parse((folder / 'romfs' / PREFIX / 'target.arc').read_bytes()).entries
    assert [e.data for e in entries] == [b'MRL base', b'MOD replacement']
    assert entries[1].tag == 0x40000000 | len(b'MOD replacement')
    assert result['entry_index'] == result['donor_index'] == 1
    assert not result['pending'] and S.read_meta(folder)['history'][-1]['id'] == result['edit']
    assert mt_arc.parse((root / PREFIX / 'target.arc').read_bytes()).entries[1].data == b'MOD base'
    S.revert(cfg, GID, 'entry-test', result['edit'])
    assert not (folder / 'romfs' / PREFIX / 'target.arc').exists()


def test_sequential_live_edits_compose_without_changing_running_archive(panel, monkeypatch):
    cfg, _, endpoint = panel
    rel = 'romfs/' + PREFIX + 'target.arc'
    initial = archive(b'MRL old build', b'MOD old build')
    S.write_files(cfg, GID, 'entry-test', {rel: {'bytes': initial}}, create={'title_id': TID})
    folder = S.build_dir(cfg, GID, 'entry-test')
    monkeypatch.setattr(S, 'running_users', lambda *a: ['active-session'])
    first = endpoint(request(entry_index=1, donor_index=1))
    second = endpoint(request(entry_index=0, donor_index=0))
    assert first['pending'] and second['pending']
    assert (folder / rel).read_bytes() == initial
    S.apply_pending(folder)
    assert [e.data for e in mt_arc.parse((folder / rel).read_bytes()).entries] == [b'MRL donor', b'MOD replacement']
    S.revert(cfg, GID, 'entry-test', second['edit'])
    assert [e.data for e in mt_arc.parse((folder / rel).read_bytes()).entries] == [b'MRL old build', b'MOD replacement']


@pytest.mark.parametrize('index', [-1, 2])
def test_out_of_range_index_is_refused(panel, index):
    cfg, _, endpoint = panel
    with pytest.raises(HTTPException, match='index does not match'):
        endpoint(request(entry_index=index, donor_index=1))
    assert not S.build_dir(cfg, GID, 'entry-test').exists()


def test_entry_name_must_match_index(panel):
    cfg, _, endpoint = panel
    with pytest.raises(HTTPException, match='index does not match'):
        endpoint(request(entry_index=1, donor_index=1).model_copy(update={'entry': 'other'}))
    assert not S.build_dir(cfg, GID, 'entry-test').exists()


def test_matching_hash_does_not_allow_material_to_replace_geometry(panel):
    import zlib
    cfg, root, endpoint = panel
    for file in ('target.arc', 'donor.arc'):
        (root / PREFIX / file).write_bytes(archive(zlib.compress(b'MRL\0material'), zlib.compress(b'MOD\0model')))
    with pytest.raises(HTTPException, match='resource kinds differ'):
        endpoint(request(entry_index=1, donor_index=0))
    assert not S.build_dir(cfg, GID, 'entry-test').exists()


@pytest.mark.parametrize('path', ['../outside.arc', '/absolute.arc', 'C:/outside.arc'])
def test_archive_path_must_stay_in_romfs(panel, path):
    cfg, _, endpoint = panel
    with pytest.raises(HTTPException):
        endpoint(request(entry_index=1, donor_index=1).model_copy(update={'arc_path': path}))
    assert not S.build_dir(cfg, GID, 'entry-test').exists()
