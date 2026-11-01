"""Measured emulated time, guarded queue ownership and uncertainty boundaries."""
import struct
import threading
from types import SimpleNamespace

import pytest

from gbox import pso_coop as C, pso_coop_native as N, pso_gc_live as G
from test_pso_coop import state
from test_pso_gc_live import RAM


class Clock:
    def __init__(self):
        self.now = 10.
    def __call__(self):
        return self.now


class ClockRAM(RAM):
    def __init__(self):
        super().__init__()
        self.tick, self.publications = 1000, 0
        p = 0x80DB62A0
        self.word(G.PLAYER + 4, p)
        self.word(p, 0x80430000)
        self.word(p + 0x18, G.VT_UPDATE - 12)
        self.put(p + 0x1C, struct.pack('>H', 1))
        self.put(G.ENTITY_TABLE, struct.pack('>3I', self.player, p, 0))
        self.put(N.READ_TICK, N.READ_TICK_CODE)
        self.word(N.EPISODE, 0)
        self.word(N.DIFFICULTY, 0)
        self._pso_coop_new_card = {'isolated': True, 'path': 'private', 'session_id': 'w-buddies'}
        self._pso_verified_player_slots = {0, 1}
        self._autoplay_speed_known = True
        self._autoplay_speed_changing = False
        self._autoplay_speed_lock = threading.Lock()
        self._pso_timing_epoch = 0
        self.autoplay_speed = 4
        self.observed = state(floor=1)
        self.observed['players'][1]['ptr'] = f'{self.player:08X}'
        self.observed['players'][2]['ptr'] = f'{p:08X}'

    def write_memory(self, address, data):
        super().write_memory(address, data)
        if address == G.QUEUE and data == struct.pack('>I', N.READ_TICK):
            self.publications += 1
            self.word(G.QUEUE + 36, self.tick)
            self.word(G.QUEUE, 0)


def setup_sampler():
    ram, clock = ClockRAM(), Clock()
    return ram, clock, N.SpeedSampler(ram, 'w-buddies', clock=clock)


@pytest.mark.parametrize('requested,actual', [(2, 2), (4, 4), (8, 8), (10, 10), (10, 1)])
def test_real_dispatcher_measures_clock_delta_not_requested_setting(requested, actual, monkeypatch):
    ram, clock, sampler = setup_sampler()
    ram.autoplay_speed = requested
    assert sampler.observe(ram.observed) is None
    ram.tick += int(actual * N.TICKS_PER_SECOND)
    clock.now += 1
    receipt = sampler.observe(ram.observed)
    assert receipt['verified'] and receipt['actual'] == actual
    assert receipt['requested'] == requested and receipt['source'].startswith('3OE2 native timebase')
    assert receipt['timing_epoch'] == 0 and ram.publications == 2
    ram.send_input_player = lambda *_: None
    monkeypatch.setattr(C.time, 'monotonic', clock)
    assert C.Inputs(ram, lambda: False).wall_learning_safe() is (requested == actual)


@pytest.mark.parametrize('fault', ['card', 'session', 'phase', 'mapping', 'clock_code', 'native_phase',
                                  'player_identity', 'pointer', 'native_floor', 'travelling', 'unknown', 'changing', 'paused'])
def test_native_clock_refuses_wrong_context_before_any_queue_publication(fault):
    ram, clock, sampler = setup_sampler()
    if fault == 'card': ram._pso_coop_new_card['isolated'] = False
    if fault == 'session': ram._pso_coop_new_card['session_id'] = 'other'
    if fault == 'phase': ram.observed['phase'] = 15
    if fault == 'mapping': ram._pso_verified_player_slots = {0}
    if fault == 'clock_code': ram.put(N.READ_TICK, bytes(8))
    if fault == 'native_phase': ram.word(G.PHASE, 15)
    if fault == 'player_identity': ram.put(0x80DB62A0 + 0x1C, b'\0\0')
    if fault == 'pointer': ram.observed['players'][2]['ptr'] = '80DCC000'
    if fault == 'native_floor': ram.word(G.FLOOR, 2)
    if fault == 'travelling': ram.word(N.TRAVELLING, 1)
    if fault == 'unknown': ram._autoplay_speed_known = False
    if fault == 'changing': ram._autoplay_speed_changing = True
    if fault == 'paused': ram._pso_timing_paused = True
    assert sampler.observe(ram.observed) is None
    assert ram.publications == 0 and not ram.writes and ram._autoplay_speed_observed is None


def test_actual_unsigned_timebase_wrap_is_accepted_but_reset_jump_is_not():
    ram, clock, sampler = setup_sampler()
    ram.tick = 0xFFFFFF00
    sampler.observe(ram.observed)
    ram.tick = (ram.tick + 4 * N.TICKS_PER_SECOND) & 0xFFFFFFFF
    clock.now += 1
    assert sampler.observe(ram.observed)['actual'] == 4
    ram.tick = 0
    clock.now += 1
    assert sampler.observe(ram.observed) is None
    assert ram._autoplay_speed_observed is None


@pytest.mark.parametrize('change', ['epoch', 'floor', 'rate', 'stale', 'changing', 'stopped'])
def test_readback_is_invalidated_at_session_boundaries(change):
    ram, clock, sampler = setup_sampler()
    sampler.observe(ram.observed)
    ram.tick += 4 * N.TICKS_PER_SECOND
    clock.now += 1
    assert sampler.observe(ram.observed)
    if change == 'epoch': ram._pso_timing_epoch += 1
    if change == 'floor': ram.observed['floor'] = 2; ram.word(G.FLOOR, 2)
    if change == 'rate': ram.autoplay_speed = 8
    if change == 'stale': clock.now += 3
    if change == 'changing': ram._autoplay_speed_changing = True
    if change == 'stopped': sampler.stopped = lambda: True
    assert sampler.observe(ram.observed) is None
    assert ram._autoplay_speed_observed is None


def test_measurement_latency_is_bounded_and_uncertainty_is_not_hidden():
    ram, clock, sampler = setup_sampler()
    ticks = iter([1000, 1000 + 4 * N.TICKS_PER_SECOND])
    def slow_native(_):
        start = clock.now
        clock.now += .12
        return next(ticks), start, clock.now
    sampler._native = slow_native
    sampler.observe(ram.observed)
    clock.now = 11.
    assert sampler.observe(ram.observed) is None, '24% timing uncertainty must not publish a verified rate'
    assert ram._autoplay_speed_observed is None


def test_native_failure_is_latched_without_automatic_retry():
    ram, clock, sampler = setup_sampler()
    calls = []
    def unknown(_):
        calls.append(True)
        raise RuntimeError('native batch outcome unknown')
    sampler._native = unknown
    assert sampler.observe(ram.observed) is None
    clock.now += 1
    assert sampler.observe(ram.observed) is None
    assert calls == [True] and 'unknown' in sampler.failure


def test_speed_sweep_lock_is_not_waited_on_or_bypassed():
    ram, clock, sampler = setup_sampler()
    with ram._autoplay_speed_lock:
        assert sampler.observe(ram.observed) is None
    assert ram.publications == 0 and not ram.writes


@pytest.mark.parametrize('fault', ['epoch', 'bounds'])
def test_wall_gate_rechecks_epoch_and_entire_timing_interval(monkeypatch, fault):
    ram, clock, sampler = setup_sampler()
    sampler.observe(ram.observed)
    ram.tick += 4 * N.TICKS_PER_SECOND
    clock.now += 1
    receipt = sampler.observe(ram.observed)
    assert receipt
    if fault == 'epoch': ram._pso_timing_epoch += 1
    if fault == 'bounds': receipt['lower'] = 3.7
    ram.send_input_player = lambda *_: None
    monkeypatch.setattr(C.time, 'monotonic', clock)
    assert not C.Inputs(ram, lambda: False).wall_learning_safe()


def test_epoch_change_after_native_call_discards_result():
    ram, clock, sampler = setup_sampler()
    original = sampler._native
    def changed(state):
        result = original(state)
        ram._pso_timing_epoch += 1
        return result
    sampler._native = changed
    assert sampler.observe(ram.observed) is None
    assert ram.publications == 1 and ram._autoplay_speed_observed is None


@pytest.mark.parametrize('after_completion', [False, True])
def test_portal_race_rebaselines_without_latching_or_repeating_a_pending_call(after_completion):
    ram, clock, sampler = setup_sampler()
    if after_completion:
        publish = ram.dbg.write
        def portal(address, data):
            publish(address, data)
            if address == G.QUEUE and data == struct.pack('>I', N.READ_TICK):
                ram.word(G.FLOOR, 2)
        ram.dbg.write = portal
    else:
        ram.word(G.FLOOR, 2)
    assert sampler.observe(ram.observed) is None
    assert sampler.failure is None and ram.publications == int(after_completion)
    ram.observed['floor'] = 2
    before = ram.publications
    assert sampler.observe(ram.observed) is None
    assert ram.publications == before, 'A context change does not bypass the one-second sampling interval'
    clock.now += 1
    assert sampler.observe(ram.observed) is None
    ram.tick += 4 * N.TICKS_PER_SECOND
    clock.now += 1
    assert sampler.observe(ram.observed)['actual'] == 4
    assert sampler.failure is None


def test_portal_after_preflight_but_before_queue_publication_is_transient(monkeypatch):
    ram, clock, sampler = setup_sampler()
    original = G.GC.call
    def just_before_call(actor, calls, **kwargs):
        ram.word(G.PHASE, 4)
        return original(actor, calls, **kwargs)
    monkeypatch.setattr(G.GC, 'call', just_before_call)
    assert sampler.observe(ram.observed) is None
    assert sampler.failure is None and ram.publications == 0


def test_same_adapter_gc_instances_cannot_overwrite_each_others_pending_queue():
    ram = RAM()
    first_entered, release_first, second_started, second_published = [threading.Event() for _ in range(4)]
    values, errors = {}, []
    first, second = G.GC(ram), G.GC(ram)
    first.hook()
    def publish(address, data):
        ram.write_memory(address, data)
        if address == G.QUEUE and len(data) == 4:
            fn = struct.unpack('>I', data)[0]
            if fn == 0x80100010:
                first_entered.set()
                assert release_first.wait(2)
            else:
                second_published.set()
            ram.word(G.QUEUE + 36, fn)
            ram.word(G.QUEUE, 0)
    first.publish = second.publish = publish
    def run(actor, fn, name):
        try:
            if name == 'second': second_started.set()
            values[name] = actor.call([(fn,)])
        except Exception as exc:
            errors.append(exc)
    a = threading.Thread(target=run, args=(first, 0x80100010, 'first'))
    b = threading.Thread(target=run, args=(second, 0x80100020, 'second'))
    a.start()
    try:
        assert first_entered.wait(2)
        b.start()
        assert second_started.wait(2)
        assert not second_published.wait(.05)
    finally:
        release_first.set()
        a.join(2)
        if b.ident is not None: b.join(2)
    assert not errors and values == {'first': [0x80100010], 'second': [0x80100020]}


def test_pending_queue_cannot_be_unhooked_after_timeout():
    ram = RAM()
    actor = G.GC(ram)
    actor.hook()
    ram.word(G.QUEUE, N.READ_TICK)
    with pytest.raises(RuntimeError, match='still pending'):
        actor.unhook()
    assert actor.u32(G.VT_UPDATE) == G.CAVE
