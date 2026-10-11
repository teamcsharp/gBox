"""#1270: a same-name mod rebuild while the running game holds the old disc open (Windows WinError 5 on .part -> .bin)."""
import hashlib
import json
import time
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
    said = []
    name = filemods.stage(cfg, 'http://t', {}, 'g', 'amy', lambda pct, msg: said.append(msg))
    assert name.startswith('amy~') and name != 'amy'
    new = filemods.mod_dir(cfg, 'g', name)
    assert (new / 'game.track03.bin').read_bytes() == b'NEW-PLAY-DATA'      # same file names, verified new content
    assert (new / 'game.gdi').read_bytes() == NEW['game.gdi']
    assert (new / '.gbox-mod.json').exists() and (new / filemods.STAGED_MARK).read_text() == 'amy'
    assert (old / 'game.track03.bin').read_bytes() == b'OLD-PLAY-DATA'      # the running game's copy is untouched
    assert not (old / '.gbox-mod.json').exists()                             # a half-updated folder is never launched as finished
    assert filemods.launch_path(cfg, 'g', old / 'x', name) == new / 'game.gdi'
    assert any('open in the running game' in m for m in said)
    assert STREAMED.count('game.track03.bin') == 1                           # the finished download moved over, not fetched twice
    assert STREAMED.count('game.gdi') == 0                                   # unchanged file hard-linked and sha-checked
    assert filemods.stage(cfg, 'http://t', {}, 'g', 'amy') == name            # same build -> same folder, resumable


def test_same_size_changed_file_is_downloaded_not_linked_to_the_locked_copy(tmp_path, monkeypatch):
    cfg, old = running_old_build(tmp_path, monkeypatch)
    (old / 'game.track03.bin').write_bytes(b'OLD-PLAY-DAT!')                  # same size as the new build, other content
    name = filemods.stage(cfg, 'http://t', {}, 'g', 'amy')
    new = filemods.mod_dir(cfg, 'g', name) / 'game.track03.bin'
    assert new.read_bytes() == b'NEW-PLAY-DATA'
    assert not new.samefile(old / 'game.track03.bin')


def test_unlocked_fetch_keeps_name_and_drops_stale_staged_copies(tmp_path, monkeypatch):
    cfg = SimpleNamespace(cache=tmp_path)
    stale = filemods.mod_dir(cfg, 'g', 'amy~0123456789')
    stale.mkdir(parents=True)
    (stale / filemods.STAGED_MARK).write_text('amy')
    other = filemods.mod_dir(cfg, 'g', 'amy~user-named')                     # not a staging copy: never removed
    other.mkdir(parents=True)
    serve(monkeypatch)
    assert filemods.stage(cfg, 'http://t', {}, 'g', 'amy') == 'amy'
    assert (filemods.mod_dir(cfg, 'g', 'amy') / 'game.track03.bin').read_bytes() == b'NEW-PLAY-DATA'
    assert not stale.exists() and other.exists()


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
