"""No live game effects: exact quick-shot edges, native readback, durable UUIDs."""
import asyncio
import json
import struct
import threading
import uuid
from types import SimpleNamespace

import httpx
import pytest

from gbox.mercs.titles import re6_magnum_quick4 as Q
from gbox.mercs.titles import re6_switch_native as N
from gbox.mercs import interventions as I
from gbox.store import Store

IDLE = 'cPlAction_pl_act_wait'


class Game:
    def __init__(self, mode='normal'):
        self.now, self.at = 0., None
        self.edges, self.shots, self.mode = [], 0, mode

    def sleep(self, n):
        self.now += n

    def send(self, rows):
        assert [r['key'] for r in rows] == ['zl', 'zr']
        assert rows[0]['down'] == rows[1]['down']
        self.edges.append(rows[0]['down'])
        if rows[0]['down']:
            self.shots += 1
            self.at = self.now
            if self.mode == 'send_error':
                raise OSError('input response lost')

    def read(self):
        if self.at is None:
            return IDLE
        age = self.now - self.at
        if self.mode == 'lost_read' and self.shots == 2:
            raise OSError('native read lost')
        if self.mode == 'player_changed' and self.shots == 2:
            raise N.Unavailable('player changed')
        if self.mode == 'ignored' or age < .006:
            return IDLE
        if self.mode == 'stuck' or age < .03:
            return Q.QUICK
        if self.mode == 'interrupted':
            return 'cPlAction_pl_act_damage'
        return IDLE

    def run(self):
        return Q.sequence(self.read, self.send, clock=lambda: self.now, sleep=self.sleep)


def test_four_actual_distinct_actions_and_no_fifth_edge():
    game = Game()
    out = game.run()
    assert out['verified'] and out['state'] == 'confirmed'
    assert out['requested'] == out['completed'] == out['presses'] == 4
    assert game.edges == [True, False] * 4
    assert game.shots == 4


@pytest.mark.parametrize('mode,presses,completed', [
    ('ignored', 1, 0), ('stuck', 1, 0), ('interrupted', 1, 0),
    ('send_error', 1, 0), ('lost_read', 2, 1), ('player_changed', 2, 1)])
def test_ignored_interrupted_or_uncertain_input_never_repeats(mode, presses, completed):
    game = Game(mode)
    out = game.run()
    assert out['state'] == 'uncertain' and out['verified'] is False
    assert out['presses'] == presses and out['completed'] == completed
    assert game.edges == [True, False] * presses


def test_read_failure_before_any_press_changes_nothing():
    game = Game()
    def fail():
        raise N.Unavailable('operator took control')
    out = Q.sequence(fail, game.send, clock=lambda: game.now, sleep=game.sleep)
    assert out['state'] == 'failed' and out['presses'] == out['completed'] == 0
    assert not game.edges


def test_release_failure_cannot_be_success_or_trigger_another_shot():
    game = Game()
    def send(rows):
        game.send(rows)
        if rows[0]['down'] is False:
            raise OSError('release unknown')
    out = Q.sequence(game.read, send, clock=lambda: game.now, sleep=game.sleep)
    assert out['state'] == 'uncertain' and out['verified'] is False
    assert game.edges == [True, False, False]


def test_only_exact_re6_controller_with_solo_loaded_magnum_advertises(monkeypatch):
    assert Q.available(SimpleNamespace()) is False
    ctl = object.__new__(N.Controller)
    ctl.ad = SimpleNamespace(send_input=lambda rows: None)
    ctl.ready = lambda: (100, 2)
    monkeypatch.setattr(Q, 'loaded', lambda c, p: [(0x107, 3)])
    assert Q.available(ctl)
    ctl.ad.mercs_coop = True
    assert not Q.available(ctl)
    ctl.ad.mercs_coop = False
    monkeypatch.setattr(Q, 'loaded', lambda c, p: [])
    assert not Q.available(ctl)
    class OtherTitle(N.Controller):
        pass
    other = object.__new__(OtherTitle)
    assert not Q.available(other)


def test_loaded_magnums_require_four_rounds_and_never_invent_inventory():
    raw = bytearray(Q.R.SLOT_STRIDE * Q.R.N_SLOTS)
    for slot, kind, rounds in ((0, 0x107, 3), (1, 0x108, 4), (2, 0x103, 99)):
        at = slot * Q.R.SLOT_STRIDE
        raw[at + 8], raw[at + 9] = 1, slot
        struct.pack_into('<H', raw, at + 0xA, kind)
        struct.pack_into('<h', raw, at + 0xE, rounds)
    ctl = SimpleNamespace(rd=lambda at, n: bytes(raw))
    assert Q.loaded(ctl, 100) == [(0x108, 1)]


@pytest.mark.parametrize('equip_state', ['equipped', 'unconfirmed', 'deferred'])
def test_execute_calls_native_equip_once_before_counted_inputs(monkeypatch, equip_state):
    game, calls = Game(), []
    ctl = SimpleNamespace(ad=SimpleNamespace(send_input=game.send), base=1000, lock=threading.Lock(),
        ready=lambda: (100, 2), w=lambda at: 3 if at == 100 + Q.E.ACTIVE_INDEX else 8,
        q=lambda at: 500 if at == 100 + Q.E.ACTIVE_OBJECT else 100,
        rd=lambda at, n: Q.R.SIGNATURE if at == 1000 + Q.R.SIG_OFF else bytes(n))
    monkeypatch.setattr(Q, 'available', lambda c: True)
    monkeypatch.setattr(Q, 'loaded', lambda c, p: [(0x107, 3)])
    monkeypatch.setattr(Q.R, 'equipped_id', lambda c, p: 7)
    monkeypatch.setattr(Q.R, 'inventory_guns', lambda c, p: {0x107: 3})
    monkeypatch.setattr(Q.R, 'unit_action', lambda c, p: game.read())
    def equip(mem, base, player, kind, expected_index):
        calls.append((base, player, kind, expected_index))
        return {'state': equip_state, 'object': 500, 'player_generation': 2}
    monkeypatch.setattr(Q.E, 'request', equip)
    if equip_state != 'equipped':
        with pytest.raises(N.Uncertain):
            Q.execute(ctl, expected=(100, 2), allowed=lambda: True,
                      clock=lambda: game.now, sleep=game.sleep)
        assert not game.edges
    else:
        out = Q.execute(ctl, expected=(100, 2), allowed=lambda: True,
                        clock=lambda: game.now, sleep=game.sleep)
        assert out['verified'] and out['item'] == 7 and out['weapon'] == 'Lightning Hawk'
        assert game.edges == [True, False] * 4
    assert calls == [(1000, 100, 0x107, 3)]


def test_magnum_request_uuid_survives_restart_and_rejects_count_and_item(tmp_path):
    store = Store(tmp_path)
    now = [100.]
    q = I.Queue(store, lambda: now[0])
    try:
        q.claim('sid', 'life', [Q.OP])
        rid = str(uuid.uuid4())
        row = q.post('sid', Q.OP, rid, 'viewer')
        claim = q.claim('sid', 'life', [Q.OP])[0]
        assert q.post('sid', Q.OP, rid, 'viewer')['state'] == 'claimed'
        now[0] += 11
        fresh = I.Queue(store, lambda: now[0])
        assert fresh.claim('sid', 'life', [Q.OP]) == []
        assert fresh.post('sid', Q.OP, rid, 'viewer')['state'] == 'uncertain'
        for args in ({'count': 4}, {'item': 7}, {'repeat': True}):
            with pytest.raises(ValueError):
                q.post('sid', Q.OP, str(uuid.uuid4()), 'viewer', args)
        receipt = {'state': 'uncertain', 'requested': 4, 'completed': 2, 'verified': False}
        q.finish('sid', row['id'], claim['claim'], receipt)
        assert q.post('sid', Q.OP, rid, 'viewer')['result'] == receipt
    finally:
        store.db.close()


def test_mcp_preserves_magnum_action_uuid_and_rejects_custom_count(monkeypatch):
    pytest.importorskip('mcp')
    from mcp.client import Client
    from gbox.mcp_server import build
    seen, rid = [], str(uuid.uuid4())
    def handler(request):
        if request.url.path == '/api/registry':
            return httpx.Response(200, json={'tools': []})
        assert request.url.path == '/api/sessions/worker-game/interventions'
        body = json.loads(request.content)
        seen.append(body)
        return httpx.Response(200, json={'request': dict(body, state='queued')})
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda *a, **kw:
        original(*a, **kw, transport=httpx.MockTransport(handler)))
    async def check():
        async with Client(build('http://fixture', 'fixture')) as client:
            out = await client.call_tool('game_intervention', {'session_id': 'worker-game',
                'op': Q.OP, 'request_id': rid})
            assert not out.is_error
            assert json.loads(out.content[0].text)['request']['state'] == 'queued'
            invalid = await client.call_tool('game_intervention', {'session_id': 'worker-game',
                'op': Q.OP, 'request_id': rid, 'item': 7})
            assert invalid.is_error
    asyncio.run(check())
    assert seen == [{'op': Q.OP, 'request_id': rid}]

@pytest.mark.parametrize('change', ['none', 'player', 'round', 'operator', 'expired', 'no_ack'])
def test_worker_magnum_handover_is_exact_and_never_installs_primary_lock(monkeypatch, change):
    ad, stats, results, calls = SimpleNamespace(), {'round_evidence_id': 'round-a'}, [], []
    clock, life, running = [100.], [2], [True]
    ctl = SimpleNamespace(pid=123, identity=(123, 99), ready=lambda: (456, life[0]),
                          current_weapon=lambda: 7)
    monkeypatch.setattr(I, 'native_controller', lambda _: ctl)
    monkeypatch.setattr(Q, 'available', lambda c: True)
    monkeypatch.setattr(I.time, 'time', lambda: clock[0])
    monkeypatch.setattr(I.time, 'monotonic', lambda: clock[0])
    def execute(c, *, expected, allowed):
        assert expected == (456, 2) and allowed()
        assert stats['native_weapon_pending']['released']
        calls.append(expected)
        return {'state': 'confirmed', 'verified': True, 'requested': 4, 'completed': 4, 'presses': 4}
    monkeypatch.setattr(Q, 'execute', execute)
    def sleep(n):
        if n != .01:
            return
        assert stats['native_weapon_pending']['until'] == 109
        if change == 'no_ack':
            clock[0] += 1
            return
        stats['native_weapon_pending']['released'] = True
        if change == 'player': life[0] += 1
        if change == 'round': stats['round_evidence_id'] = 'round-b'
        if change == 'operator': stats['operator_control'] = True
        if change == 'expired': clock[0] += 20
    monkeypatch.setattr(I.time, 'sleep', sleep)
    def handler(request):
        body = json.loads(request.content)
        if request.url.path.endswith('/claim'):
            assert Q.OP in body['capabilities']
            assert body['options']['current_weapon'] == 7
            return httpx.Response(200, json={'requests': [{'id': 'request', 'claim': 'claim',
                'op': Q.OP, 'args': {}, 'expires': 110, 'epoch': body['epoch']}]})
        assert request.url.path.endswith('/results')
        assert 'native_weapon_pending' not in stats
        results.extend(body['results'])
        running[0] = False
        return httpx.Response(200, json={})
    original = httpx.Client
    monkeypatch.setattr(httpx, 'Client', lambda **kw: original(**kw, transport=httpx.MockTransport(handler)))
    I.worker_loop('sid', 'http://fixture', {}, ad, lambda: stats, lambda: running[0])
    assert len(results) == 1
    assert calls == ([(456, 2)] if change == 'none' else [])
    assert results[0]['result']['state'] == ('confirmed' if change == 'none' else 'failed')
    assert not hasattr(ad, '_merc_primary_weapon')


def test_magnum_queue_cannot_confirm_an_incomplete_or_fabricated_count(tmp_path):
    store = Store(tmp_path)
    q = I.Queue(store, lambda: 100.)
    try:
        q.claim('sid', 'life', [Q.OP])
        row = q.post('sid', Q.OP, str(uuid.uuid4()), 'viewer')
        claim = q.claim('sid', 'life', [Q.OP])[0]
        for result in ({}, {'requested': 4, 'completed': 3, 'presses': 4},
                       {'requested': 4, 'completed': 4, 'presses': 5},
                       {'requested': 4, 'completed': True, 'presses': 4}):
            with pytest.raises(ValueError, match='four'):
                q.finish('sid', row['id'], claim['claim'],
                    {'state': 'confirmed', 'verified': True, **result})
        out = q.finish('sid', row['id'], claim['claim'], {'state': 'confirmed', 'verified': True,
            'requested': 4, 'completed': 4, 'presses': 4})
        assert out['state'] == 'confirmed'
    finally:
        store.db.close()


def test_live_control_mcp_action_schema_has_no_count_or_item():
    from gbox import merc_live_controls as LC
    valid = {'session_id': 'pc-run', 'op': Q.OP, 'request_id': str(uuid.uuid4())}
    assert LC.validate_request(valid) == Q.OP
    for extra in ({'count': 4}, {'item': 7}, {'value': True}, {'control': 'mod.quick_attack'}):
        with pytest.raises(ValueError):
            LC.validate_request(valid | extra)

def test_real_native_publication_precedes_four_verified_actions(monkeypatch):
    from tests.test_re6_switch_equip import fixture, finish, BASE
    memory, player, hand, writes = fixture(0x107, 3)
    game = Game()
    ctl = SimpleNamespace(ad=SimpleNamespace(send_input=game.send, write_memory=memory.wr),
        base=BASE, lock=threading.Lock(), ready=lambda: (player, 18), rd=memory.rd,
        q=lambda at: struct.unpack('<Q', memory.rd(at, 8))[0],
        w=lambda at: struct.unpack('<I', memory.rd(at, 4))[0])
    monkeypatch.setattr(Q, 'available', lambda c: True)
    monkeypatch.setattr(Q.R, 'unit_action', lambda c, p: game.read())
    def sleep(n):
        game.sleep(n)
        if writes:
            finish(memory, player, hand, 3)
    out = Q.execute(ctl, expected=(player, 18), allowed=lambda: True,
                    clock=lambda: game.now, sleep=sleep)
    assert out['verified'] and out['completed'] == 4
    published = [(a, data) for a, data in writes if a == player + Q.E.MANAGER + 0x30]
    assert len(published) == 1
    assert struct.unpack('<iiiB', published[0][1]) == (Q.E.REQUEST_ID, 1, -1, 1)
    assert all(a not in (player + Q.E.ACTIVE_OBJECT, player + Q.E.ACTIVE_INDEX)
               and not player + Q.E.SLOTS <= a < player + Q.E.SLOTS + Q.E.STRIDE * Q.E.SLOT_COUNT
               for a, _ in writes)
    assert game.edges == [True, False] * 4


def test_re6_catalog_only_lists_loaded_native_weapons_and_actual_current(monkeypatch):
    from gbox.mercs.titles import re6_switch_weapon_native as W
    ctl = object.__new__(N.Controller)
    ctl.ready = lambda: (100, 2)
    monkeypatch.setattr(Q.R, 'inventory_guns', lambda c, p: {0x107: 3, 0x103: 0, 0x115: 11})
    assert {row['item'] for row in W.choices(ctl)} == {3, 7}
    monkeypatch.setattr(Q.R, 'inventory_state', lambda c, p: (3, 7, None))
    assert ctl.current_weapon() == 7
    monkeypatch.setattr(Q.R, 'inventory_state', lambda c, p: (11, 21, None))
    assert ctl.current_weapon() is None


def test_re6_operator_primary_prevents_bot_gun_swap_and_expires_with_life():
    from gbox.mercs import primary_weapon as P
    bot = Q.R.Bot(stats={})
    calls = []
    bot.native_equip = SimpleNamespace(select=lambda p, index: calls.append(index))
    p = {'ptr': 100, 'generation': 9, 'guns': {0x107: 3, 0x104: 1}, 'equipped': 3}
    bot._operator_primary = {'item': 7, 'locked': True}
    assert bot._gun_index(p, preferred=1) == 3
    bot._equip_keys(p, 1)
    bot._equip_keys(p, 11)
    assert calls == [3, 3]
    bot._operator_primary['locked'] = False
    bot._equip_keys(p, 1)
    bot._equip_keys(p, 11)
    assert calls == [3, 3, 3, 11]
    ad = SimpleNamespace(_guest=lambda: (10, None))
    P.install(ad, dict(state='confirmed', verified=True, item=7, weapon='Lightning Hawk',
        player=100, player_generation=9, weapon_generation=3), 10, clock=lambda: 0.)
    snap = {'mercenaries_phase': 1, 'player': p}
    assert P.snapshot(ad, snap, clock=lambda: 179.)['locked']
    assert not P.snapshot(ad, snap, clock=lambda: 180.)['locked']
    p['generation'] = 10
    assert P.snapshot(ad, snap, clock=lambda: 121.) is None