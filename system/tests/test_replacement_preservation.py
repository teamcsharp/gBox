import hashlib
import time
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from gbox import tools, filemods
from gbox.config import Config
from gbox.server import create_app


def enclosed(fn, name):
    return dict(zip(fn.__code__.co_freevars, fn.__closure__))[name]


@pytest.mark.parametrize('failed_stage', ['prepare_mod', 'state_transfer'])
def test_replacement_aborts_before_launch_when_preparation_or_checkpoint_fails(tmp_path, failed_stage):
    from fastapi import HTTPException
    cfg = Config(data_dir=tmp_path)
    app = create_app(cfg)
    store = app.state.store
    store.upsert_catalog([{'game_id': 'g', 'title': 'Game', 'platform': 'ps1', 'source_paths': [], 'format': 'cue'}])
    store.put('worker', 'w', {'id': 'w', 'name': 'PC', 'os': 'windows', 'last_seen': time.time()})
    store.put('session', 'w-live', {'session_id': 'w-live', 'game_id': 'g', 'state': 'running'})
    route = next(r for r in app.routes if getattr(r, 'path', '') == '/api/sessions/{sid}/swap')
    swap = enclosed(enclosed(route.endpoint, 'swap_job').cell_contents, 'session_swap').cell_contents
    calls = []
    def run(tool, *args, **kwargs):
        calls.append(tool)
        if tool == failed_stage: raise HTTPException(409, 'test failure')
        return {'mean_luma': 20}
    enclosed(swap, '_run_job').cell_contents = run
    with pytest.raises(HTTPException): swap('w-live', 'sonic', '', 'operator')
    assert 'launch_game' not in calls
    assert 'session_op' not in calls
    assert store.get('session', 'w-live')['state'] == 'running'


def test_restore_loads_actual_written_slot_and_ignores_other_games(tmp_path, monkeypatch):
    states = tmp_path / 'states'
    states.mkdir()
    restored = b'preserved-current-moment'
    digest = hashlib.sha256(restored).hexdigest()
    written = states / 'Current.state18'
    loaded = []
    def save(slot):
        written.write_bytes(b'placeholder')
        (states / 'Other.state9').write_bytes(b'unrelated')
    ad = SimpleNamespace(name='retroarch', save_state=save, load_state=loaded.append)
    monkeypatch.setitem(tools.SESSIONS, 'worker-test', (ad, {'_rom_path': 'Current.cue', 'game_id': 'g'}))
    monkeypatch.setattr(tools.httpx, 'get', lambda *a, **k: httpx.Response(200, content=restored, request=httpx.Request('GET', 'http://test')))
    monkeypatch.setattr(tools.time, 'sleep', lambda _: None)
    ctx = SimpleNamespace(config=SimpleNamespace(runtime=tmp_path), server='http://test', headers={})
    result = tools.state_transfer(tools.StateXIn(session_id='worker-test', op='import', artifact=digest), ctx)
    assert result['result']['load_requested']
    assert result['result']['load_verified'] is False
    assert 'loaded' not in result['result']
    assert written.read_bytes() == restored
    assert loaded == [18]
    assert (states / 'Other.state9').read_bytes() == b'unrelated'


def test_export_saved_uses_existing_game_checkpoint_without_resaving(tmp_path, monkeypatch):
    states = tmp_path / 'states'
    states.mkdir()
    saved = states / 'Current.state40'
    saved.write_bytes(b'exact-failed-moment')
    (states / 'Other.state99').write_bytes(b'unrelated')
    def unexpected(*args):
        pytest.fail('export_saved must not advance the emulated game or overwrite the checkpoint')
    ad = SimpleNamespace(name='retroarch', save_state=unexpected)
    monkeypatch.setitem(tools.SESSIONS, 'worker-exact', (ad, {'_rom_path': 'Current.cue', 'game_id': 'g'}))
    artifacts = []
    ctx = SimpleNamespace(config=SimpleNamespace(runtime=tmp_path), artifact=lambda *args, **kwargs: artifacts.append(args))
    result = tools.state_transfer(tools.StateXIn(session_id='worker-exact', op='export_saved',
        slot=40, not_before=saved.stat().st_mtime), ctx)
    assert result['result']['file'] == 'Current.state40'
    assert artifacts[0][1] == b'exact-failed-moment'
    with pytest.raises(RuntimeError, match='no matching saved checkpoint'):
        tools.state_transfer(tools.StateXIn(session_id='worker-exact', op='export_saved',
            slot=40, not_before=saved.stat().st_mtime + 60), ctx)


def test_bad_checkpoint_never_saves_or_loads(tmp_path, monkeypatch):
    def unexpected(*args):
        pytest.fail('emulator must not change for a corrupt checkpoint')
    ad = SimpleNamespace(name='retroarch', save_state=unexpected, load_state=unexpected)
    monkeypatch.setitem(tools.SESSIONS, 'worker-test', (ad, {'_rom_path': 'Current.cue'}))
    monkeypatch.setattr(tools.httpx, 'get', lambda *a, **k: httpx.Response(200, content=b'corrupt', request=httpx.Request('GET', 'http://test')))
    ctx = SimpleNamespace(config=SimpleNamespace(runtime=tmp_path), server='http://test', headers={})
    with pytest.raises(ValueError, match='checkpoint'):
        tools.state_transfer(tools.StateXIn(session_id='worker-test', op='import', artifact='wrong'), ctx)


@pytest.mark.parametrize('corrupt', [False, True])
def test_mod_resume_verifies_partial_and_publishes_marker_last(tmp_path, monkeypatch, corrupt):
    cfg = SimpleNamespace(cache=tmp_path)
    out = filemods.mod_dir(cfg, 'g', 'model')
    out.mkdir(parents=True)
    data = {'disc.bin': b'abcdefgh', '.gbox-mod.json': b'{}'}
    (out / 'disc.bin.part').write_bytes(b'bad' if corrupt else b'abc')
    files = [{'path': p, 'size': len(b), 'sha256': hashlib.sha256(b).hexdigest()} for p, b in data.items()]
    monkeypatch.setattr(httpx, 'get', lambda *a, **k: httpx.Response(200, json={'files': files}, request=httpx.Request('GET', 'http://test')))
    ranges = []
    class Stream:
        def __init__(self, name, headers):
            offset = int(headers.get('Range', 'bytes=0-').split('=')[1].split('-')[0])
            ranges.append((name, offset))
            self.status_code = 206 if offset else 200
            self.headers = {'Content-Range': f'bytes {offset}-{len(data[name])-1}/{len(data[name])}'}
            self.content = data[name][offset:]
            if name == '.gbox-mod.json':
                assert (out / 'disc.bin').read_bytes() == data['disc.bin']
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def raise_for_status(self): pass
        def iter_bytes(self, n): yield self.content
    monkeypatch.setattr(httpx, 'stream', lambda method, url, headers, **kw: Stream(url.rsplit('/', 1)[-1], headers))
    assert filemods.fetch(cfg, 'http://test', {}, 'g', 'model')
    assert (out / 'disc.bin').read_bytes() == data['disc.bin']
    assert ranges[0] == ('disc.bin', 3)
    if corrupt: assert ('disc.bin', 0) in ranges


def test_modded_launch_reuses_active_replacement_after_old_session_ends(tmp_path):
    cfg = Config(data_dir=tmp_path)
    app = create_app(cfg)
    store = app.state.store
    store.upsert_catalog([{'game_id': 'g', 'title': 'Game', 'platform': 'ps1', 'source_paths': [], 'format': 'cue'}])
    store.put('worker', 'w', {'id': 'w', 'name': 'PC', 'os': 'windows', 'last_seen': time.time()})
    store.put('session', 'w-old', {'session_id': 'w-old', 'game_id': 'g', 'state': 'ended'})
    from gbox.models import Job
    job = Job(tool='session_swap', state='running', input={'session_id': 'w-old', 'game_id': 'g', 'mod': 'sonic', 'to': '', 'keep_state': True})
    store.put('job', job.id, job.model_dump())
    with TestClient(app, headers={'Authorization': 'Bearer ' + cfg.token()}) as client:
        same = client.post('/api/games/g/launch?mod=sonic&node=windows')
        assert same.status_code == 200
        assert same.json()['id'] == job.id
        different = client.post('/api/games/g/launch?mod=shadow&node=windows')
        assert different.status_code == 409
    assert len(store.all('job')) == 1
