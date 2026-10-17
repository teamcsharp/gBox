from types import SimpleNamespace

import pytest

from gbox import adapters, rewind, tools
from gbox.config import Config, EmulatorConfig


class Emulator:
    name = 'fake'
    supported = {'fast_forward'}

    def __init__(self):
        self.ff_on = False
        self.clears = 0

    def fast_forward(self, on=None):
        self.ff_on = not self.ff_on if on is None else on
        return {'on': self.ff_on}

    def normal_speed(self):
        self.clears += 1
        self.ff_on = False
        return {'on': False}


def test_manual_toggle_and_pad_ramp_share_state_and_off_blocks_held_chord(monkeypatch):
    ad = Emulator()
    sr = rewind.SessionRewind('test-speed', ad, 'native')
    monkeypatch.setitem(rewind.ACTIVE, sr.sid, sr)
    rewind.set_fast_forward(sr.sid, ad, True)
    sr.poll(0, (False, False, False))
    assert ad.ff_on  # pad polling must not fight a UI toggle
    sr.poll(4, (True, False, True))
    assert rewind.fast_forward_status(sr.sid, ad)['on']
    rewind.set_fast_forward(sr.sid, ad, recover=True)
    for n in range(300):
        sr.poll(5 + n / 60, (True, False, True))
    assert not ad.ff_on and ad.clears == 1
    assert not rewind.fast_forward_status(sr.sid, ad)['on']
    sr.poll(11, (False, False, False))
    sr.poll(12, (True, False, True))
    sr.poll(16, (True, False, True))
    assert ad.ff_on  # a new deliberate chord works


def test_live_channel_off_does_not_queue_or_toggle(monkeypatch):
    ad = Emulator()
    monkeypatch.setitem(tools.SESSIONS, 'speed-rpc', (ad, {}))
    assert tools.session_rpc('speed-rpc', 'normal_speed', {})['on'] is False
    assert tools.session_rpc('speed-rpc', 'normal_speed', {})['on'] is False
    assert ad.clears == 2 and not ad.ff_on


def test_fast_forward_rpc_is_allowed_and_audited():
    from pathlib import Path
    src = (Path(tools.__file__).parent / 'server.py').read_text()
    route = src[src.index('@app.post("/api/sessions/{sid}/rpc")'):src.index('@app.post("/api/sessions/{sid}/rpc/{rid}")')]
    assert '"normal_speed"' in route[route.index('if req.op not in'):route.index('raise HTTPException(422')]
    assert '"normal_speed"' in route[route.index('if req.op in ("reset"'):route.index('store.audit(')]


def test_status_failure_remains_unknown_without_breaking_other_controls():
    class Offline(Emulator):
        def fast_forward_status(self):
            raise RuntimeError('No reply')
    assert rewind.fast_forward_status('absent', Offline()) == {
        'supported': True, 'on': None, 'source': 'unknown', 'error': 'No reply'}


def retroarch(tmp_path):
    return adapters.RetroArchAdapter(EmulatorConfig(adapter='retroarch', executable='x', core='y'), config=Config(data_dir=tmp_path))


def test_retroarch_observed_status_and_explicit_off(tmp_path):
    ad = retroarch(tmp_path)
    actual = {'on': True}
    calls = []
    def cmd(text, **kwargs):
        calls.append(text)
        if text.startswith('SET_OPTION'):
            actual['on'] = False
            return 'OK'
        return 'fast_forward\t' + ('on' if actual['on'] else 'off')
    ad.cmd = cmd
    assert ad.fast_forward_status()['on']  # cached ff_on starts false
    assert ad.normal_speed() == {'supported': True, 'on': False, 'source': 'emulator'}
    assert 'FAST_FORWARD' not in calls


@pytest.mark.parametrize('paused', [False, True])
def test_legacy_recovery_clears_stale_toggle_and_preserves_pause(tmp_path, monkeypatch, paused):
    ad = retroarch(tmp_path)
    ad._ff_option = False
    state = {'paused': paused, 'fast': True}
    ad.query_runtime = lambda: {'state': 'PAUSED' if state['paused'] else 'PLAYING'}
    ad.pause = lambda: state.update(paused=True)
    ad.resume = lambda: state.update(paused=False)
    calls = []
    def cmd(text, **kwargs):
        calls.append(text)
        assert state['paused']  # RetroArch's paused hotkey edge clears FASTMOTION
        state['fast'] = False
    ad.cmd = cmd
    monkeypatch.setattr(adapters.time, 'sleep', lambda _: None)
    assert ad.normal_speed()['on'] is False
    assert not state['fast'] and state['paused'] == paused
    assert calls == ['FAST_FORWARD_HOLD\nGET_STATUS']


def test_dolphin_releases_even_with_stale_off_cache(tmp_path, monkeypatch):
    ad = adapters.DolphinWinAdapter(Config(data_dir=tmp_path), 'gamecube')
    ad.proc = SimpleNamespace(pid=123)
    calls = []
    monkeypatch.setattr(adapters, 'win_send_keys', lambda pid, events, **kw: calls.append((events, kw)) or {'sent': 1})
    assert ad.normal_speed()['on'] is False
    assert calls == [([{'key': ad.lane, 'down': False}], {'hidden_ok': True})]
    monkeypatch.setattr(adapters, 'win_send_keys', lambda *args, **kw: {'sent': 0})
    with pytest.raises(RuntimeError):
        ad.normal_speed()


def test_legacy_recovery_failure_restores_pause_and_does_not_claim_success(tmp_path, monkeypatch):
    ad = retroarch(tmp_path)
    ad._ff_option = False
    ad.ff_on = True
    state = {'paused': False}
    ad.query_runtime = lambda: {'state': 'PAUSED' if state['paused'] else 'PLAYING'}
    ad.pause = lambda: state.update(paused=True)
    ad.resume = lambda: state.update(paused=False)
    def fail(*args, **kwargs):
        raise RuntimeError('No reply')
    ad.cmd = fail
    with pytest.raises(RuntimeError):
        ad.normal_speed()
    assert not state['paused'] and ad.ff_on
