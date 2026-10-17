"""Portable MGO routing must not fall through to generic RPCS3 provisioning."""
from contextlib import contextmanager
import hashlib
from pathlib import Path
import subprocess
from types import SimpleNamespace
import zipfile

import pytest

from gbox import adapters, catalog, savemgo
from gbox.config import Config, EmulatorConfig
from gbox.registry import ToolUnavailable, Unsupported


def game():
    return {'game_id': 'mgo', 'title': 'Metal Gear Online', 'platform': 'ps3',
            'launch': {'kind': 'savemgo_bundle', 'source_fingerprint': 'abc'}}


def test_catalog_uses_shared_package_identity_and_never_generic_member(tmp_path, monkeypatch):
    archive = tmp_path / 'SaveMGO.zip'
    archive.write_bytes(b'fixture')
    profile = {'title': 'Metal Gear Online', 'serial': 'NPMG00010', 'archive_size': 7,
               'launch': game()['launch'] | {'eboot': savemgo.EBOOT, 'executable': 'rpcs3.exe'}}
    monkeypatch.setattr(savemgo, 'identify', lambda path: profile)
    monkeypatch.setattr('gbox.rom_archives.members', lambda *_: pytest.fail('generic ZIP reader used'))
    entries, problems = catalog.scan([tmp_path], {}, lib_id='ps3', do_hash=False)
    assert not problems and len(entries) == 1
    row = entries[0]
    assert row.title == 'Metal Gear Online' and row.serial == 'NPMG00010'
    assert row.game_id == hashlib.sha1(b'ps3:SaveMGO.zip').hexdigest()[:16]
    assert row.library == 'ps3' and row.rel_path == 'SaveMGO.zip'
    assert row.launch['path'] == str(archive) and row.launch['kind'] == 'savemgo_bundle'
    assert 'archive_member' not in row.launch and row.core is None
    from gbox.store import Store
    store = Store(tmp_path / 'search')
    store.upsert_catalog([row.model_dump()])
    from gbox.library_home import HomeData
    home = HomeData(SimpleNamespace(), store, Config(data_dir=tmp_path))
    monkeypatch.setattr(home, 'snapshot', lambda: {'stats': {}, 'platforms': [], 'indexing': False, 'media': {}})
    monkeypatch.setattr(home, '_local_art', lambda: {})
    for query in ('metal gear', 'metal gear online', 'mgo', 'MGO'):
        total, found = store.search(query)
        assert total == 1 and found[0]['game_id'] == row.game_id
        result = home.games(q=query)
        assert result['total'] == 1 and result['items'][0]['game_id'] == row.game_id


def test_unrelated_zip_still_scans(tmp_path):
    with zipfile.ZipFile(tmp_path / 'Test.zip', 'w') as archive:
        archive.writestr('Test.nes', b'NES\x1a' + bytes(32))
    rows, problems = catalog.scan([tmp_path], {}, lib_id='nes', do_hash=False)
    assert not problems and len(rows) == 1 and rows[0].platform == 'nes'
    assert rows[0].launch['archive_member'] == 'Test.nes'


def test_invalid_identified_bundle_never_falls_back(tmp_path, monkeypatch):
    (tmp_path / 'SaveMGO.zip').write_bytes(b'fixture')
    def reject(*_):
        raise ValueError('Pinned runner differs')
    monkeypatch.setattr(savemgo, 'identify', reject)
    monkeypatch.setattr('gbox.rom_archives.members', lambda *_: pytest.fail('unsafe fallback'))
    rows, problems = catalog.scan([tmp_path], {}, lib_id='ps3', do_hash=False)
    assert not rows and len(problems) == 1 and 'Pinned runner differs' in problems[0]


def test_bundle_routing_precedes_global_ps3_override(tmp_path, monkeypatch):
    cfg = Config(data_dir=tmp_path, emulators={'ps3': EmulatorConfig(adapter='command', executable='other.exe')})
    monkeypatch.setattr(adapters, 'HOST_OS', 'windows')
    ad = adapters.for_game(game(), cfg)
    assert isinstance(ad, adapters.SaveMGOAdapter)
    caps = ad.get_capabilities()
    assert caps['launch_game'] == 'supported' and caps['query_runtime'] == 'supported'
    assert all(caps[op] == 'unsupported' for op in ('read_memory', 'write_memory', 'save_state', 'load_state', 'rewind'))
    with pytest.raises(Unsupported, match='writer'):
        adapters.for_game(game(), cfg, mod='unknown')
    monkeypatch.setattr(adapters, 'HOST_OS', 'linux')
    with pytest.raises(ToolUnavailable, match='Windows'):
        adapters.for_game(game(), cfg)


def prepared(tmp_path, monkeypatch, *, exit_code=None, fail_start=False):
    home = tmp_path / 'portable'
    home.mkdir()
    bundle = {'home': home, 'executable': home / 'rpcs3.exe', 'eboot': home / savemgo.EBOOT,
              'source_fingerprint': 'abc', 'archive_sha256': 'f' * 64, 'reused': True}
    calls, leases = [], []
    def prepare(path, cfg, progress, **kwargs):
        calls.append(('prepare', Path(path), kwargs))
        return bundle
    @contextmanager
    def lease(path):
        leases.append(('enter', path))
        try:
            yield
        finally:
            leases.append(('exit', path))
    proc = SimpleNamespace(pid=123, returncode=exit_code, poll=lambda: exit_code)
    def wait(timeout):
        if exit_code is None:
            raise subprocess.TimeoutExpired('rpcs3', timeout)
        return exit_code
    proc.wait = wait
    def popen(argv, **kwargs):
        calls.append(('popen', argv, kwargs))
        if fail_start:
            raise OSError('test startup failure')
        return proc
    monkeypatch.setattr(savemgo, 'prepare', prepare)
    monkeypatch.setattr(savemgo, 'runtime_lease', lease)
    monkeypatch.setattr(adapters.subprocess, 'Popen', popen)
    monkeypatch.setattr(adapters, 'hidden_start', lambda: 'startup')
    monkeypatch.setattr(adapters, 'keep_offscreen', lambda pid: calls.append(('park', pid)))
    monkeypatch.setattr(adapters, '_kill_tree', lambda proc: calls.append(('kill', proc)))
    monkeypatch.setattr(adapters.provision, 'ensure_rpcs3', lambda *_: pytest.fail('generic provision used'))
    return bundle, proc, calls, leases


def test_exact_vendor_launch_and_lease_until_exit(tmp_path, monkeypatch):
    bundle, proc, calls, leases = prepared(tmp_path, monkeypatch)
    ad = adapters.SaveMGOAdapter(Config(data_dir=tmp_path), game())
    ad.examine = True  # generic application default must not inject this fork
    assert ad.prepare_bundle(tmp_path / 'SaveMGO.zip') == bundle['eboot']
    result = ad.launch_game(str(bundle['eboot']))
    assert calls[0][2] == {'expected_fingerprint': 'abc'}
    assert calls[1] == ('popen', [str(bundle['executable']), '--no-gui', str(bundle['eboot'])],
                        {'cwd': bundle['home'], 'startupinfo': 'startup'})
    assert result['bundled_runtime']['verified'] and result['examine'] is False
    assert 'immutable_files' not in str(result) and leases == [('enter', bundle['home'])]
    assert ad.query_runtime()['running']
    proc.poll = lambda: 0
    assert not ad.query_runtime()['running']
    assert leases == [('enter', bundle['home']), ('exit', bundle['home'])]
    ad.stop_game()
    assert len(leases) == 2


@pytest.mark.parametrize('failure', ['early_exit', 'popen'])
def test_startup_failure_releases_only_owned_lease(tmp_path, monkeypatch, failure):
    bundle, proc, calls, leases = prepared(tmp_path, monkeypatch,
        exit_code=3 if failure == 'early_exit' else None, fail_start=failure == 'popen')
    ad = adapters.SaveMGOAdapter(Config(data_dir=tmp_path), game())
    ad.prepare_bundle(tmp_path / 'SaveMGO.zip')
    with pytest.raises((OSError, RuntimeError)):
        ad.launch_game(str(bundle['eboot']))
    assert leases == [('enter', bundle['home']), ('exit', bundle['home'])]
    assert ad._lease is None


def test_no_unprepared_eboot_or_capture_injection(tmp_path, monkeypatch):
    bundle, proc, calls, leases = prepared(tmp_path, monkeypatch)
    ad = adapters.SaveMGOAdapter(Config(data_dir=tmp_path), game())
    with pytest.raises(ValueError, match='complete verified'):
        ad.launch_game('unverified/EBOOT.BIN')
    ad.prepare_bundle(tmp_path / 'SaveMGO.zip')
    ad.capture_backend = {'driver': 'vulkan'}
    with pytest.raises(Unsupported, match='RenderDoc'):
        ad.launch_game(str(bundle['eboot']))
    assert not leases and len(calls) == 1


def test_cancelled_launch_cleans_unregistered_owned_process(tmp_path, monkeypatch):
    from gbox import tools
    bundle, proc, calls, leases = prepared(tmp_path, monkeypatch)
    ad = adapters.SaveMGOAdapter(Config(data_dir=tmp_path), game())
    def launching(inp, ctx):
        tools._LAUNCH_DIAG.d['_adapter'] = ad
        ad.prepare_bundle(tmp_path / 'SaveMGO.zip')
        ad.launch_game(str(bundle['eboot']))
        raise RuntimeError('progress cancelled after spawn')
    monkeypatch.setattr(tools, '_launch_game', launching)
    monkeypatch.setattr(tools, '_launch_failure_evidence', lambda *_: None)
    def kill(owned):
        assert owned is proc
        proc.poll = lambda: 0
    monkeypatch.setattr(adapters, '_kill_tree', kill)
    with pytest.raises(RuntimeError, match='cancelled'):
        tools.launch_game(SimpleNamespace(), SimpleNamespace())
    assert leases == [('enter', bundle['home']), ('exit', bundle['home'])]


def test_cold_preparation_failure_keeps_previous_game_running(tmp_path, monkeypatch):
    from gbox import tools
    from gbox.models import CatalogEntry
    from gbox.registry import Ctx
    archive = tmp_path / 'SaveMGO.zip'
    archive.write_bytes(b'fixture')
    cfg = Config(data_dir=tmp_path / 'data')
    row = CatalogEntry(**(game() | {'source_paths': [str(archive)], 'format': 'savemgo_bundle',
        'profile_id': 'mgo', 'launch': game()['launch'] | {'path': str(archive)}}))
    ad = adapters.SaveMGOAdapter(cfg, row.model_dump())
    monkeypatch.setattr(adapters, 'for_game', lambda *_args, **_kw: ad)
    def unavailable(_path):
        raise RuntimeError('package not ready')
    monkeypatch.setattr(ad, 'prepare_bundle', unavailable)
    monkeypatch.setattr(tools, '_close_previous_games', lambda *_args, **_kw: pytest.fail('previous game closed before staging'))
    with pytest.raises(RuntimeError, match='package not ready'):
        tools.launch_game(tools.LaunchIn(game=row), Ctx(cfg))
