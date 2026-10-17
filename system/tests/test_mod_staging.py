"""#1270: a same-name mod rebuild while the running game holds the old disc open (Windows WinError 5 on .part -> .bin)."""
import hashlib
import json
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from gbox import filemods, tools
from gbox.config import Config
from gbox.server import create_app

NEW = {'game.gdi': b'3\n1 0 4 2352 game.track01.bin 0\n', 'game.track03.bin': b'NEW-PLAY-DATA',
       '.gbox-mod.json': json.dumps({'name': 'amy', 'game_id': 'g', 'image': 'game.gdi'}).encode()}


STREAMED = []


def serve(monkeypatch, data=NEW):
    STREAMED.clear()
    files = [{'path': p, 'size': len(b), 'sha256': hashlib.sha256(b).hexdigest()} for p, b in data.items()]
    monkeypatch.setattr(httpx, 'get', lambda *a, **k: httpx.Response(200, json={'files': files}, request=httpx.Request('GET', 'http://t')))

    class Stream:
        def __init__(self, name):
            STREAMED.append(name)
            self.status_code, self.headers, self.content = 200, {}, data[name]
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def raise_for_status(self): pass
        def iter_bytes(self, n): yield self.content
    monkeypatch.setattr(httpx, 'stream', lambda method, url, headers, **kw: Stream(url.rsplit('/', 1)[-1]))


def running_old_build(tmp_path, monkeypatch):
    """The old build is in the cache and the emulator holds its track03 open: replacing it raises WinError 5."""
    cfg = SimpleNamespace(cache=tmp_path)
    old = filemods.mod_dir(cfg, 'g', 'amy')
    old.mkdir(parents=True)
    (old / 'game.gdi').write_bytes(NEW['game.gdi'])
    (old / 'game.track03.bin').write_bytes(b'OLD-PLAY-DATA')
    (old / '.gbox-mod.json').write_text('{"name": "amy", "image": "game.gdi"}')
    locked = (old / 'game.track03.bin').resolve()
    real = filemods.os.replace

    def replace(src, dst):
        if __import__('pathlib').Path(dst).resolve() == locked:
            raise PermissionError(13, 'Access is denied', str(src))
        return real(src, dst)
    monkeypatch.setattr(filemods.os, 'replace', replace)
    serve(monkeypatch)
    return cfg, old


def test_locked_running_copy_stages_new_build_beside_it(tmp_path, monkeypatch):
    cfg, old = running_old_build(tmp_path, monkeypatch)
    before = {p.name: p.read_bytes() for p in old.iterdir()}
    said = []
    name = filemods.stage(cfg, 'http://t', {}, 'g', 'amy', lambda pct, msg: said.append(msg))
    assert name.startswith('amy~') and name != 'amy'
    new = filemods.mod_dir(cfg, 'g', name)
    assert (new / 'game.track03.bin').read_bytes() == b'NEW-PLAY-DATA'      # same file names, verified new content
    assert (new / 'game.gdi').read_bytes() == NEW['game.gdi']
    assert (new / '.gbox-mod.json').exists() and (new / filemods.STAGED_MARK).read_text() == 'amy'
    assert (old / 'game.track03.bin').read_bytes() == b'OLD-PLAY-DATA'      # the running game's copy is untouched
    assert before == {p.name: p.read_bytes() for p in old.iterdir()}          # old metadata and every old resource are retained
    assert filemods.launch_path(cfg, 'g', old / 'x', name) == new / 'game.gdi'
    assert any('Preserving the existing game copy' in m for m in said)
    assert STREAMED.count('game.track03.bin') == 1
    assert STREAMED.count('game.gdi') == 0                                   # unchanged file copied and sha-checked
    assert not (new / 'game.gdi').samefile(old / 'game.gdi')                 # future source writes cannot change this stage
    assert filemods.stage(cfg, 'http://t', {}, 'g', 'amy') == name            # same build -> same folder, resumable


def test_same_size_changed_file_is_downloaded_not_linked_to_the_locked_copy(tmp_path, monkeypatch):
    cfg, old = running_old_build(tmp_path, monkeypatch)
    (old / 'game.track03.bin').write_bytes(b'OLD-PLAY-DAT!')                  # same size as the new build, other content
    name = filemods.stage(cfg, 'http://t', {}, 'g', 'amy')
    new = filemods.mod_dir(cfg, 'g', name) / 'game.track03.bin'
    assert new.read_bytes() == b'NEW-PLAY-DATA'
    assert not new.samefile(old / 'game.track03.bin')


def test_fresh_fetch_keeps_name_and_preserves_all_prior_staged_copies(tmp_path, monkeypatch):
    cfg = SimpleNamespace(cache=tmp_path)
    stale = filemods.mod_dir(cfg, 'g', 'amy~0123456789')
    stale.mkdir(parents=True)
    (stale / filemods.STAGED_MARK).write_text('amy')
    other = filemods.mod_dir(cfg, 'g', 'amy~user-named')                     # not a staging copy: never removed
    other.mkdir(parents=True)
    serve(monkeypatch)
    assert filemods.stage(cfg, 'http://t', {}, 'g', 'amy') == 'amy'
    assert (filemods.mod_dir(cfg, 'g', 'amy') / 'game.track03.bin').read_bytes() == b'NEW-PLAY-DATA'
    assert stale.exists() and other.exists()


def test_staged_copies_are_not_pushed_or_listed(tmp_path, monkeypatch):
    cfg, _ = running_old_build(tmp_path, monkeypatch)
    name = filemods.stage(cfg, 'http://t', {}, 'g', 'amy')
    (filemods.mod_dir(cfg, 'g', 'amy') / '.gbox-mod.json').write_text('{"name": "amy"}')
    assert [m['name'] for m in filemods.list_mods(cfg, 'g')] == ['amy']
    puts = []
    monkeypatch.setattr(httpx, 'get', lambda *a, **k: httpx.Response(404, request=httpx.Request('GET', 'http://t')))
    monkeypatch.setattr(httpx, 'put', lambda url, **k: puts.append(url) or httpx.Response(200, request=httpx.Request('PUT', url)))
    filemods.push_missing(cfg, 'http://t', {})
    assert puts and not any(name in u for u in puts)


def test_prepare_mod_returns_the_folder_to_launch(tmp_path, monkeypatch):
    cfg, _ = running_old_build(tmp_path, monkeypatch)
    game = tools.CatalogEntry.model_validate({'game_id': 'g', 'title': 'Jet Grind Radio (USA)', 'platform': 'dreamcast',
                                              'profile_id': 'dreamcast', 'source_paths': [], 'format': 'gdi'})
    ctx = SimpleNamespace(config=cfg, server='http://t', headers={}, progress=lambda *a: None)
    out = tools.prepare_mod(tools.PrepareModIn(game=game, mod='amy'), ctx)
    assert out['ready'] and out['mod'].startswith('amy~')
    assert out['source_mod'] == 'amy'


def enclosed(fn, name):
    return dict(zip(fn.__code__.co_freevars, fn.__closure__))[name]


def test_session_swap_launches_the_staged_folder_and_keeps_the_mod_name(tmp_path):
    cfg = Config(data_dir=tmp_path)
    app = create_app(cfg)
    store = app.state.store
    store.upsert_catalog([{'game_id': 'g', 'title': 'Game', 'platform': 'dreamcast', 'source_paths': [], 'format': 'gdi'}])
    store.put('worker', 'w', {'id': 'w', 'name': 'PC', 'os': 'windows', 'last_seen': time.time()})
    store.put('session', 'w-live', {'session_id': 'w-live', 'game_id': 'g', 'state': 'running', 'mod': 'amy'})
    route = next(r for r in app.routes if getattr(r, 'path', '') == '/api/sessions/{sid}/swap')
    swap = enclosed(enclosed(route.endpoint, 'swap_job').cell_contents, 'session_swap').cell_contents
    calls = []

    def run(tool, inp, *a, **k):
        calls.append((tool, dict(inp)))
        if tool == 'prepare_mod': return {'ready': True, 'mod': 'amy~abc'}
        if tool == 'launch_game':
            store.put('session', 'w-new', {'session_id': 'w-new', 'game_id': 'g', 'state': 'running', 'mod': inp['mod']})
            return {'session_id': 'w-new'}
        return {}
    enclosed(swap, '_run_job').cell_contents = run
    out = swap('w-live', 'amy', '', 'operator', keep_state=False)
    assert [i['mod'] for t, i in calls if t == 'launch_game'] == ['amy~abc']
    assert out['mod'] == 'amy' and out['session_id'] == 'w-new'
    assert store.get('session', 'w-new')['mod'] == 'amy' and store.get('session', 'w-new')['staged_mod'] == 'amy~abc'
    assert out['launch_mod'] == 'amy~abc' and store.get('session', 'w-new')['launch_mod'] == 'amy~abc'


def test_unlocked_existing_build_is_never_overwritten(tmp_path, monkeypatch):
    cfg, old = running_old_build(tmp_path, monkeypatch)
    monkeypatch.undo()
    serve(monkeypatch)
    before = {p.name: p.read_bytes() for p in old.iterdir()}
    name = filemods.stage(cfg, 'http://t', {}, 'g', 'amy')
    assert name != 'amy'
    assert before == {p.name: p.read_bytes() for p in old.iterdir()}


def test_existing_partial_is_not_moved_or_modified(tmp_path, monkeypatch):
    cfg, old = running_old_build(tmp_path, monkeypatch)
    partial = old / 'game.track03.bin.part'
    partial.write_bytes(NEW['game.track03.bin'])
    before = {p.name: p.read_bytes() for p in old.iterdir()}
    filemods.stage(cfg, 'http://t', {}, 'g', 'amy')
    assert before == {p.name: p.read_bytes() for p in old.iterdir()}


def test_changed_metadata_uses_a_different_stage_with_equal_disc_bytes(tmp_path, monkeypatch):
    cfg, old = running_old_build(tmp_path, monkeypatch)
    first = filemods.stage(cfg, 'http://t', {}, 'g', 'amy')
    old_stage = filemods.mod_dir(cfg, 'g', first)
    before = {p.name: p.read_bytes() for p in old_stage.iterdir()}
    changed = dict(NEW, **{'.gbox-mod.json': json.dumps({'name': 'amy', 'game_id': 'g',
                         'image': 'game.gdi', 'provenance': 'new-build'}).encode()})
    serve(monkeypatch, changed)
    second = filemods.stage(cfg, 'http://t', {}, 'g', 'amy')
    assert first != second
    assert before == {p.name: p.read_bytes() for p in old_stage.iterdir()}
    assert (filemods.mod_dir(cfg, 'g', second) / '.gbox-mod.json').read_bytes() == changed['.gbox-mod.json']


def test_corrupt_existing_stage_is_preserved_and_replaced_by_new_sibling(tmp_path, monkeypatch):
    cfg, old = running_old_build(tmp_path, monkeypatch)
    first = filemods.stage(cfg, 'http://t', {}, 'g', 'amy')
    corrupt = filemods.mod_dir(cfg, 'g', first)
    (corrupt / 'game.track03.bin').write_bytes(b'CORRUPT')
    before = {p.name: p.read_bytes() for p in corrupt.iterdir()}
    second = filemods.stage(cfg, 'http://t', {}, 'g', 'amy')
    assert first != second and second.startswith(first + '-')
    assert before == {p.name: p.read_bytes() for p in corrupt.iterdir()}


@pytest.mark.parametrize('bad_path', ['../escape', 'nested/../../escape', '/absolute', 'C:/absolute',
                                    r'..\escape', 'track:stream', 'nested//track'])
def test_manifest_paths_reject_before_any_cache_write(tmp_path, monkeypatch, bad_path):
    serve(monkeypatch, dict(NEW, **{bad_path: b'bad'}))
    with pytest.raises(ValueError, match='cache folder'):
        filemods.stage(SimpleNamespace(cache=tmp_path), 'http://t', {}, 'g', 'amy')
    assert not (tmp_path / 'mods').exists() and STREAMED == []


@pytest.mark.parametrize('bad_name', ['..', '../amy', r'..\amy', 'C:/amy', 'amy:stream', '/amy'])
def test_mod_name_cannot_escape_cache(tmp_path, monkeypatch, bad_name):
    serve(monkeypatch)
    with pytest.raises(ValueError, match='components'):
        filemods.stage(SimpleNamespace(cache=tmp_path), 'http://t', {}, 'g', bad_name)
    assert not (tmp_path / 'mods').exists()


@pytest.mark.parametrize('bad_manifest', ['missing_hash', 'duplicate', 'missing_marker'])
def test_bad_manifest_never_publishes_a_cache(tmp_path, monkeypatch, bad_manifest):
    rows = [{'path': p, 'size': len(b), 'sha256': hashlib.sha256(b).hexdigest()} for p, b in NEW.items()]
    if bad_manifest == 'missing_hash': rows[0].pop('sha256')
    if bad_manifest == 'duplicate': rows.append(dict(rows[0], path=rows[0]['path'].upper()))
    if bad_manifest == 'missing_marker': rows.pop()
    monkeypatch.setattr(httpx, 'get', lambda *a, **k: httpx.Response(200, json={'files': rows},
        request=httpx.Request('GET', 'http://t')))
    with pytest.raises(ValueError):
        filemods.stage(SimpleNamespace(cache=tmp_path), 'http://t', {}, 'g', 'amy')
    assert not (tmp_path / 'mods').exists()


def test_listing_is_pinned_and_content_drift_cannot_publish_metadata(tmp_path, monkeypatch):
    serve(monkeypatch)
    original_stream = httpx.stream
    calls = []
    def get(*a, **k):
        calls.append(a[0])
        return httpx.Response(200, json={'files': [{'path': p, 'size': len(b),
            'sha256': hashlib.sha256(b).hexdigest()} for p, b in NEW.items()]},
            request=httpx.Request('GET', 'http://t'))
    monkeypatch.setattr(httpx, 'get', get)
    def drift(method, url, **kw):
        stream = original_stream(method, url, **kw)
        if url.endswith('game.track03.bin'): stream.content = b'OTHER-CONTENT'
        return stream
    monkeypatch.setattr(httpx, 'stream', drift)
    with pytest.raises(ValueError, match='mismatch'):
        filemods.stage(SimpleNamespace(cache=tmp_path), 'http://t', {}, 'g', 'amy')
    assert len(calls) == 1
    assert not (tmp_path / 'mods/g/amy/.gbox-mod.json').exists()


def test_launch_metadata_cannot_point_outside_prepared_folder(tmp_path):
    cfg = SimpleNamespace(cache=tmp_path)
    folder = filemods.mod_dir(cfg, 'g', 'amy')
    folder.mkdir(parents=True)
    (folder / '.gbox-mod.json').write_text(json.dumps({'image': '../other/game.gdi'}))
    with pytest.raises(ValueError, match='cache folder'):
        filemods.launch_path(cfg, 'g', Path('Original.gdi'), 'amy')


def test_modfile_endpoint_cannot_write_a_sibling_cache(tmp_path):
    from fastapi.testclient import TestClient
    cfg = Config(data_dir=tmp_path)
    app = create_app(cfg)
    with TestClient(app, headers={'Authorization': 'Bearer ' + cfg.token()}) as client:
        response = client.put('/api/modfiles/g/amy/file/%2E%2E/amy-other/escape.bin', content=b'bad')
    assert response.status_code == 400
    assert not (Path(cfg.cache) / 'mods/g/amy-other/escape.bin').exists()


@pytest.mark.parametrize('prepared', [{'ready': False, 'mod': 'amy'},
    {'ready': True, 'mod': '../other'}, {'ready': True, 'mod': 'another'},
    {'ready': True, 'mod': 'amy~new', 'source_mod': 'another'}])
def test_invalid_prepared_route_keeps_the_current_game_untouched(tmp_path, prepared):
    from fastapi import HTTPException
    cfg = Config(data_dir=tmp_path)
    app = create_app(cfg)
    store = app.state.store
    store.upsert_catalog([{'game_id': 'g', 'title': 'Game', 'platform': 'dreamcast', 'source_paths': [], 'format': 'gdi'}])
    store.put('worker', 'w', {'id': 'w', 'name': 'PC', 'os': 'windows', 'last_seen': time.time()})
    before = {'session_id': 'w-live', 'game_id': 'g', 'state': 'running', 'mod': 'amy'}
    store.put('session', 'w-live', before)
    route = next(r for r in app.routes if getattr(r, 'path', '') == '/api/sessions/{sid}/swap')
    swap = enclosed(enclosed(route.endpoint, 'swap_job').cell_contents, 'session_swap').cell_contents
    calls = []
    def run(tool, *a, **kw):
        calls.append(tool)
        return prepared
    enclosed(swap, '_run_job').cell_contents = run
    with pytest.raises(HTTPException) as error:
        swap('w-live', 'amy', '', 'operator')
    assert error.value.status_code == 409
    assert calls == ['prepare_mod'] and store.get('session', 'w-live') == before


def test_failed_staged_launch_recovers_the_exact_previous_stage(tmp_path):
    from fastapi import HTTPException
    cfg = Config(data_dir=tmp_path)
    app = create_app(cfg)
    store = app.state.store
    store.upsert_catalog([{'game_id': 'g', 'title': 'Game', 'platform': 'dreamcast', 'source_paths': [], 'format': 'gdi'}])
    store.put('worker', 'w', {'id': 'w', 'name': 'PC', 'os': 'windows', 'last_seen': time.time()})
    store.put('session', 'w-live', {'session_id': 'w-live', 'game_id': 'g', 'state': 'running',
                                  'mod': 'amy', 'staged_mod': 'amy~old', 'launch_mod': 'amy~old'})
    route = next(r for r in app.routes if getattr(r, 'path', '') == '/api/sessions/{sid}/swap')
    swap = enclosed(enclosed(route.endpoint, 'swap_job').cell_contents, 'session_swap').cell_contents
    calls = []
    def run(tool, inp, *a, **k):
        calls.append((tool, inp))
        if tool == 'prepare_mod': return {'ready': True, 'mod': 'amy~new', 'source_mod': 'amy'}
        if tool == 'launch_game' and inp['mod'] == 'amy~old': return {'session_id': 'w-back'}
        raise HTTPException(409, 'launch or previous-session probe failed')
    enclosed(swap, '_run_job').cell_contents = run
    with pytest.raises(HTTPException):
        swap('w-live', 'amy', '', 'operator', keep_state=False)
    assert [inp['mod'] for tool, inp in calls if tool == 'launch_game'] == ['amy~new', 'amy~old']


def test_transient_local_copy_failure_falls_back_to_verified_download(tmp_path, monkeypatch):
    cfg, old = running_old_build(tmp_path, monkeypatch)
    monkeypatch.setattr(filemods.shutil, 'copy2', lambda *a, **kw: (_ for _ in ()).throw(PermissionError('read locked')))
    name = filemods.stage(cfg, 'http://t', {}, 'g', 'amy')
    assert (filemods.mod_dir(cfg, 'g', name) / 'game.gdi').read_bytes() == NEW['game.gdi']
    assert STREAMED.count('game.gdi') == 1


def test_launch_receipt_retains_collection_and_actual_stage_identities():
    records = {}
    store = SimpleNamespace(get=lambda kind, sid: records.get(sid),
        put=lambda kind, sid, doc: records.__setitem__(sid, doc))
    out = tools.LaunchOut(session_id='w-new', adapter='retroarch', capabilities={}, detail={
        'mod': 'amy~verified', 'collection_mod': 'amy'})
    tools._launch_accept(store, out, 'operator')
    session = records['w-new']
    assert session['mod'] == 'amy' and session['launch_mod'] == 'amy~verified'
    assert session['staged_mod'] == 'amy~verified' and session['detail']['mod'] == 'amy~verified'


@pytest.mark.parametrize('old_folder', ['canonical', 'stage'])
def test_removed_asset_selects_a_new_stage_without_altering_the_previous_copy(tmp_path, monkeypatch, old_folder):
    cfg = SimpleNamespace(cache=tmp_path)
    old = filemods.mod_dir(cfg, 'g', 'amy')
    old.mkdir(parents=True)
    for name, content in NEW.items():
        (old / name).write_bytes(content)
    serve(monkeypatch)
    if old_folder == 'stage':
        (old / 'game.track03.bin').write_bytes(b'old')
        alias = filemods.stage(cfg, 'http://t', {}, 'g', 'amy')
        previous = filemods.mod_dir(cfg, 'g', alias)
    else:
        previous = old
    (previous / 'obsolete.bin').write_bytes(b'previous build asset')
    (previous / 'download.part').write_bytes(b'keep partial')
    before = {p.name: p.read_bytes() for p in previous.iterdir()}
    selected = filemods.stage(cfg, 'http://t', {}, 'g', 'amy')
    new = filemods.mod_dir(cfg, 'g', selected)
    assert new != previous and not (new / 'obsolete.bin').exists()
    assert before == {p.name: p.read_bytes() for p in previous.iterdir()}
    assert {p.name for p in new.iterdir()} == set(NEW) | {filemods.STAGED_MARK}


def test_dropped_download_resumes_from_the_partial_file(tmp_path, monkeypatch):
    """The collection can close a multi-GB stream before its Content-Length is sent
    (httpx.RemoteProtocolError). A resumable fetch must retry from the .part offset instead of
    failing the whole launch; this was the GTA LCS / lcs_sonic launch failure (3824 MB mod dropped
    at ~266 MB)."""
    data = b'NEW-PLAY-DATA'
    files = [{'path': 'big.bin', 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}]
    monkeypatch.setattr(filemods, '_FETCH_RETRY_DELAY', 0)
    monkeypatch.setattr(httpx, 'get', lambda *a, **k: httpx.Response(
        200, json={'files': files}, request=httpx.Request('GET', 'http://t')))

    calls = {'stream': 0, 'range': None}

    class DropStream:
        def __init__(self, url, headers=None, **kw):
            calls['stream'] += 1
            calls['range'] = (headers or {}).get('Range')
            if calls['stream'] == 1:
                self.status_code, self.headers = 200, {}
            else:
                self.status_code, self.headers = 206, {'Content-Range': 'bytes 5-12/13'}

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def raise_for_status(self):
            pass

        def iter_bytes(self, n):
            if calls['stream'] == 1:
                yield data[:5]                 # 5 bytes land, then the peer drops the connection
                raise httpx.RemoteProtocolError(
                    'peer closed connection without sending complete message body')
            yield data[5:]                     # the resume serves only the remainder

    monkeypatch.setattr(httpx, 'stream', lambda method, url, headers=None, **kw: DropStream(url, headers, **kw))

    out = tmp_path / 'out'
    out.mkdir()
    filemods._fetch(SimpleNamespace(cache=tmp_path), 'http://t', {}, 'g', 'amy', files=files, dest=out)

    assert calls['stream'] == 2
    assert calls['range'] == 'bytes=5-'        # the retry resumed, it did not restart from zero
    assert (out / 'big.bin').read_bytes() == data
    assert not (out / 'big.bin.part').exists()


def test_resumable_download_creates_an_empty_manifest_file(tmp_path, monkeypatch):
    data = {"empty.bin": b""}
    files = [{"path": "empty.bin", "size": 0, "sha256": hashlib.sha256(b"").hexdigest()}]
    class Stream:
        status_code, headers = 200, {}
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def raise_for_status(self): pass
        def iter_bytes(self, size): return iter(())
    monkeypatch.setattr(httpx, "stream", lambda *a, **k: Stream())
    filemods._fetch(SimpleNamespace(cache=tmp_path), "http://t", {}, "g", "amy", files=files, dest=tmp_path)
    assert (tmp_path / "empty.bin").read_bytes() == b""
    assert not (tmp_path / "empty.bin.part").exists()
