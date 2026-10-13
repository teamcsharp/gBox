"""#1504 "immediate pkill": Stop kills the emulator's process tree at once and answers without waiting on cleanup.

Before: RetroArch got QUIT + wait(5) (it never exited from it on Windows: median stop 5.5 s, exit code 1 = the kill
after the wait), and the checkpoint ring kept saving meanwhile; a save into the quitting RetroArch waited out its 12 s
deadline while rewind.stop() waited for it: 20.3 s and 24.7 s stops on the i9-NUC (PSO Ver. 2, Flycast)."""
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from gbox import adapters, rewind, ring_record, tools
from gbox.config import Config, EmulatorConfig
from gbox.server import create_app


def _sleeper():
    return subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])


@pytest.fixture
def quiet(monkeypatch):
    monkeypatch.setattr(tools, 'track_emulator', lambda *a, **k: None)


class SlowRewind:
    """A rewind whose close() waits on a checkpoint still in flight (the 12 s RetroArch save deadline)."""
    threads: list = []

    def __init__(self, seconds):
        self.seconds, self.closed = seconds, threading.Event()

    def close(self):
        time.sleep(self.seconds)
        self.closed.set()


def test_stop_does_not_wait_for_a_checkpoint_in_flight(monkeypatch, tmp_path, quiet):
    proc = SimpleNamespace(poll=lambda: 1)
    ad = SimpleNamespace(stop_game=lambda: {'returncode': 1}, proc=proc)
    monkeypatch.setitem(tools.SESSIONS, 'w-pso', (ad, {'game_id': 'pso'}))
    slow = SlowRewind(5.0)
    monkeypatch.setitem(rewind.ACTIVE, 'w-pso', slow)
    t = time.monotonic()
    out = tools.session_op(tools.SessionIn(session_id='w-pso', op='stop_game'), SimpleNamespace(config=Config(data_dir=tmp_path)))
    took = time.monotonic() - t
    assert out['ended'] is True and took < 2.0
    assert 'w-pso' not in tools.SESSIONS and 'w-pso' not in rewind.ACTIVE
    timings = out['result']['timings']
    assert timings['teardown_done'] is False and timings['teardown_s'] < 1.5
    assert slow.closed.wait(6)                                   # the ring is still closed, in the background


def test_ring_takes_no_checkpoint_once_stop_starts(monkeypatch, tmp_path, quiet):
    seen = []
    def stop_game():
        seen.append(rewind.mode('w-g'))                          # the kill happens with the ring already detached
        return {'returncode': 1}
    ad = SimpleNamespace(stop_game=stop_game, proc=SimpleNamespace(poll=lambda: 1))
    monkeypatch.setitem(tools.SESSIONS, 'w-g', (ad, {}))
    monkeypatch.setitem(rewind.ACTIVE, 'w-g', SlowRewind(0))
    tools.session_op(tools.SessionIn(session_id='w-g', op='stop_game'), SimpleNamespace(config=Config(data_dir=tmp_path)))
    assert seen == [None]


def test_failed_kill_keeps_the_session_and_its_rewind(monkeypatch, tmp_path, quiet):
    ad = SimpleNamespace(stop_game=lambda: {}, proc=SimpleNamespace(poll=lambda: None))
    sr = SlowRewind(0)
    monkeypatch.setitem(tools.SESSIONS, 'w-x', (ad, {}))
    monkeypatch.setitem(rewind.ACTIVE, 'w-x', sr)
    with pytest.raises(RuntimeError, match='still running'):
        tools.session_op(tools.SessionIn(session_id='w-x', op='stop_game'), SimpleNamespace(config=Config(data_dir=tmp_path)))
    assert 'w-x' in tools.SESSIONS and rewind.ACTIVE['w-x'] is sr and not sr.closed.is_set()


def test_save_only_when_asked_and_capped(monkeypatch, tmp_path, quiet):
    calls = []
    def save_state():
        calls.append('save')
        time.sleep(5)
        return {'slot': 0}
    ad = SimpleNamespace(stop_game=lambda: {'returncode': 1}, proc=SimpleNamespace(poll=lambda: 1), save_state=save_state)
    ctx = SimpleNamespace(config=Config(data_dir=tmp_path))
    monkeypatch.setitem(tools.SESSIONS, 'w-s', (ad, {}))
    out = tools.session_op(tools.SessionIn(session_id='w-s', op='stop_game'), ctx)
    assert calls == [] and 'save' not in out['result']                   # a plain Stop never saves
    monkeypatch.setitem(tools.SESSIONS, 'w-s', (ad, {}))
    t = time.monotonic()
    out = tools.session_op(tools.SessionIn(session_id='w-s', op='stop_game', args={'save': True, 'save_cap_s': 0.5}), ctx)
    assert time.monotonic() - t < 2.0 and calls == ['save']
    assert out['result']['save']['skipped'] is True and out['ended'] is True
    fast = SimpleNamespace(stop_game=lambda: {}, proc=None, save_state=lambda: {'slot': 3, 'path': 'x.state3'})
    monkeypatch.setitem(tools.SESSIONS, 'w-s', (fast, {}))
    out = tools.session_op(tools.SessionIn(session_id='w-s', op='stop_game', args={'save': True}), ctx)
    assert out['result']['save'] == {'slot': 3, 'path': 'x.state3'}


def test_gameplay_ring_finalising_never_holds_stop(monkeypatch, tmp_path, quiet):
    ad = SimpleNamespace(stop_game=lambda: {}, proc=None)
    monkeypatch.setitem(tools.SESSIONS, 'w-r', (ad, {}))
    monkeypatch.setattr(ring_record, 'stop', lambda sid: time.sleep(4))      # ffmpeg deaf to 'q': 8 s + 5 s before
    t = time.monotonic()
    tools.session_op(tools.SessionIn(session_id='w-r', op='stop_game'), SimpleNamespace(config=Config(data_dir=tmp_path)))
    assert time.monotonic() - t < 2.0


def test_retroarch_stop_kills_the_process_at_once(tmp_path):
    ad = adapters.RetroArchAdapter(EmulatorConfig(), Config(data_dir=tmp_path), 'dreamcast')
    ad.proc = _sleeper()                                     # deaf to RetroArch's UDP QUIT, like a Windows session
    try:
        t = time.monotonic()
        res = ad.stop_game()
        took = time.monotonic() - t
    finally:
        if ad.proc.poll() is None:
            ad.proc.kill()
    assert ad.proc.poll() is not None and res['returncode'] is not None
    assert took < 4.0                                        # was >= 5 s (QUIT + wait(5)) before the kill (~0.7 s here)


def test_retroarch_save_state_gives_up_when_the_emulator_is_gone(tmp_path):
    ad = adapters.RetroArchAdapter(EmulatorConfig(), Config(data_dir=tmp_path), 'dreamcast')
    ad.log_path = tmp_path / 'retroarch.log'
    ad.log_path.write_text('')
    ad.proc = SimpleNamespace(poll=lambda: 1)
    t = time.monotonic()
    with pytest.raises(RuntimeError, match='exited'):
        ad.save_state()
    assert time.monotonic() - t < 1.0                        # not the 12 s save deadline


def test_retroarch_session_flushes_in_game_saves(monkeypatch, tmp_path):
    exe = tmp_path / 'ra' / 'retroarch.exe'
    exe.parent.mkdir()
    monkeypatch.setattr(adapters.provision, 'retroarch_exe', lambda config: str(exe))   # no install / download
    from gbox import gamepads
    monkeypatch.setattr(gamepads, 'retroarch_driver', lambda exe: 'sdl2')
    ad = adapters.RetroArchAdapter(EmulatorConfig(), Config(data_dir=tmp_path), 'snes')
    assert 'autosave_interval = "5"' in ad._write_cfg().read_text()


def test_stop_is_claimed_first_and_the_session_shows_stopping(tmp_path):
    cfg = Config(data_dir=tmp_path)
    app = create_app(cfg)
    store = app.state.store
    store.put('session', 'pc-s', {'session_id': 'pc-s', 'state': 'running', 'started': 1})
    with TestClient(app, headers={'Authorization': 'Bearer ' + cfg.token()}) as client:
        client.post('/api/workers/register', json={'id': 'pc', 'name': 'PC', 'os': 'windows',
                                                    'tools': ['session_op', 'pso_mods']}).raise_for_status()
        polls = [client.post('/api/jobs', json={'tool': 'session_op', 'input': {'session_id': 'pc-s', 'op': 'query_runtime'}}).json()
                 for _ in range(3)]
        stop = client.post('/api/jobs', json={'tool': 'session_op', 'input': {'session_id': 'pc-s', 'op': 'stop_game'}}).json()
        row = next(s for s in client.get('/api/sessions').json() if s['session_id'] == 'pc-s')
        assert row['state'] == 'running' and row['stopping'] is True       # truthful record, visible intent
        assert client.post('/api/workers/pc/claim').json()['id'] == stop['id']
        assert client.post('/api/workers/pc/claim').json()['id'] == polls[0]['id']   # the rest keep their order
        store.put('job', stop['id'], store.get('job', stop['id']) | {'state': 'failed'})
        row = next(s for s in client.get('/api/sessions').json() if s['session_id'] == 'pc-s')
        assert 'stopping' not in row                                        # a failed stop: the game is still on
