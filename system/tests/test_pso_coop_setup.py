import threading
from types import SimpleNamespace

import pytest

from gbox import adapters, pso_coop_setup as setup


def test_second_pad_is_independent_and_cannot_activate_existing_state_hotkeys():
    p1 = {v.lower() for v in adapters.DolphinAdapter.keys.values()}
    p2 = {v.lower() for v in setup.PAD2.values()}
    assert p1.isdisjoint(p2)
    assert p2.isdisjoint({'f1', 'f8', 'f10', 'f13', 'f14', 'f15', 'tab'})
    ini = setup.pad_ini(adapters.DolphinWinAdapter.PAD_INI_WIN, windows=True)
    second = ini.split('[GCPad2]')[1]
    assert 'DInput/0/Keyboard Mouse' in second and 'XInput/' not in second
    assert 'Buttons/A = `F6`' in second


def test_windows_raw_second_pad_letters_do_not_become_player_one_aliases(monkeypatch):
    calls = []
    monkeypatch.setattr(adapters, 'win_send_keys', lambda pid, rows, **kw: calls.extend(rows) or {'sent': len(rows)})
    ad = object.__new__(adapters.DolphinWinAdapter)
    ad.proc, ad.coop_players = SimpleNamespace(pid=7), 2
    ad.send_input_player([{'key': 'cleft', 'down': True}, {'key': 'a', 'down': True}], player=2)
    assert [row['key'] for row in calls] == ['B', 'F6']
    assert [adapters.PAD_KEYS[1].get(row['key'], row['key']) for row in calls] == ['B', 'F6']
    ad.send_input_player([{'key': 'lup', 'down': True}], player=1)
    assert calls[-1]['key'] == 'up'
    ad.send_input([{'key': 'lright', 'down': True}])
    assert calls[-1]['key'] == 'right'
    assert adapters.DolphinAdapter.keys['lright'] == 'Right'


def test_unconnected_second_pad_and_unknown_keys_are_rejected():
    ad = object.__new__(adapters.DolphinAdapter)
    with pytest.raises(ValueError, match='not connected'):
        ad.send_input_player([{'key': 'a'}], player=2)
    with pytest.raises(ValueError):
        setup.input_rows([{'key': 'arbitrary'}], 2)


def test_disc_preflight_rejects_wrong_build_before_card_creation(tmp_path):
    disc = tmp_path / 'pso.iso'
    disc.write_bytes(b'GPOE8P\0\x01')
    ctx = SimpleNamespace(config=SimpleNamespace(data_dir=tmp_path / 'data'), worker='i9', job_id='launch')
    ad = SimpleNamespace(name='dolphin', send_input_player=lambda *a, **kw: None)
    with pytest.raises(ValueError, match='revision 2'):
        setup.prepare(ad, {'platform': 'gamecube', 'game_id': '7a3692dc0cbc9b82'}, ctx, disc)
    assert not (tmp_path / 'data').exists()
    disc.write_bytes(b'GPOE8P\0\x02')
    setup.verify_disc(disc)


def test_private_card_is_persistent_and_existing_operator_card_is_untouched(tmp_path):
    operator = tmp_path / 'operator.raw'
    operator.write_bytes(b'keep this existing card')
    ctx = SimpleNamespace(config=SimpleNamespace(data_dir=tmp_path), worker='i9', job_id='launch')
    ad = SimpleNamespace(name='dolphin', send_input_player=lambda *a, **kw: None)
    game = {'platform': 'gamecube', 'game_id': '7a3692dc0cbc9b82'}
    first = setup.prepare(ad, game, ctx)
    from pathlib import Path
    card = Path(first['card'])
    before = card.read_bytes()
    second = setup.prepare(ad, game, ctx)
    assert first['new_card'] and not second['new_card']
    assert card.read_bytes() == before
    assert operator.read_bytes() == b'keep this existing card'
    assert ad.memory_card_context['closed'] and ad.memory_card_context['sandbox']
    assert setup.speed_options(ad)['Dolphin.Core.SIDevice1'] == '6'


def speed_adapter():
    return SimpleNamespace(_pso_coop_new_card={'isolated': True}, _autoplay_speed_known=True,
                           _autoplay_speed_lock=threading.Lock(), autoplay_speed=1.0,
                           normal_speed=lambda: None)


@pytest.mark.parametrize('adapter_type,operation', [
    (adapters.DolphinAdapter, 'load_state'),
    (adapters.DolphinAdapter, 'checkpoint_load'),
    (adapters.DolphinWinAdapter, 'load_state'),
    (adapters.DolphinWinAdapter, 'checkpoint_load'),
    (adapters.DolphinWinAdapter, 'reset'),
])
def test_restore_invalidates_speed_evidence_before_uncertain_input(adapter_type, operation):
    ad = object.__new__(adapter_type)
    ad._pso_timing_epoch = 4
    ad._autoplay_speed_observed = {'verified': True, 'actual': 2}

    def fail(*args):
        assert ad._pso_timing_epoch == 5
        assert ad._autoplay_speed_observed is None
        raise OSError('input result unknown')

    ad._xdo = ad._hotkey = fail
    with pytest.raises(OSError, match='unknown'):
        getattr(ad, operation)()
    assert ad._pso_timing_epoch == 5
    assert ad._autoplay_speed_observed is None


def test_jump_boot_invalidates_previous_timing_epoch(tmp_path):
    ad = object.__new__(adapters.DolphinAdapter)
    ad._autoplay_speed_observed = {'verified': True}
    ad.jump_boot(tmp_path / 'demo.s10')
    assert ad._pso_timing_epoch == 1
    assert ad._autoplay_speed_observed is None
    assert ad.jump_from == tmp_path / 'demo.s10'


@pytest.mark.parametrize('adapter_type', [adapters.DolphinAdapter, adapters.DolphinWinAdapter])
def test_pause_keeps_speed_sampling_blocked_until_resume_is_confirmed(adapter_type, monkeypatch):
    ad = object.__new__(adapter_type)
    ad.proc = SimpleNamespace(pid=7)
    ad._autoplay_speed_observed = {'verified': True}
    calls = []

    def halt(*args):
        assert ad._pso_timing_paused
        assert ad._autoplay_speed_observed is None
        calls.append('halt')
        return [100]

    def failed_resume(*args):
        raise OSError('resume result unknown')

    ad.dbg = SimpleNamespace(halt=halt, resume=failed_resume)
    monkeypatch.setattr(adapters, 'win_suspend_emulation', halt)
    monkeypatch.setattr(adapters, 'win_resume_threads', failed_resume)
    ad.pause()
    assert calls == ['halt'] and ad._pso_timing_epoch == 1
    with pytest.raises(OSError, match='unknown'):
        ad.resume()
    assert ad._pso_timing_paused and ad._pso_timing_epoch == 2
    ad.dbg.resume = lambda: {'state': 'PLAYING'}
    monkeypatch.setattr(adapters, 'win_resume_threads', lambda tids: len(tids))
    ad.resume()
    assert not ad._pso_timing_paused and ad._pso_timing_epoch == 3
    assert ad._autoplay_speed_observed is None


def test_speed_requests_are_bounded_and_report_delivery_not_achievement():
    ad, presses = speed_adapter(), []
    def press(direction):
        assert ad._autoplay_speed_changing
        presses.append(direction)
    result = setup.set_speed(ad, 2, press)
    assert presses == ['Increase'] * 10
    assert result['input_delivered'] and not result['achieved_verified']
    assert ad.autoplay_speed == 2
    assert not ad._autoplay_speed_changing
    setup.set_speed(ad, 1, presses.append)
    assert presses[-10:] == ['Decrease'] * 10
    for bad in (True, 0, 3, 11, float('nan')):
        with pytest.raises(ValueError):
            setup.set_speed(ad, bad, presses.append)


def test_interrupted_rate_change_cannot_silently_drift():
    ad = speed_adapter()
    def interrupted(_):
        raise OSError('lost input')
    with pytest.raises(OSError):
        setup.set_speed(ad, 4, interrupted)
    assert not ad._autoplay_speed_known and ad.autoplay_speed == 1
    assert not ad._autoplay_speed_changing
    with pytest.raises(RuntimeError, match='relaunch'):
        setup.set_speed(ad, 1, lambda _: None)
