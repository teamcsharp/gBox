import io
import json
from pathlib import Path
import zipfile

import pytest

from gbox import savemgo, tools
from gbox.config import Config
from gbox.models import CatalogEntry
from gbox.registry import Ctx, Unsupported, ToolUnavailable
from gbox.store import sha256


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    cfg = Config(data_dir=tmp_path / 'data')
    root = tmp_path / 'home' / 'dev_hdd0/game/NPMG00020/USRDIR'
    (root / 'dbm').mkdir(parents=True)
    (root / 'dbm/test.dbm').write_bytes(b'native music fixture')
    (root.parent.parent.parent / 'home').mkdir()
    (root.parent.parent.parent / 'home/private-save.bin').write_bytes(b'personal save must never appear')
    profile = {'data_root': root, 'source_fingerprint': 'f' * 64}
    monkeypatch.setattr(savemgo, 'prepare', lambda *args, **kwargs: profile)
    monkeypatch.setattr(tools, 'HOST_OS', 'windows')
    game = CatalogEntry(game_id='test-game', title='Metal Gear Online', platform='ps3',
        source_paths=['SaveMGO.zip'], format='savemgo_bundle', profile_id='test-game',
        launch={'kind':'savemgo_bundle','path':'SaveMGO.zip','source_fingerprint':'f'*64})
    return cfg, root, game


def test_inventory_report_is_validated_without_personal_data(prepared):
    cfg, root, game = prepared
    ctx = Ctx(cfg)
    result = tools.savemgo_assets(tools.SaveMGOAssetsIn(game=game), ctx)
    assert result['result']['summary']['files'] == 1
    assert result['result']['source_verified'] is True
    assert result['result']['readiness']['decoded_models'] is False
    artifacts = {name:data for name,data,_,_ in ctx.artifacts}
    assert tools._savemgo_assets_validate(tools.SaveMGOAssetsOut(**result), artifacts) == []
    assert 'personal save' not in str(artifacts) and 'private-save' not in str(artifacts)


def test_selected_native_export_has_hashed_download_only(prepared):
    cfg, root, game = prepared
    ctx = Ctx(cfg)
    result = tools.savemgo_assets(tools.SaveMGOAssetsIn(game=game,op='export',paths=['dbm/test.dbm']),ctx)
    artifacts = {name:data for name,data,_,_ in ctx.artifacts}
    assert result['result']['download'] == 'savemgo-native-assets.zip'
    with zipfile.ZipFile(io.BytesIO(artifacts['savemgo-native-assets.zip'])) as archive:
        assert set(archive.namelist()) == {'native/dbm/test.dbm','manifest.json'}
        native = archive.read('native/dbm/test.dbm')
        manifest = json.loads(archive.read('manifest.json'))
    assert sha256(native) == manifest['files'][0]['sha256']
    assert manifest['native_only'] is True and manifest['source_fingerprint'] == 'f'*64
    assert result['result']['files'][0]['readiness']['cross_game_ready'] is False


def test_unsupported_host_and_empty_export_fail_before_preparation(prepared, monkeypatch):
    cfg, root, game = prepared
    monkeypatch.setattr(savemgo, 'prepare', lambda *_args, **_kw: pytest.fail('must not stage'))
    with pytest.raises(ValueError, match='Select files'):
        tools.savemgo_assets(tools.SaveMGOAssetsIn(game=game,op='export'),Ctx(cfg))
    monkeypatch.setattr(tools, 'HOST_OS', 'linux')
    with pytest.raises(ToolUnavailable, match='Windows'):
        tools.savemgo_assets(tools.SaveMGOAssetsIn(game=game),Ctx(cfg))
    game.launch['kind'] = 'emulator'
    with pytest.raises(Unsupported, match='verified SaveMGO'):
        tools.savemgo_assets(tools.SaveMGOAssetsIn(game=game),Ctx(cfg))


def test_full_resource_export_streams_through_tool_without_personal_data(prepared):
    cfg, root, game = prepared
    ctx = Ctx(cfg)
    result = tools.savemgo_assets(tools.SaveMGOAssetsIn(game=game,op='export',paths=['*']),ctx)
    assert result['result']['state'] == 'exported'
    assert {r['source_path'] for r in result['result']['files']} == {'dbm/test.dbm'}
    assert (root / 'dbm/test.dbm').read_bytes() == b'native music fixture'
    assert all(b'personal save' not in content for _,content,_,_ in ctx.artifacts)
