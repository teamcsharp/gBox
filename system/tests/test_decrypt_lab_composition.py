"""Edits of a replacement build preserve its mesh and compose across pending restarts."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException

from gbox import decrypt_lab as L, mt_arc, switch_mods as S
from gbox.config import Config

TID = '010018100CD46000'
GID = '52d15709be0fda1a'
PREFIX = 'nativeNXx64/ImgNX/Archive/'
CHRIS, JILL, SHEVA = (PREFIX + name for name in (
    'uPl00ChrisNormal.arc', 'uPl02JillCos1.arc', 'uPl01ShebaNormal.arc'))


def archive(character):
    prefix = f'pawn\\pl\\{character}\\model\\'
    values = [('body_MOD', character.encode() + b'_mesh'),
              ('evf0000_01_BM', character.encode() + b'_skin'),
              ('evf0000_02_BM', character.encode() + b'_coat')]
    return mt_arc.build(mt_arc.Arc(7, [mt_arc.Entry(prefix + name, 1, 23, len(data), 0, data)
                                     for name, data in values]))


def contents(data):
    return {entry.name.rsplit('\\', 1)[-1]: entry.data for entry in mt_arc.parse(data).entries}


@pytest.fixture
def panel(tmp_path, monkeypatch):
    cfg = Config(data_dir=tmp_path / 'data', cache_dir=tmp_path / 'cache')
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    monkeypatch.setattr(S, 'running_users', lambda *a: [])
    root = tmp_path / 'gBox_alt' / 'switch' / 'romfs' / TID
    (root / PREFIX).mkdir(parents=True)
    for path, character in ((CHRIS, 'chris'), (JILL, 'jill'), (SHEVA, 'sheva'),
                            (PREFIX + 'uEm10.arc', 'majini')):
        (root / path).write_bytes(archive(character))
    rows = [(GID, json.dumps({'serial': TID}))]
    store = SimpleNamespace(db=SimpleNamespace(execute=lambda *a: SimpleNamespace(fetchall=lambda: rows)))
    app = FastAPI()
    L.install(app, store, cfg, lambda: None)
    return cfg, root, {r.path: r.endpoint for r in app.routes}


def native(routes, build='composition-test'):
    return routes['/api/decrypt-lab/character-swap'](L.CharacterSwapIn(
        title='re5_switch', build=build, arc_path=CHRIS, donor_arc=JILL))


def skin(routes, build='composition-test'):
    return routes['/api/decrypt-lab/model-swap'](L.ModelSwapIn(
        title='re5_switch', build=build, arc_path=CHRIS, donor_arc=SHEVA))


@pytest.mark.parametrize('running', [False, True])
def test_native_skin_and_clothes_edits_preserve_replacement_geometry(panel, monkeypatch, running):
    cfg, root, routes = panel
    folder = S.build_dir(cfg, GID, 'composition-test')
    # A modified donor in the same build must not make the donor dropdown depend on previous edits.
    S.write_files(cfg, GID, 'composition-test', {SHEVA: {'bytes': archive('edited-donor')}}, create={'title_id': TID})
    monkeypatch.setattr(S, 'running_users', lambda *a: ['live-session'] if running else [])
    assert native(routes)['pending'] is running
    assert skin(routes)['pending'] is running
    stripped = routes['/api/decrypt-lab/strip-clothes'](L.StripClothesIn(
        title='re5_switch', build='composition-test', arc_path=CHRIS))
    assert stripped['pending'] is running
    target = folder / 'romfs' / CHRIS
    if running:
        assert not target.exists() and len(S.pending_edits(folder)) == 3
        S.apply_pending(folder)
    result = contents(target.read_bytes())
    assert result == {'body_MOD': b'jill_mesh', 'evf0000_01_BM': b'sheva_skin', 'evf0000_02_BM': b'sheva_skin'}
    S.revert(cfg, GID, 'composition-test', stripped['edit'])
    assert contents(target.read_bytes())['evf0000_02_BM'] == b'jill_coat'
    assert contents(target.read_bytes())['body_MOD'] == b'jill_mesh'
    assert contents((root / CHRIS).read_bytes())['body_MOD'] == b'chris_mesh'


def test_composition_uses_only_the_named_build(panel):
    cfg, _, routes = panel
    native(routes, 'other-build')
    skin(routes, 'fresh-build')
    target = S.build_dir(cfg, GID, 'fresh-build') / 'romfs' / CHRIS
    assert contents(target.read_bytes())['body_MOD'] == b'chris_mesh'
    assert contents(target.read_bytes())['evf0000_01_BM'] == b'sheva_skin'


def test_pending_removal_restores_base_before_the_next_edit(panel, monkeypatch):
    cfg, _, routes = panel
    native(routes)
    S.write_files(cfg, GID, 'composition-test', {CHRIS: {'remove': True}}, in_use=True)
    monkeypatch.setattr(S, 'running_users', lambda *a: ['live-session'])
    skin(routes)
    folder = S.build_dir(cfg, GID, 'composition-test')
    S.apply_pending(folder)
    assert contents((folder / 'romfs' / CHRIS).read_bytes())['body_MOD'] == b'chris_mesh'


def test_missing_pending_payload_is_refused_without_overwriting_the_prior_build(panel, monkeypatch):
    cfg, _, routes = panel
    monkeypatch.setattr(S, 'running_users', lambda *a: ['live-session'])
    edit = native(routes)
    folder = S.build_dir(cfg, GID, 'composition-test')
    (folder / S.PENDING / edit['edit'] / 'files' / 'romfs' / CHRIS).unlink()
    with pytest.raises(HTTPException, match='incomplete'):
        skin(routes)
    assert len(S.pending_edits(folder)) == 1
    assert not (folder / 'romfs' / CHRIS).exists()


def test_enemy_cast_changes_use_the_latest_pending_enemy_mesh(panel, monkeypatch):
    from gbox import model_swap
    cfg, _, routes = panel
    target = PREFIX + 'uEm10.arc'
    replacement = archive('replacement')
    S.write_files(cfg, GID, 'enemy-test', {target: {'bytes': replacement}}, in_use=True, create={'title_id': TID})
    monkeypatch.setattr(S, 'running_users', lambda *a: ['live-session'])
    seen = []
    def swap(slot, donor, **kwargs):
        seen.append((slot, donor))
        return {'data': slot, 'meshes': [], 'textures': []}
    monkeypatch.setattr(model_swap, 'swap_models', swap)
    result = routes['/api/decrypt-lab/zombie-cast'](L.ZombieCastIn(
        title='re5_switch', build='enemy-test', donors=['chris'], max_growth=0))
    assert result['pending'] and result['swapped'] == 1
    assert seen == [(replacement, archive('chris'))]
