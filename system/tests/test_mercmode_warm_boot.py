"""A warm launch must compile/boot before pause and cannot pause a taken-over game."""
from types import SimpleNamespace

import pytest

from gbox.mercs import warm_boot as W


class Emulator:
    def __init__(self):
        self.proc = SimpleNamespace(poll=lambda: None)
        self.generation = 0
        self.pauses = 0
        self.resumes = 0

    def pause(self):
        self.pauses += 1
        return {'paused': True}

    def resume(self):
        self.resumes += 1
        return {'paused': False}


def rig(**kwargs):
    ad, now, state, owned = Emulator(), [0.], [{'ready': False, 'screen': 'unknown'}], [True]
    prep = W.Preparation(ad, {}, lambda: owned[0], probe=lambda: state[0], clock=lambda: now[0], **kwargs)
    return prep, ad, now, state, owned


def test_guest_memory_and_loading_never_pause_until_stable_native_menu():
    p, ad, now, state, _ = rig()
    for at in (0, 10, 50):
        now[0] = at
        assert p.tick() and not ad.pauses and p.snapshot()['state'] == 'loading'
    state[0] = {'ready': True, 'screen': 'title', 'title': 'BLUS30491', 'token': 1}
    assert p.tick() and not ad.pauses
    now[0] += .5
    state[0] = {'ready': False, 'screen': 'loading'}
    assert p.tick()
    state[0] = {'ready': True, 'screen': 'main_menu', 'title': 'BLUS30491', 'token': 2}
    assert p.tick() and not ad.pauses
    now[0] += 1
    assert not p.tick() and ad.pauses == 1 and ad.gbox_warm
    assert p.snapshot() == {'state': 'ready', 'ready': True, 'paused': True, 'screen': 'main_menu',
                            'title': 'BLUS30491', 'source': 'native_menu', 'wait_s': 51.5}
    assert not p.tick() and ad.pauses == 1


@pytest.mark.parametrize('change', ['cancel', 'ownership', 'process', 'generation', 'exit'])
def test_stop_takeover_or_replacement_never_gets_a_late_pause(change):
    p, ad, now, state, owned = rig()
    state[0] = {'ready': True, 'screen': 'title'}
    assert p.tick()
    now[0] = 2
    if change == 'cancel': p.cancel('Player resumed the game.')
    elif change == 'ownership': owned[0] = False
    elif change == 'process': ad.proc = SimpleNamespace(poll=lambda: None)
    elif change == 'generation': ad.generation = 1
    else: ad.proc.poll = lambda: -9
    assert not p.tick() and not ad.pauses and p.snapshot()['state'] == 'cancelled'


def test_cancel_during_a_native_read_prevents_pause():
    p, ad, now, state, _ = rig()
    state[0] = {'ready': True, 'screen': 'title'}
    p.tick(); now[0] = 2
    def probe():
        p.cancel('Manual control')
        return state[0]
    p.probe = probe
    assert not p.tick() and not ad.pauses


def test_timeout_and_unconfirmed_pause_fail_without_claiming_ready():
    p, ad, now, state, _ = rig(timeout_s=2)
    now[0] = 2
    assert not p.tick() and not ad.pauses and p.snapshot()['state'] == 'failed'
    p, ad, now, state, _ = rig()
    state[0] = {'ready': True, 'screen': 'title'}
    ad.pause = lambda: {'paused': False}
    p.tick(); now[0] = 2
    assert not p.tick() and p.snapshot()['paused'] is False and p.snapshot()['state'] == 'failed'


def test_native_read_errors_retry_only_within_deadline():
    p, ad, now, state, _ = rig(timeout_s=2)
    p.probe = lambda: (_ for _ in ()).throw(OSError('guest page not mapped'))
    assert p.tick() and not ad.pauses
    now[0] = 2
    assert not p.tick() and not ad.pauses


@pytest.mark.parametrize('result', [{'paused': True}, {'state': 'PAUSED', 'processes': 1},
                                  {'state': 'PAUSED', 'threads': 2}, {'halted': True}])
def test_verified_pause_receipts_cover_existing_native_adapters(result):
    p, ad, now, state, _ = rig()
    state[0] = {'ready': True, 'screen': 'title'}
    ad.pause = lambda: result
    p.tick(); now[0] = 2
    assert not p.tick() and p.snapshot()['ready'] and ad.gbox_warm


def test_unsupported_platform_does_not_open_or_guess_memory(monkeypatch):
    from gbox import mercs_bot
    monkeypatch.setattr(mercs_bot, '_memory', lambda _: pytest.fail('must not open unsupported memory'))
    for game in ({'game_id': W.RE5_ID, 'platform': 'switch'}, {'game_id': 'unknown', 'platform': 'ps3'}):
        assert W.native_probe(Emulator(), game)()['unsupported']


def test_re5_menu_needs_exact_live_code_and_no_loading_unit(monkeypatch):
    from gbox import mercs_bot
    from gbox.mercs.titles import re5_ps3 as R
    data = dict(R.CONTINUE_CODE)
    memory = SimpleNamespace(rd=lambda address, size: data.get(address, b'\0' * size))
    monkeypatch.setattr(mercs_bot, '_memory', lambda _: memory)
    units = {'uIdStartUp00': 0x30001000}
    monkeypatch.setattr(R, 'ui_units', lambda *args: units)
    probe = W.native_probe(Emulator(), {'game_id': W.RE5_ID, 'platform': 'ps3'})
    assert probe()['ready']
    units['uIdNowLoading00'] = 0x30002000
    assert probe()['screen'] == 'loading' and not probe()['ready']
    units.clear(); units['uIdStartUp00'] = 0x30001000
    data.clear()
    assert not probe()['ready']


def test_re4_catalog_and_cached_signature_do_not_replace_live_build_proof(monkeypatch):
    from gbox import mercs_bot, re4_menus as R
    data = {}
    memory = SimpleNamespace(rd=lambda address, size: data.get(address, b'\0' * size), _re4_signed=True)
    monkeypatch.setattr(mercs_bot, '_memory', lambda _: memory)
    monkeypatch.setattr(R, 'screen', lambda _: {'where':'main_menu', 'title_routine':5, 'title_step':1})
    probe = W.native_probe(Emulator(), {'game_id': next(iter(W.RE4_IDS)), 'platform':'gamecube'})
    assert not probe()['ready']
    data.update(R.SIGNATURES)
    assert probe()['ready']
    data[next(iter(R.SIGNATURES))] = b'changed live build'
    assert not probe()['ready']


@pytest.mark.parametrize('kind', ['proc_mem', 'own_shm', 'adapter'])
def test_observer_closes_its_own_native_view_without_closing_adapter(monkeypatch, kind):
    from gbox import mercs_bot, re4_menus as R
    closed = []
    resource = SimpleNamespace(close=lambda: closed.append(kind))
    view = SimpleNamespace(rd=lambda address, size: R.SIGNATURES.get(address, b'\0' * size))
    if kind == 'proc_mem': view.f = resource
    elif kind == 'own_shm': view.ram = resource
    else: view.ad = resource
    monkeypatch.setattr(mercs_bot, '_memory', lambda _: view)
    monkeypatch.setattr(R, 'screen', lambda _: {'where':'main_menu'})
    probe = W.native_probe(Emulator(), {'game_id':next(iter(W.RE4_IDS)), 'platform':'gamecube'})
    assert probe()['ready']
    probe.close(); probe.close()
    assert closed == ([] if kind == 'adapter' else [kind])


def test_autoplay_start_cancels_before_driver_construction_or_thread_start(monkeypatch):
    from gbox import autoplay, tools
    p, ad, now, state, _ = rig()
    state[0] = {'ready': True, 'screen':'title'}
    p.tick(); now[0] = 2
    ad.gbox_warm_preparation = p
    monkeypatch.setattr(tools, 'SESSIONS', {'w-live':(ad, {'game_id':'exact'})})
    monkeypatch.setattr(tools, 'AUTOPLAY', {})
    priority = []
    monkeypatch.setattr(tools, '_warm_priority', lambda adapter, value: priority.append((adapter, value)))
    class DriverReached(Exception): pass
    def driver(*args, **kwargs):
        assert p.snapshot()['state']=='cancelled'
        assert priority == [(ad, 0)]
        assert not p.tick() and not ad.pauses  # no autoplay thread exists yet
        raise DriverReached()
    monkeypatch.setattr(autoplay, 'Driver', driver)
    ctx = SimpleNamespace(server='unused', headers={'authorization':'Bearer test'})
    with pytest.raises(DriverReached):
        tools.autoplay(tools.AutoplayIn(session_id='w-live',op='start'),ctx)


def test_autoplay_stop_cancels_before_releasing_input_owner(monkeypatch):
    from gbox import tools
    p, ad, now, state, _ = rig()
    state[0] = {'ready': True, 'screen':'title'}
    p.tick(); now[0] = 2
    ad.gbox_warm_preparation = p
    monkeypatch.setattr(tools, 'SESSIONS', {'w-live':(ad,{})})
    monkeypatch.setattr(tools, 'AUTOPLAY', {})
    monkeypatch.setattr(tools, '_warm_priority', lambda *a: pytest.fail('Stop must not promote a parked game'))
    def release(sid):
        assert sid=='w-live' and p.snapshot()['state']=='cancelled'
        assert not p.tick() and not ad.pauses
    monkeypatch.setattr(tools, '_release_all', release)
    assert tools.autoplay(tools.AutoplayIn(session_id='w-live',op='stop'),SimpleNamespace())['result']['stopped'] is False


def parked():
    p, ad, now, state, owned = rig()
    ad.gbox_warm_preparation = p
    state[0] = {'ready': True, 'screen':'title'}
    assert p.tick()
    now[0] = 2
    assert not p.tick() and ad.pauses == 1
    return p, ad, owned


def test_autoplay_start_after_preparation_pause_resumes_before_driver_setup(monkeypatch):
    from gbox import autoplay, tools
    p, ad, _ = parked()
    monkeypatch.setattr(tools, 'SESSIONS', {'w-live':(ad, {'game_id':'exact'})})
    monkeypatch.setattr(tools, 'AUTOPLAY', {})
    priority = []
    monkeypatch.setattr(tools, '_warm_priority', lambda adapter, value: priority.append((adapter, value)))
    class DriverReached(Exception): pass
    def driver(*args, **kwargs):
        assert ad.resumes == 1 and not ad.gbox_warm
        assert priority == [(ad, 0)]
        assert p.snapshot()['state'] == 'cancelled' and p.snapshot()['paused'] is False
        assert not p.tick() and ad.pauses == 1
        raise DriverReached()
    monkeypatch.setattr(autoplay, 'Driver', driver)
    ctx = SimpleNamespace(server='unused', headers={'authorization':'Bearer test'})
    with pytest.raises(DriverReached):
        tools.autoplay(tools.AutoplayIn(session_id='w-live',op='start'),ctx)


def test_start_waits_for_inflight_preparation_pause_then_resumes_it():
    import threading
    p, ad, now, state, _ = rig()
    ad.gbox_warm_preparation = p
    state[0] = {'ready': True, 'screen':'title'}
    assert p.tick()
    now[0] = 2
    pausing, finish_pause, starting, claimed = (threading.Event() for _ in range(4))
    errors = []
    def pause():
        ad.pauses += 1
        pausing.set()
        assert finish_pause.wait(2)
        return {'paused': True}
    ad.pause = pause
    def prepare():
        try: p.tick()
        except Exception as error: errors.append(error)
    def start():
        starting.set()
        try: W.autoplay_control(ad, 'start')
        except Exception as error: errors.append(error)
        finally: claimed.set()
    observer = threading.Thread(target=prepare)
    claimant = threading.Thread(target=start)
    observer.start()
    try:
        assert pausing.wait(2)
        claimant.start()
        assert starting.wait(2)
        assert not claimed.wait(.02)
    finally:
        finish_pause.set()
        observer.join(2)
        if claimant.ident is not None: claimant.join(2)
    assert not errors and claimed.is_set()
    assert ad.pauses == ad.resumes == 1 and not ad.gbox_warm
    assert p.snapshot()['paused'] is False and not p.tick()


@pytest.mark.parametrize('change', ['stop', 'manual_control', 'ownership', 'process', 'generation', 'exit'])
def test_autoplay_never_resumes_an_unowned_or_stopped_pause(change):
    p, ad, owned = parked()
    if change == 'manual_control': p.cancel('Manual pause now owns this session.')
    elif change == 'ownership': owned[0] = False
    elif change == 'process': ad.proc = SimpleNamespace(poll=lambda: None)
    elif change == 'generation': ad.generation += 1
    elif change == 'exit': ad.proc.poll = lambda: -9
    W.autoplay_control(ad, 'stop' if change == 'stop' else 'start')
    assert not ad.resumes and not p.tick() and ad.pauses == 1


def test_manually_paused_game_without_preparation_is_not_resumed():
    ad = Emulator()
    ad.gbox_warm = True
    W.autoplay_control(ad, 'start')
    assert not ad.resumes


def test_unconfirmed_warm_resume_blocks_setup_and_explicit_start_can_retry(monkeypatch):
    from gbox import autoplay, tools
    p, ad, _ = parked()
    monkeypatch.setattr(tools, 'SESSIONS', {'w-live':(ad, {'game_id':'exact'})})
    monkeypatch.setattr(tools, 'AUTOPLAY', {})
    monkeypatch.setattr(tools, '_warm_priority', lambda *a: pytest.fail('Unconfirmed resume must not promote a game'))
    monkeypatch.setattr(autoplay, 'Driver', lambda *a, **kw: pytest.fail('must not set up a paused bot'))
    monkeypatch.setattr(ad, 'resume', lambda: {'paused': True})
    ctx = SimpleNamespace(server='unused', headers={'authorization':'Bearer test'})
    with pytest.raises(RuntimeError, match='did not confirm'):
        tools.autoplay(tools.AutoplayIn(session_id='w-live',op='start'),ctx)
    assert p.snapshot()['state'] == 'failed' and p.snapshot()['paused'] is True
    monkeypatch.setattr(ad, 'resume', lambda: {'paused': False})
    W.autoplay_control(ad, 'start')
    assert not ad.gbox_warm and p.snapshot()['paused'] is False


@pytest.mark.parametrize('operation',['status','list'])
def test_read_only_autoplay_queries_do_not_cancel_preparation(monkeypatch, operation):
    from gbox import tools
    p, ad, _, _, _ = rig()
    ad.gbox_warm_preparation = p
    monkeypatch.setattr(tools, 'SESSIONS', {'w-live':(ad,{'game_id':'exact'})})
    monkeypatch.setattr(tools, 'AUTOPLAY', {})
    monkeypatch.setattr(tools, '_missions', lambda game: [])
    tools.autoplay(tools.AutoplayIn(session_id='w-live',op=operation),SimpleNamespace())
    assert p.snapshot()['state']=='loading' and not p.cancelled.is_set()


def test_live_ready_receipt_supersedes_successful_but_still_loading_launch():
    job = {'state': 'succeeded', 'output': {'detail': {'warm': {'state': 'loading', 'paused': False}}}}
    assert W.loading({}, job)
    session = {'detail': {'warm': {'state': 'ready', 'ready': True, 'paused': True}}}
    assert not W.loading(session, job) and W.receipt(session, job)['ready']
