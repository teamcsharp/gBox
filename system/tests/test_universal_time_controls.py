"""Shared time controls: held directions, normal game inputs, native adapter delivery and safe releases."""
from types import SimpleNamespace

import pytest

from gbox import adapters, rewind, xinput
from gbox.config import Config, EmulatorConfig, HOST_OS


@pytest.mark.parametrize('back,forward', [('left', 'right'), ('down', 'up'), ('l2', 'r2'), ('Left', 'Right')])
def test_every_chord_alias_requires_select_and_repeats(back, forward):
    d = rewind.ChordDetector(.5)
    assert d.feed([{'key': forward, 'down': True}], 0) == []
    assert d.feed([{'key': 'select', 'down': True}], .1) == ['ff_start']
    assert d.feed([{'key': back, 'down': True}], .2) == ['rewind_step', 'ff_end']
    assert d.feed([], .7) == ['rewind_step']
    assert d.feed([{'key': back, 'down': False}], .8) == ['rewind_end', 'ff_start']
    assert d.feed([{'key': 'select', 'down': False}], .9) == ['ff_end']


def session():
    calls = []
    ad = SimpleNamespace(name='retroarch', supported={'rewind', 'fast_forward'}, rewind=lambda seconds: calls.append(seconds),
                         fast_forward=lambda on=None: calls.append(on))
    return rewind.SessionRewind('demo', ad, 'native', native_steps=True), calls


def test_streamed_chords_are_swallowed_but_ordinary_taps_and_player_two_survive():
    sr, _ = session()
    ordinary = [{'key': 'l2', 'down': True}, {'key': 'l2', 'down': False}, {'key': 'a', 'down': True},
                {'key': 'select', 'player': 2, 'down': True}, {'key': 'right', 'player': 2, 'down': True}]
    assert sr.feed(ordinary) == ordinary
    assert sr.sample() == (False,) * 5
    assert sr.feed([{'key': 'select', 'down': True}, {'key': 'right', 'down': True}]) == []
    assert sr.poll(0) == ['ff_start']
    assert sr.feed([{'key': 'select', 'down': False}]) == []
    assert sr.poll(.1) == ['ff_end']
    assert sr.feed([{'key': 'right', 'down': False}]) == []
    assert sr.feed([{'key': 'right', 'down': True}]) == [{'key': 'right', 'down': True}]


def test_joining_select_releases_already_held_game_key_without_reasserting_on_modifier_release():
    sr, _ = session()
    assert sr.feed([{'key': 'Left', 'down': True}]) == [{'key': 'Left', 'down': True}]
    assert sr.feed([{'key': 'Shift_R', 'down': True}]) == [{'key': 'Left', 'down': False}]
    assert sr.poll(0) == ['rewind_step']
    assert sr.feed([{'key': 'Shift_R', 'down': False}]) == []
    assert sr.poll(.1) == ['rewind_end']
    assert sr.feed([{'key': 'Left', 'down': False}]) == []
    assert sr.feed([{'key': 'Left', 'down': True}]) == [{'key': 'Left', 'down': True}]


def test_release_one_of_two_forward_aliases_does_not_end_other_held_alias():
    sr, _ = session()
    sr.feed([{'key': 'select'}, {'key': 'right'}, {'key': 'r2'}])
    assert sr.poll(0) == ['ff_start']
    sr.feed([{'key': 'right', 'down': False}])
    assert sr.poll(.1) == [] and sr.chord.ff_held
    sr.feed([{'key': 'r2', 'down': False}])
    assert sr.poll(.2) == ['ff_end']


def test_stopping_session_releases_held_speed_key():
    sr, calls = session()
    rewind.ACTIVE['demo'] = sr
    sr.poll(0, (True, False, False, False, True))
    sr.poll(4, (True, False, False, False, True))
    assert sr.ff_on and calls[-1] is True
    rewind.stop('demo')
    assert calls[-1] is False and not sr.ff_on


def test_xinput_dpad_aliases_and_reconnect_to_another_slot(monkeypatch):
    monkeypatch.setattr(xinput, 'load', lambda: object())
    live = {2: SimpleNamespace(buttons=rewind.BACK | 0x0001, lt=0, rt=0)}
    def read(_dll, slot, state):
        if slot not in live:
            return None
        g = live[slot]
        state.gamepad.buttons, state.gamepad.lt, state.gamepad.rt = g.buttons, g.lt, g.rt
        return state
    monkeypatch.setattr(xinput, 'read', read)
    pad = rewind.XInputPad()
    assert pad.read() == (True, False, False, False, True) and pad.slot == 2
    live.clear()
    assert pad.read() is None
    live[1] = SimpleNamespace(buttons=rewind.BACK | 0x0004, lt=0, rt=0)
    assert pad.read() == (True, False, False, True, False) and pad.slot == 1


def test_linux_dolphin_has_held_speed_key_and_actual_user_state_folder(tmp_path):
    ad = adapters.DolphinAdapter(Config(data_dir=tmp_path, runtime_dirs={HOST_OS: str(tmp_path / 'rt')}), 'gamecube')
    calls = []
    ad._xdo = lambda *args: calls.append(args)
    assert 'fast_forward' in ad.supported
    assert ad.fast_forward(True)['fast_forward'] == 'on'
    ad.fast_forward(True)
    assert calls == [('keydown', 'Tab')]
    assert ad.fast_forward(False)['fast_forward'] == 'off'
    assert calls[-1] == ('keyup', 'Tab')
    assert ad.state_dir() == tmp_path / 'rt' / 'dolphin-user' / 'StateSaves'
    ad.checkpoint_save()
    assert calls[-1] == ('keydown', 'Shift_L', 'keydown', 'F8', 'sleep', '0.1', 'keyup', 'F8', 'keyup', 'Shift_L')
    ad.checkpoint_load()
    assert calls[-1] == ('keydown', 'F8', 'sleep', '0.1', 'keyup', 'F8')
    ad.gameplay_demo_user = tmp_path / 'demo-user'
    assert ad.state_dir() == tmp_path / 'demo-user' / 'StateSaves'


def test_windows_dolphin_speed_keys_are_background_safe_and_failures_are_visible(tmp_path, monkeypatch):
    ad = adapters.DolphinWinAdapter(Config(data_dir=tmp_path), 'gamecube')
    ad.proc = SimpleNamespace(pid=42)
    calls = []
    def send(pid, events, **kw):
        calls.append((pid, events, kw))
        return {'sent': len(events)}
    monkeypatch.setattr(adapters, 'win_send_keys', send)
    ad.fast_forward(True)
    ad.fast_forward(False)
    assert all(c[2] == {'hidden_ok': True} for c in calls)
    monkeypatch.setattr(adapters, 'win_send_keys', lambda *a, **kw: {'sent': 0, 'stopped': True})
    sr = rewind.SessionRewind('dolphin', ad, 'checkpoint')
    sr._set_ff(True)
    assert not ad.ff_on and not sr.ff_on
    assert 'did not receive' in sr.status()['control_error']


@pytest.mark.parametrize('factory', [adapters.DolphinAdapter, adapters.DolphinWinAdapter])
def test_dolphin_demo_profile_configs_and_states_stay_private(tmp_path, monkeypatch, factory):
    cfg = Config(data_dir=tmp_path / 'data', runtime_dirs={HOST_OS: str(tmp_path / 'runtime')})
    ad = factory(cfg, 'gamecube')
    ad.gameplay_demo_user = tmp_path / 'private-demo'
    monkeypatch.setattr(ad, '_gecko_setup', lambda *a: None)
    exe = tmp_path / 'emulator' / 'Dolphin.exe'
    exe.parent.mkdir()
    monkeypatch.setattr(ad, '_exe', lambda: exe, raising=False)
    argv = ad._argv('private-copy.iso')
    assert 'Dolphin.General.HotkeysRequireFocus=False' in argv
    assert argv[argv.index('-u') + 1] == str(ad.gameplay_demo_user)
    assert ad.state_dir() == ad.gameplay_demo_user / 'StateSaves'
    assert (ad.gameplay_demo_user / 'Config' / 'Hotkeys.ini').is_file()
    assert not (exe.parent / 'User').exists() and not (exe.parent / 'portable.txt').exists()
    assert not (cfg.runtime / 'dolphin-user').exists()


@pytest.mark.parametrize('factory', [adapters.DolphinAdapter, adapters.DolphinWinAdapter])
def test_dolphin_psos_live_face_textures_use_full_checksumming_only_for_pso(tmp_path, monkeypatch, factory):
    ad = factory(Config(data_dir=tmp_path / 'data'), 'gamecube')
    ad.gameplay_demo_user = tmp_path / 'private-demo'
    monkeypatch.setattr(ad, '_gecko_setup', lambda *a: None)
    exe = tmp_path / 'emulator' / 'Dolphin.exe'
    exe.parent.mkdir()
    monkeypatch.setattr(ad, '_exe', lambda: exe, raising=False)
    ad.gecko_id = 'GPOE8P'
    assert 'GFX.Settings.SafeTextureCacheColorSamples=0' in ad._argv('pso.iso')
    ad.gecko_id = 'GGSEA4'
    assert not any(a.startswith('GFX.Settings.SafeTextureCacheColorSamples=') for a in ad._argv('other.iso'))


def test_checkpoint_recording_callback_reuses_verified_ring_file(tmp_path):
    from test_rewind import PathEmulator, Clock, ring_for
    clock, ad, captured = Clock(), PathEmulator(tmp_path / 'states'), []
    ad.gameplay_checkpoint = lambda path, kind: captured.append((path, kind, path.read_bytes()))
    ring = ring_for(tmp_path, ad, clock, interval_s=1)
    ad.frame = 9
    entry = ring.maybe_take(clock.tick(1))
    assert captured == [(entry['file'], 'checkpoint', b'frame=9')]
    ad.frame = 10
    ring.step_back()
    assert captured[-1] == (entry['file'], 'restore', b'frame=9')
    assert ad.saves == [9] and ad.loads == [9]  # no second save for capture
    ring.close()


@pytest.mark.parametrize('platform', ['nes', 'genesis', 'n64', 'psx', 'dreamcast', 'gamecube', 'wii', 'ps2', '3ds'])
def test_retroarch_platforms_all_use_one_chord_owner(tmp_path, monkeypatch, platform):
    cfg = Config(data_dir=tmp_path, runtime_dirs={HOST_OS: str(tmp_path / platform)})
    ad = adapters.RetroArchAdapter(EmulatorConfig(adapter='retroarch', executable='ra', core='core'), config=cfg, platform=platform)
    monkeypatch.setattr(adapters, 'HOST_OS', 'linux')
    monkeypatch.setattr(adapters, '_set_core_opts', lambda *a: None)
    text = ad._write_cfg().read_text()
    assert not ad.trigger_hotkeys
    assert 'input_rewind_axis = "nul"' in text and 'input_hold_fast_forward = "nul"' in text
    state = rewind.start('platform-' + platform, ad, cfg, threads=False)
    assert state['fast_forward_supported'] and state['fast_forward_ramp']
    if ad.rewind_on:
        assert state['native_steps']
    rewind.stop('platform-' + platform)


@pytest.mark.parametrize('factory', [lambda cfg: adapters.RPCS3Adapter(cfg), lambda cfg: adapters.YuzuAdapter(cfg),
                                   lambda cfg: adapters.SteamAdapter()])
def test_emulators_without_in_place_state_support_report_limit(tmp_path, factory):
    ad = factory(Config(data_dir=tmp_path))
    state = rewind.start('limited', ad, Config(data_dir=tmp_path), threads=False)
    assert state['rewind'] == 'unsupported' and state['reason']
    assert state['fast_forward_supported'] is False and state['fast_forward_reason']
    rewind.stop('limited')
