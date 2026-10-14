from pathlib import Path
from types import SimpleNamespace

from gbox import ff7_swap as S, characters, pe_swap


def test_rebuild_preserves_old_builds_and_their_previews(tmp_path, monkeypatch):
    cfg = SimpleNamespace(cache=tmp_path/'cache')
    root = tmp_path/'characters'
    meta = {'slug': 'mario', 'name': 'Mario', 'model': 'mario.gltf', 'rig': {'roles': {'hip': 'hip'}}}
    game = {'game_id': '6703ee6f461a2ea5'}
    old = cfg.cache/'mods'/game['game_id']/'ff7_mario'
    old.mkdir(parents=True)
    (old/'original.bin').write_bytes(b'legacy game')
    preview = root/'mario/targets/ff7_preview.png'
    preview.parent.mkdir(parents=True)
    preview.write_bytes(b'legacy preview')
    monkeypatch.setattr(pe_swap, 'base_bin', lambda *args: tmp_path/'base.bin')
    monkeypatch.setattr(characters, '_blender', lambda *args: None)
    monkeypatch.setattr(characters, 'render_preview', lambda src, dst: Path(dst))

    def fake_build(disc, model, roles, work, name, out_bin, base, **kwargs):
        out_bin.write_bytes(b'new game')
        cue = out_bin.with_suffix('.cue')
        cue.write_text('new cue')
        rig = work/'field.gltf'
        rig.write_text('{}')
        return {'bin': str(out_bin), 'cue': str(cue), 'rigged_field': str(rig),
                'field': {'triangles': 10}, 'battle': {'triangles': 20}}

    monkeypatch.setattr(S, 'build', fake_build)
    first = S.build_mod(cfg, meta, game, root=root)
    first_dir = cfg.cache/'mods'/game['game_id']/first['mod']
    before = {p.name: p.read_bytes() for p in first_dir.iterdir()}
    second = S.build_mod(cfg, meta, game, root=root)
    assert first['mod'] == 'ff7_mario_v2'
    assert second['mod'].startswith(first['mod']+'_')
    assert second['mod'] != first['mod']
    assert {p.name: p.read_bytes() for p in first_dir.iterdir()} == before
    assert (old/'original.bin').read_bytes() == b'legacy game'
    assert preview.read_bytes() == b'legacy preview'
    assert (root/'mario/targets'/game['game_id']/first['mod']/'ff7_cloud_field.gltf').is_file()
    assert (root/'mario/targets'/game['game_id']/second['mod']/'ff7_cloud_field.gltf').is_file()
    # Disc 2 uses the same donor/version name but must not collide with Disc 1's
    # preview or an in-progress work directory.
    pending = cfg.cache/'characters_build'/game['game_id']/first['mod']
    pending.mkdir(parents=True)
    (pending/'keep.txt').write_text('other disc build')
    game2 = {'game_id': '52d73a58e6b29209'}
    other_disc = S.build_mod(cfg, meta, game2, root=root)
    assert other_disc['mod'] == first['mod']
    assert (root/'mario/targets'/game2['game_id']/other_disc['mod']/'ff7_cloud_field.gltf').is_file()
    assert (pending/'keep.txt').read_text() == 'other disc build'


def test_use_records_and_returns_the_new_rebuild_name(tmp_path, monkeypatch):
    from gbox import sm64_swap
    meta = {'slug': 'mario', 'name': 'Mario'}
    game = {'game_id': '6703ee6f461a2ea5'}
    ctx = SimpleNamespace(config=SimpleNamespace(cache=tmp_path), progress=lambda *args: None)
    inp = SimpleNamespace(session_id=None, rebuild=True, launch=False)
    recorded = []
    monkeypatch.setattr(characters, 'library_root', lambda cfg: tmp_path)
    monkeypatch.setattr(sm64_swap, '_have_mod', lambda *args: True)
    monkeypatch.setattr(characters, '_api', lambda *args, **kwargs: recorded.append(kwargs.get('json')))
    monkeypatch.setattr(S, 'build_mod', lambda *args: {'mod': 'ff7_mario_v2_new',
                        'report': {'field': {'triangles': 359}, 'battle': {'triangles': 752}}})
    result = S.use(ctx, meta, game, inp)
    assert result['mod'] == recorded[0]['mod'] == 'ff7_mario_v2_new'


def test_remote_use_returns_the_remote_immutable_name(tmp_path, monkeypatch):
    from gbox import sm64_swap
    meta = {'slug': 'mario', 'name': 'Mario'}
    ctx = SimpleNamespace(config=SimpleNamespace(cache=tmp_path), progress=lambda *args: None)
    inp = SimpleNamespace(session_id=None, rebuild=True, launch=False)
    monkeypatch.setattr(characters, 'library_root', lambda cfg: tmp_path/'missing')
    monkeypatch.setattr(characters, '_api', lambda *args, **kwargs: [{'id': 'test-linux', 'os': 'linux'}])
    monkeypatch.setattr(sm64_swap, '_have_mod', lambda *args: True)
    monkeypatch.setattr(characters, '_job', lambda *args, **kwargs: {'state': 'succeeded',
                        'output': {'result': {'status': 'built', 'mod': 'ff7_mario_v2_remote', 'build': {}}}})
    assert S.use(ctx, meta, {'game_id': '6703ee6f461a2ea5'}, inp)['mod'] == 'ff7_mario_v2_remote'
