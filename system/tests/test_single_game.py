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
        ad = SimpleNamespace(checkpoint_state='path', proc=None, stop_game=lambda sid=sid: events.append(('stop', sid)))
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
    sessions = {s: (SimpleNamespace(checkpoint_state='path', proc=None, stop_game=lambda: events.append('stop')), {'game_id': s}) for s in ('old1', 'old2')}
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
    ad = SimpleNamespace(checkpoint_state='path', proc=SimpleNamespace(poll=lambda: None), stop_game=lambda: None)
    monkeypatch.setattr(tools, 'SESSIONS', {'old': (ad, {'game_id': 'g'})})
    monkeypatch.setattr(tools, 'state_transfer', lambda *a: {'result': {'artifact': 'backup'}})
    ctx = SimpleNamespace(config=SimpleNamespace(runtime=tmp_path), progress=lambda *a: None)
    with pytest.raises(RuntimeError, match='still running'):
        tools._close_previous_games(ctx)
    assert 'old' in tools.SESSIONS


def test_stopped_session_is_published_before_it_leaves_worker(monkeypatch, tmp_path):
    sessions = {'old': (SimpleNamespace(checkpoint_state='path', proc=None, stop_game=lambda: None), {'game_id': 'g'})}
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
    ad = SimpleNamespace(checkpoint_state='path', proc=None, stop_game=lambda: None)
    monkeypatch.setattr(tools, 'SESSIONS', {'old': (ad, {'game_id': 'g', 'title': 'Crazy Taxi'})})
    monkeypatch.setattr(tools, 'state_transfer', lambda inp, ctx: (_ for _ in ()).throw(RuntimeError("gBox isn't the active window")))
    monkeypatch.setattr(tools, '_session_ended_on_server', lambda ctx, sid: False)
    ctx = SimpleNamespace(server=None, headers={}, config=SimpleNamespace(runtime=tmp_path), progress=lambda *a: None)
    with pytest.raises(Unsupported, match='Crazy Taxi'):
        tools._close_previous_games(ctx)
    assert 'old' in tools.SESSIONS


@pytest.mark.parametrize('ad_kwargs', [
    {'name': 'cxbx', 'checkpoint_reason': 'Cxbx-Reloaded has no verified in-place save-state interface'},
    {'name': 'rpcs3', 'checkpoint_reason': 'RPCS3 reloads the game on every save state (no in-place rewind)'},
])
def test_adapter_without_portable_save_state_switches_without_blocking(monkeypatch, tmp_path, ad_kwargs):
    """A cxbx/rpcs3 adapter has no in-place save state, so switching games must close it normally (its own saves
    persist) instead of failing the export and blocking every launch on this PC (operator report 2026-10-16)."""
    events = []
    ad = SimpleNamespace(checkpoint_state=False, proc=None, stop_game=lambda: events.append('stop'), **ad_kwargs)
    monkeypatch.setattr(tools, 'SESSIONS',
                        {'old': (ad, {'game_id': 'g', 'title': 'Dead or Alive Ultimate (Disc 1) (USA)'})})
    monkeypatch.setattr(tools, 'state_transfer', lambda inp, ctx: events.append('save'))  # must never run
    monkeypatch.setattr(tools, 'track_emulator', lambda *a, **k: None)
    ctx = SimpleNamespace(server=None, headers={}, config=SimpleNamespace(runtime=tmp_path), progress=lambda *a: None)
    snapshots = tools._close_previous_games(ctx)
    assert events == ['stop']
    assert snapshots == [{'session_id': 'old', 'game_id': 'g', 'artifact': None,
                          'save_state': 'unsupported', 'reason': ad_kwargs['checkpoint_reason']}]
    assert 'old' not in tools.SESSIONS


def test_keep_session_leaves_link_host_running(monkeypatch, tmp_path):
    events = []
    sessions = {}
    for sid in ('host', 'other'):
        ad = SimpleNamespace(checkpoint_state='path', proc=None, stop_game=lambda sid=sid: events.append(('stop', sid)))
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
    sessions = {'old': (SimpleNamespace(checkpoint_state='path', proc=None, stop_game=lambda: events.append('stop')), {'game_id': 'old'})}
    monkeypatch.setattr(tools, 'SESSIONS', sessions)
    monkeypatch.setattr(tools, 'state_transfer', lambda inp, ctx: {'result': {'artifact': 'backup'}})
    monkeypatch.setattr(tools, 'track_emulator', lambda *a, **k: None)
    ctx = SimpleNamespace(config=SimpleNamespace(runtime=tmp_path), progress=lambda *a: None)
    tools._close_previous_games(ctx, keep='ghost')
    assert events == ['stop'] and not sessions


def test_op_on_a_session_the_worker_no_longer_holds_says_relaunch():
    """#840: an op after a worker restart raised a bare KeyError instead of a readable message."""
    with pytest.raises(Unsupported, match='no longer running') as e:
        tools.SESSIONS['gone-session']
    assert isinstance(e.value, KeyError) and 'gone-session' in str(e.value)


def test_switch_uses_native_save_for_non_transfer_adapter(monkeypatch, tmp_path):
    """Switching away from an emulator state_transfer can't move uses its own save_state (RPCS3/Xenia/...)."""
    calls = []
    ad = SimpleNamespace(name='rpcs3', proc=None, stop_game=lambda: calls.append('stop'),
                         save_state=lambda: calls.append('save_state') or {'saved': True})
    monkeypatch.setattr(tools, 'SESSIONS', {'old': (ad, {'game_id': 'g', 'title': 'Stranglehold'})})
    monkeypatch.setattr(tools, 'state_transfer', lambda *a, **k: (_ for _ in ()).throw(AssertionError('must not run')))
    monkeypatch.setattr(tools, 'track_emulator', lambda *a, **k: None)
    ctx = SimpleNamespace(server=None, headers={}, config=SimpleNamespace(runtime=tmp_path), progress=lambda *a: None)
    snapshots = tools._close_previous_games(ctx)
    assert calls == ['save_state', 'stop']
    assert snapshots == [{'session_id': 'old', 'game_id': 'g', 'artifact': None, 'saved': True}]
    assert 'old' not in tools.SESSIONS


def test_switch_with_no_save_state_closes_without_blocking(monkeypatch, tmp_path):
    """An emulator with no save state at all (cxbx) is closed normally: its own saves persist, and refusing the switch
    would block every launch on this PC (operator report #2014)."""
    ad = SimpleNamespace(name='cxbx', proc=None, stop_game=lambda: None,
                         save_state=lambda: (_ for _ in ()).throw(Unsupported('cxbx does not support save_state')))
    monkeypatch.setattr(tools, 'SESSIONS', {'old': (ad, {'game_id': 'g', 'title': 'Dead or Alive Ultimate'})})
    monkeypatch.setattr(tools, 'state_transfer', lambda *a, **k: (_ for _ in ()).throw(AssertionError('must not run')))
    monkeypatch.setattr(tools, 'track_emulator', lambda *a, **k: None)
    ctx = SimpleNamespace(server=None, headers={}, config=SimpleNamespace(runtime=tmp_path), progress=lambda *a: None)
    snapshots = tools._close_previous_games(ctx)
    assert snapshots == [{'session_id': 'old', 'game_id': 'g', 'artifact': None, 'save_state': 'unsupported',
                          'reason': 'cxbx does not support save_state'}]
    assert 'old' not in tools.SESSIONS


def test_native_save_state_uploads_artifact_for_resume(monkeypatch, tmp_path):
    """A save_state that reports a path becomes a resumable checkpoint (sha256 artifact), like state_transfer."""
    import hashlib
    state = tmp_path / 'savestates' / 'game.sav'
    state.parent.mkdir()
    state.write_bytes(b'state-bytes')
    uploaded = []
    ad = SimpleNamespace(name='rpcs3', proc=None, stop_game=lambda: None,
                         save_state=lambda: {'saved': True, 'path': str(state)})
    monkeypatch.setattr(tools, 'SESSIONS', {'old': (ad, {'game_id': 'g'})})
    monkeypatch.setattr(tools, 'state_transfer', lambda *a, **k: (_ for _ in ()).throw(AssertionError('must not run')))
    monkeypatch.setattr(tools, 'track_emulator', lambda *a, **k: None)
    ctx = SimpleNamespace(server=None, headers={}, config=SimpleNamespace(runtime=tmp_path),
                          progress=lambda *a: None, artifact=lambda *a, **kw: uploaded.append((a[0], kw)))
    snapshots = tools._close_previous_games(ctx)
    assert snapshots[0]['artifact'] == hashlib.sha256(b'state-bytes').hexdigest()
    assert uploaded and uploaded[0][0] == 'game.sav'
    assert uploaded[0][1]['session'] == 'old'


class _Emu(SimpleNamespace):
    """A fake emulator with real pause/resume methods (gbox.tools looks them up on the type)."""
    def pause(self, **kw):
        self.events.append(('pause', self.sid, kw))
        if getattr(self, 'fail', False):
            raise RuntimeError('debugger not attached')
        self.paused = True

    def resume(self, **kw):
        self.events.append(('resume', self.sid, kw))
        self.paused = False

    def stop_game(self):
        self.events.append(('stop', self.sid, self.paused))


def test_warm_pool_games_stay_up_or_close_without_a_save(monkeypatch, tmp_path):
    """MercMode warm pool: keep_sessions stay up; a paused warm game is resumed (SIGCONT) and closed without a save."""
    events = []
    emu = {sid: _Emu(sid=sid, events=events, checkpoint_state='path', proc=None, paused=sid != 'old')
           for sid in ('cur', 'parked', 'warm', 'old')}
    emu['warm'].gbox_warm = True
    sessions = {sid: (ad, {'game_id': sid}) for sid, ad in emu.items()}
    monkeypatch.setattr(tools, 'SESSIONS', sessions)
    monkeypatch.setattr(tools, 'state_transfer', lambda inp, ctx: events.append(('save', inp.session_id)) or {'result': {'artifact': inp.session_id}})
    monkeypatch.setattr(tools, 'track_emulator', lambda *a, **k: None)
    ctx = SimpleNamespace(server=None, config=SimpleNamespace(runtime=tmp_path), progress=lambda *a: None)
    snapshots = tools._close_previous_games(ctx, keep=['', 'cur', 'parked'])
    assert set(sessions) == {'cur', 'parked'}
    assert ('save', 'warm') not in events and ('save', 'old') in events
    assert events.index(('resume', 'warm', {})) < events.index(('stop', 'warm', False))   # running again before the kill
    assert {'session_id': 'warm', 'game_id': 'warm', 'artifact': None, 'warm': True} in snapshots
    assert not [e for e in events if e[1] in ('cur', 'parked')]


def test_warm_launch_is_paused_once_running_or_reported_unpaused():
    events = []
    ok = _Emu(sid='a', events=events, paused=False)
    assert tools._park_warm(ok) == {'paused': True} and ok.gbox_warm is True and ok.paused
    broken = _Emu(sid='b', events=events, paused=False, fail=True)
    out = tools._park_warm(broken)
    assert out['paused'] is False and 'debugger' in out['reason'] and not getattr(broken, 'gbox_warm', False)
    assert tools._park_warm(SimpleNamespace(name='steam'))['paused'] is False


def test_session_op_warm_pause_and_resume_mark_the_game(monkeypatch):
    events = []
    ad = _Emu(sid='s', events=events, paused=False)
    monkeypatch.setattr(tools, 'SESSIONS', {'w1-s': (ad, {'game_id': 'g'})})
    out = tools.session_op(tools.SessionIn(session_id='w1-s', op='pause', args={'warm': True}), SimpleNamespace())
    assert events[-1] == ('pause', 's', {}) and ad.gbox_warm is True and out['result']['warm'] is True
    tools.session_op(tools.SessionIn(session_id='w1-s', op='resume', args={'warm': False}), SimpleNamespace())
    assert events[-1] == ('resume', 's', {}) and ad.gbox_warm is False
