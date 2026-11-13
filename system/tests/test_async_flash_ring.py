import json
import threading

import pytest

from gbox.mercs import async_flash_ring as A, grenade_ring as G
from test_re5_grenade_ring import ring_controller, N


@pytest.fixture(autouse=True)
def receipts(tmp_path, monkeypatch):
    monkeypatch.setattr(A, 'ROOT', tmp_path)


def scene():
    return {'player': {'ptr': 0x200000000, 'generation': 0x100000002, 'pos': [0, 0, 0], 'hp': 1000}}


def stats():
    return {'round_evidence_id': 'one', 'source_session_id': 'session', 'screen': 'playing', 'kills': 3}


DECISION = {'fire': True, 'reason': 'crowd', 'kind': 'flash'}


def test_pending_native_wait_does_not_block_combat_or_duplicate_submission():
    gate, entered = threading.Event(), threading.Event()
    flight, st, snap = A.Flight(), stats(), scene()

    def run(d, worker_stats, now, guard):
        entered.set()
        assert gate.wait(3)
        assert guard['allowed']() and guard['expected'] == (0x200000000, 0x100000002)
        worker_stats.update(rings_attempted=1, rings_deployed=1, ring_last_at=now)
        worker_stats['kills'] = 999  # never merge live progress from a worker
        return {'state': 'confirmed', 'kind': 'flash', 'detonated': 10}

    try:
        assert flight.submit(snap, st, DECISION, 10, run)['pending']
        assert entered.wait(3)
        job = flight.job
        assert flight.poll(snap, st)['pending']
        assert not flight.submit(snap, st, DECISION, 11, run)['fire']
        st['rings_attempted'] = 4  # another source's counter is preserved
        gate.set()
        assert job['done'].wait(3)
        assert flight.poll(snap, st)['fired']
        assert st['rings_attempted'] == 5 and st['rings_deployed'] == 1 and st['kills'] == 3
        assert flight.poll(snap, st) is None
        assert st['rings_attempted'] == 5
    finally:
        gate.set()


@pytest.mark.parametrize('change', ['round', 'life', 'operator', 'menu', 'close'])
def test_cancelled_receipt_survives_without_mutating_the_next_round(change):
    gate, entered = threading.Event(), threading.Event()
    flight, st, snap = A.Flight(), stats(), scene()

    def run(d, worker_stats, now, guard):
        entered.set()
        assert gate.wait(3)
        assert not guard['allowed']()
        worker_stats.update(rings_attempted=1, rings_deployed=1)
        return {'state': 'uncertain', 'kind': 'flash', 'detonated': 2}

    try:
        flight.submit(snap, st, DECISION, 10, run)
        assert entered.wait(3)
        job = flight.job
        if change == 'round': st['round_evidence_id'] = 'two'
        if change == 'life': snap['player']['generation'] += 1
        if change == 'operator': st['operator_control'] = True
        if change == 'close': flight.close()
        flight.observe(snap, st, playing=change != 'menu')
        gate.set()
        assert job['done'].wait(3)
        record = json.loads((A.ROOT / (job['record']['id'] + '.json')).read_text())
        assert record['identity'][0] == 'one' and record['receipt']['detonated'] == 2
        assert record['cancelled']
        st['operator_control'] = False
        assert not flight.poll(snap, st)['fire']
        assert 'rings_deployed' not in st
    finally:
        gate.set()


def test_native_cancel_before_attach_and_wrong_life_publish_nothing():
    ctl = ring_controller()
    with pytest.raises(N.Unavailable, match='cancelled'):
        ctl.grenade_ring('flash', allowed=lambda: False)
    with pytest.raises(N.Unavailable, match='lifecycle'):
        ctl.grenade_ring('flash', expected=(ctl.player, ctl.generation + 1))
    assert ctl.spawns == [] and ctl.calls == []


def test_native_cancel_after_two_blasts_stops_without_replaying():
    ctl = ring_controller()
    result = ctl.grenade_ring('flash', ripple_ms=0, allowed=lambda: len(ctl.spawns) < 3)
    assert result['state'] == 'uncertain' and result['detonated'] == 2
    assert len(ctl.spawns) == 3  # third was spawned, cancellation prevents its explosion request
    assert result['unconfirmed_projectile']['stage'] == 'spawn_returned'
    assert 'cancelled' in result['reason']


def test_busy_native_controller_refuses_without_queueing():
    ctl = ring_controller()
    gate, entered = threading.Event(), threading.Event()
    def hold():
        with ctl.lock:
            entered.set()
            gate.wait(3)
    thread = threading.Thread(target=hold)
    thread.start()
    try:
        assert entered.wait(3)
        with pytest.raises(N.Unavailable, match='not queued'):
            ctl.grenade_ring('flash', wait_for_lock=False)
        assert not ctl.spawns
    finally:
        gate.set()
        thread.join(3)


def test_background_path_refuses_explosives():
    ctl = ring_controller()
    result = G.fire(None, dict(DECISION, kind='hand'), {}, 10, ring=ctl, flash_only=True)
    assert result['state'] == 'refused' and not ctl.spawns


def test_control_keeps_inputs_held_during_background_flash(monkeypatch):
    ctl = ring_controller()
    ctl.async_flash_ring = True
    flight = A.Flight()
    monkeypatch.setattr(A, 'Flight', lambda: flight)
    monkeypatch.setattr(G, 'decide', lambda *a, **k: DECISION)
    step = G.control(None, {'map_id': '010018100CD46000'}, ring=ctl)
    holds, st = [], stats()
    out = step(scene(), st, 10, holds.append)
    assert out['pending'] and holds == []
    step.close()
    assert flight.job['done'].wait(3)


def test_evidence_failure_prevents_native_publication(monkeypatch):
    flight, st = A.Flight(), stats()
    calls = []
    def fail(*args):
        raise OSError('disk full')
    monkeypatch.setattr(A, '_write', fail)
    flight.submit(scene(), st, DECISION, 10, lambda *a: calls.append(a))
    assert flight.job['done'].wait(3)
    result = flight.poll(scene(), st)
    assert not result['fired'] and 'disk full' in result['receipt']['reason'] and not calls


@pytest.mark.parametrize('receipt', [{'kind':'flash'}, {'kind':'random','kinds':['flash']}])
def test_flash_completion_keeps_combat_and_engine_cancels_on_terminal(tmp_path, monkeypatch, receipt):
    from test_engine_round_rotation import run_sequence
    observed, closed = [], []
    def step(*args):
        return {'fired': True, 'receipt': {'state': 'confirmed', **receipt}}
    step.observe = lambda snap, stats, playing: observed.append(playing)
    step.close = lambda: closed.append(True)
    monkeypatch.setattr(G, 'control', lambda *a, **k: step)
    _, st, _, _ = run_sequence(tmp_path, monkeypatch,
        [{'where': 'playing', 'round': 1}, {'where': 'playing', 'round': 1}, {'where': 'dead', 'round': 1}])
    assert not st.get('ring_blast_backsteps') and 'ring_blast_until' not in st
    assert False in observed and closed == [True]


def test_scatter_uses_the_same_nonblocking_flight_and_keeps_separate_counters(monkeypatch):
    ctl = ring_controller()
    ctl.async_flash_ring = True
    flight = A.Flight()
    monkeypatch.setattr(A, 'Flight', lambda: flight)
    monkeypatch.setattr(G, 'decide', lambda *a, **k: {'fire':False,'reason':'ring cooldown'})
    monkeypatch.setattr(G, 'decide_scatter', lambda *a, **k:
                        {'fire':True,'reason':'nearby attack','count':2,'flash':True,'toward':[(2000,0)]})
    step = G.control(None, {'map_id':'010018100CD46000'}, ring=ctl)
    holds, st = [], stats()
    assert step(scene(), st, 10, holds.append)['pending']
    job = flight.job
    assert job['done'].wait(3)
    result = step(scene(), st, 10.5, holds.append)
    assert result['fired'] and result['receipt']['kinds'] == ['flash']
    assert st['scatters_fired'] == 1 and st['scatter_rounds'] == 2 and not st.get('rings_deployed')
    assert 'ring_last_at' not in st and st['scatter_last_at'] == 10 and holds == []
    assert job['record']['operation'] == 'scatter'


def test_scatter_checks_lifecycle_and_cancellation_before_publication():
    ctl = ring_controller()
    with pytest.raises(N.Unavailable, match='lifecycle'):
        ctl.grenade_scatter(expected=(ctl.player,ctl.generation+1))
    with pytest.raises(N.Unavailable, match='cancelled'):
        ctl.grenade_scatter(allowed=lambda:False)
    assert not ctl.spawns
    result = ctl.grenade_scatter(count=6,gap_ms=(0,0),allowed=lambda:len(ctl.spawns)<3)
    assert result['state'] == 'uncertain' and result['detonated'] == 2
    assert result['unconfirmed_projectile']['stage'] == 'spawn_returned'


def test_background_scatter_reanchors_clearance_as_player_moves():
    import math
    import struct
    ctl = ring_controller()
    original = ctl._ring_one
    positions = []
    def one(x,y,z,*a,**kw):
        px,py,pz = struct.unpack('<3f',ctl.rd(ctl.player+N.R.P_POS,12))
        positions.append((px,py,pz,x,y,z))
        out = original(x,y,z,*a,**kw)
        ctl.put(ctl.player+N.R.P_POS,struct.pack('<3f',px+400,py,pz))
        return out
    ctl._ring_one = one
    receipt = ctl.grenade_scatter(count=3,gap_ms=(0,0),allowed=lambda:True,toward=[(3000,0)])
    assert receipt['state'] == 'confirmed' and len(positions) == 3
    assert positions[-1][0] == positions[0][0]+800
    assert all(math.hypot(x-px,z-pz)>=N.flash_place_min_cm() for px,py,pz,x,y,z in positions)
