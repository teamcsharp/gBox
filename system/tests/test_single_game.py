import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from gbox import tools
from gbox.registry import Unsupported


def test_parallel_launches_are_serialized(monkeypatch):
    active = 0
    peak = 0
    lock = threading.Lock()
    def launch(inp, ctx):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(.04)
        with lock: active -= 1
        return inp
    monkeypatch.setattr(tools, '_launch_game', launch)
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(lambda n: tools.launch_game(n, None), [1, 2])) == [1, 2]
    assert peak == 1


def test_switch_checkpoints_all_games_before_stopping_any(monkeypatch, tmp_path):
    events = []
    sessions = {}
    for sid in ('old1', 'old2'):
        ad = SimpleNamespace(proc=None, stop_game=lambda sid=sid: events.append(('stop', sid)))
        sessions[sid] = (ad, {'game_id': sid})
    monkeypatch.setattr(tools, 'SESSIONS', sessions)
    monkeypatch.setattr(tools, 'state_transfer', lambda inp, ctx: events.append(('save', inp.session_id)) or {'result': {'artifact': inp.session_id}})
    monkeypatch.setattr(tools, 'track_emulator', lambda *a, **k: None)
    ctx = SimpleNamespace(config=SimpleNamespace(runtime=tmp_path), progress=lambda *a: None)
    snapshots = tools._close_previous_games(ctx)
    assert events == [('save', 'old1'), ('save', 'old2'), ('stop', 'old1'), ('stop', 'old2')]
    assert [s['artifact'] for s in snapshots] == ['old1', 'old2']
    assert not sessions


def test_failed_checkpoint_keeps_all_previous_games(monkeypatch, tmp_path):
    events = []
    sessions = {s: (SimpleNamespace(proc=None, stop_game=lambda: events.append('stop')), {'game_id': s}) for s in ('old1', 'old2')}
    monkeypatch.setattr(tools, 'SESSIONS', sessions)
    def save(inp, ctx):
        if inp.session_id == 'old2': raise RuntimeError('save failed')
        return {'result': {'artifact': 'backup'}}
    monkeypatch.setattr(tools, 'state_transfer', save)
    ctx = SimpleNamespace(config=SimpleNamespace(runtime=tmp_path), progress=lambda *a: None)
    with pytest.raises(Unsupported, match='kept running'):
        tools._close_previous_games(ctx)
    assert not events
    assert len(sessions) == 2


def test_emulator_that_does_not_stop_blocks_another_game(monkeypatch, tmp_path):
    ad = SimpleNamespace(proc=SimpleNamespace(poll=lambda: None), stop_game=lambda: None)
    monkeypatch.setattr(tools, 'SESSIONS', {'old': (ad, {'game_id': 'g'})})
    monkeypatch.setattr(tools, 'state_transfer', lambda *a: {'result': {'artifact': 'backup'}})
    ctx = SimpleNamespace(config=SimpleNamespace(runtime=tmp_path), progress=lambda *a: None)
    with pytest.raises(RuntimeError, match='still running'):
        tools._close_previous_games(ctx)
    assert 'old' in tools.SESSIONS


def test_stopped_session_is_published_before_it_leaves_worker(monkeypatch, tmp_path):
    sessions = {'old': (SimpleNamespace(proc=None, stop_game=lambda: None), {'game_id': 'g'})}
    monkeypatch.setattr(tools, 'SESSIONS', sessions)
    monkeypatch.setattr(tools, 'state_transfer', lambda *a: {'result': {'artifact': 'backup'}})
    monkeypatch.setattr(tools, 'track_emulator', lambda *a, **kw: None)
    calls = []
    def post(url, **kwargs):
        assert 'old' in sessions
        calls.append((url, kwargs['json']))
        return SimpleNamespace(raise_for_status=lambda: None)
    monkeypatch.setattr(tools.httpx, 'post', post)
    ctx = SimpleNamespace(server='http://test', headers={}, config=SimpleNamespace(runtime=tmp_path), progress=lambda *a: None)
    tools._close_previous_games(ctx)
    assert calls == [('http://test/api/sessions/old/ended', {'via': 'single_game', 'checkpoint': 'backup'})]
    assert not sessions


def test_launch_ingestion_closes_old_session_and_retains_checkpoint():
    records = {'old': {'session_id': 'old', 'state': 'running'}}
    store = SimpleNamespace(get=lambda kind, sid: records.get(sid), put=lambda kind, sid, doc: records.__setitem__(sid, doc))
    output = tools.LaunchOut(session_id='new', adapter='retroarch', capabilities={}, detail={
        'previous_checkpoints': [{'session_id': 'old', 'artifact': 'saved'}]})
    tools._launch_accept(store, output, 'operator')
    assert records['old']['state'] == 'ended'
    assert records['old']['checkpoint'] == 'saved'
    assert records['new']['state'] == 'running'


def test_orphan_session_ended_on_server_is_closed_without_saving(monkeypatch, tmp_path):
    """A leftover emulator the server already ended must not block every launch (operator report 2026-10-13)."""
    events = []
    ad = SimpleNamespace(proc=None, stop_game=lambda: events.append('stop'))
    monkeypatch.setattr(tools, 'SESSIONS', {'old': (ad, {'game_id': 'g', 'title': 'Crazy Taxi'})})
    monkeypatch.setattr(tools, 'state_transfer', lambda inp, ctx: (_ for _ in ()).throw(RuntimeError("gBox isn't the active window")))
    monkeypatch.setattr(tools, '_session_ended_on_server', lambda ctx, sid: True)
    monkeypatch.setattr(tools.httpx, 'post', lambda *a, **k: events.append('post'))
    ctx = SimpleNamespace(server='http://x', headers={}, config=SimpleNamespace(runtime=tmp_path), progress=lambda *a: None)
    tools._close_previous_games(ctx)
    assert events == ['stop'] and 'old' not in tools.SESSIONS


def test_live_session_save_failure_names_the_game(monkeypatch, tmp_path):
    ad = SimpleNamespace(proc=None, stop_game=lambda: None)
    monkeypatch.setattr(tools, 'SESSIONS', {'old': (ad, {'game_id': 'g', 'title': 'Crazy Taxi'})})
    monkeypatch.setattr(tools, 'state_transfer', lambda inp, ctx: (_ for _ in ()).throw(RuntimeError("gBox isn't the active window")))
    monkeypatch.setattr(tools, '_session_ended_on_server', lambda ctx, sid: False)
    ctx = SimpleNamespace(server=None, headers={}, config=SimpleNamespace(runtime=tmp_path), progress=lambda *a: None)
    with pytest.raises(Unsupported, match='Crazy Taxi'):
        tools._close_previous_games(ctx)
    assert 'old' in tools.SESSIONS


def test_keep_session_leaves_link_host_running(monkeypatch, tmp_path):
    events = []
    sessions = {}
    for sid in ('host', 'other'):
        ad = SimpleNamespace(proc=None, stop_game=lambda sid=sid: events.append(('stop', sid)))
        sessions[sid] = (ad, {'game_id': sid})
    monkeypatch.setattr(tools, 'SESSIONS', sessions)
    monkeypatch.setattr(tools, 'state_transfer', lambda inp, ctx: events.append(('save', inp.session_id)) or {'result': {'artifact': inp.session_id}})
    monkeypatch.setattr(tools, 'track_emulator', lambda *a, **k: None)
    ctx = SimpleNamespace(config=SimpleNamespace(runtime=tmp_path), progress=lambda *a: None)
    snapshots = tools._close_previous_games(ctx, keep='host')
    assert events == [('save', 'other'), ('stop', 'other')]
    assert [s['artifact'] for s in snapshots] == ['other']
    assert 'host' in sessions and 'other' not in sessions


def test_keep_unknown_session_still_closes_all(monkeypatch, tmp_path):
    events = []
    sessions = {'old': (SimpleNamespace(proc=None, stop_game=lambda: events.append('stop')), {'game_id': 'old'})}
    monkeypatch.setattr(tools, 'SESSIONS', sessions)
    monkeypatch.setattr(tools, 'state_transfer', lambda inp, ctx: {'result': {'artifact': 'backup'}})
    monkeypatch.setattr(tools, 'track_emulator', lambda *a, **k: None)
    ctx = SimpleNamespace(config=SimpleNamespace(runtime=tmp_path), progress=lambda *a: None)
    tools._close_previous_games(ctx, keep='ghost')
    assert events == ['stop'] and not sessions
