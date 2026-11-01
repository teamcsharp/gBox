"""Native action publication, refusal, and hand attachment readback (no UI input)."""
import struct

import pytest

from gbox.mercs.titles import re6_switch as R, re6_switch_equip as E
from tests.test_re6_switch import BASE, round_guest


def fixture(kind=0x115, index=11):
    g = round_guest(enemies=())
    p = R.u64(g, R.u64(g, BASE + R.S_PLAYER) + R.P_FIRST)
    g.i32(p + E.GENERATION, 18)
    manager = p + E.MANAGER
    g.q(manager, BASE + E.MANAGER_VTABLE)
    g.q(manager + 8, p)
    g.i32(manager + 0x18, 64)
    table = g.alloc(64 * 8)
    g.q(manager + 0x28, table)
    g.put(manager + 0x30, struct.pack('<iiiB', 1, 0, -1, 0))
    g.q(BASE + E.MANAGER_VTABLE + 0x30, BASE + E.REQUEST_FUNCTION)
    g.q(BASE + E.MANAGER_VTABLE + 0x48, BASE + E.UPDATE_FUNCTION)
    active = g.obj('cPlAction_pl_act_wait')
    g.q(manager + 0x48, active)
    equip = g.obj('cPlAction_pl_act_weapon_change')
    g.q(table + 8 * E.REQUEST_ID, equip)
    g.put(equip + 0x10, struct.pack('<QQQ', p, p, 0))
    g.q(R.u64(g, equip) + 0x38, BASE + E.EQUIP_INIT)
    obj = g.obj('uWp1094')
    vt = R.u64(g, obj)
    fn = R.u64(g, vt + 0x28)
    w0, w1, _ = struct.unpack('<III', g.rd(fn, 12))
    imm = ((w0 >> 29) & 3) | (((w0 >> 5) & 0x7ffff) << 2)
    if imm & (1 << 20):
        imm -= 1 << 21
    dti = (fn & ~0xfff) + (imm << 12) + ((w1 >> 10) & 0xfff)
    g.i32(dti + 0x34, kind << 8)
    g.q(vt + 0x3a0, BASE + E.DIRECT_HAND_GETTER)
    g.q(vt + 0x390, BASE + E.HAND_ENABLE)
    g.q(obj + E.OWNER, p)
    g.i32(obj + E.GENERATION, 20)
    g.put(obj + E.HIDDEN, b'\x01\x00')
    slot = p + E.SLOTS
    g.put(slot + 8, struct.pack('<BBH', 1, index, kind))
    g.put(slot + 0xe, struct.pack('<h', 10))
    g.q(slot + 0x20, obj)
    writes = []
    def write(a, data):
        writes.append((a, bytes(data)))
        g.put(a, data)
    g.wr = write
    return g, p, obj, writes


def finish(g, p, obj, index):
    # Simulated game consumer: these cells are never assigned by the request.
    g.q(p + E.ACTIVE_OBJECT, obj)
    g.i32(p + E.ACTIVE_INDEX, index)
    g.put(obj + E.HIDDEN, bytes(2))
    g.put(p + E.MANAGER + 0x3c, b'\x00')


@pytest.mark.parametrize('kind,index', [(0x115, 11), (0x116, 12), (0x11b, 3)])
def test_request_publishes_native_action_and_waits_for_native_hand(kind, index):
    g, p, obj, writes = fixture(kind, index)
    result = E.request(g, BASE, p, kind, now=1)
    assert result['state'] == 'requested'
    assert writes[-1] == (p + E.MANAGER + 0x30, struct.pack('<iiiB', E.REQUEST_ID, 1, -1, 1))
    assert all(a not in (p + E.ACTIVE_OBJECT, p + E.ACTIVE_INDEX) and not p + E.SLOTS <= a < p + E.SLOTS + E.SLOT_COUNT * E.STRIDE for a, _ in writes)
    if kind in E.ITEMS:
        assert struct.unpack('<i', g.rd(p + E.PENDING_ITEM, 4))[0] == index
    else:
        assert struct.unpack('<i', g.rd(p + E.PENDING_GUN, 4))[0] == index
        assert struct.unpack('<i', g.rd(p + E.PENDING_ITEM, 4))[0] == -1
    n = len(writes)
    assert E.request(g, BASE, p, kind, now=1.1)['state'] == 'pending'
    assert len(writes) == n
    finish(g, p, obj, index)
    assert E.poll(g, now=1.2)['state'] == 'equipped'
    assert len(writes) == n


@pytest.mark.parametrize('bad', ['signature', 'dead', 'owner', 'generation', 'busy', 'priority', 'empty', 'hand_lifecycle'])
def test_missing_or_busy_native_witness_refuses_without_writes(bad):
    g, p, obj, writes = fixture()
    if bad == 'signature': g.put(BASE + R.SIG_OFF, bytes(len(R.SIGNATURE)))
    elif bad == 'dead': g.put(p + R.P_HP, bytes(2))
    elif bad == 'owner': g.q(obj + E.OWNER, p + 0x100)
    elif bad == 'generation': g.i32(obj + E.GENERATION, 0)
    elif bad == 'busy': g.put(p + E.MANAGER + 0x3c, b'\x01')
    elif bad == 'priority': g.i32(p + E.MANAGER + 0x38, 5)
    elif bad == 'empty': g.put(p + E.SLOTS + 0xe, bytes(2))
    elif bad == 'hand_lifecycle': g.q(R.u64(g, obj) + 0x390, BASE + 0x100)
    assert E.request(g, BASE, p, 0x115, now=1)['state'] == 'deferred'
    assert writes == []


def test_index_alone_does_not_confirm_native_attachment():
    g, p, obj, writes = fixture()
    E.request(g, BASE, p, 0x115, now=1)
    g.i32(p + E.ACTIVE_INDEX, 11)
    assert E.poll(g, now=1.1)['state'] == 'pending'
    g.q(p + E.ACTIVE_OBJECT, obj)
    assert E.poll(g, now=1.2)['state'] == 'pending'  # still disabled
    g.put(obj + E.HIDDEN, bytes(2))
    assert E.poll(g, now=1.3)['state'] == 'equipped'


def test_identity_change_during_preparation_never_publishes_or_reverts_other_life():
    g, p, obj, writes = fixture()
    write = g.wr
    def changed(a, data):
        write(a, data)
        g.i32(p + E.GENERATION, 19)
    g.wr = changed
    result = E.request(g, BASE, p, 0x115, now=1)
    assert result['state'] == 'deferred'
    assert len(writes) == 1 and writes[0][0] == p + E.PENDING_ITEM_SELECT
    assert g.rd(p + E.MANAGER + 0x3c, 1) == b'\x00'


def test_publication_readback_failure_does_not_replay_consumed_request():
    g, p, obj, writes = fixture()
    write = g.wr
    def consumed(a, data):
        write(a, data)
        if a == p + E.MANAGER + 0x30:
            finish(g, p, obj, 11)
            raise OSError('native consumer raced write verification')
    g.wr = consumed
    assert E.request(g, BASE, p, 0x115, now=1)['state'] == 'equipped'
    n = len(writes)
    assert E.request(g, BASE, p, 0x115, now=1.1)['state'] == 'equipped'
    assert len(writes) == n


def test_reused_object_generation_is_not_success():
    g, p, obj, writes = fixture()
    E.request(g, BASE, p, 0x115, now=1)
    finish(g, p, obj, 11)
    g.i32(obj + E.GENERATION, 21)
    assert E.poll(g, now=1.2) == {'state': 'unconfirmed', 'kind': 0x115, 'reason': 'request_identity_changed'}


def test_changed_snapshot_index_is_refused_without_writes():
    g, p, obj, writes = fixture()
    assert E.request(g, BASE, p, 0x115, expected_index=10)['reason'] == 'target_slot_changed'
    assert writes == []


@pytest.mark.parametrize('disabled', ['mercs_no_modifications', 'operator_control'])
def test_controller_respects_readonly_and_operator_control(disabled):
    g, p, obj, writes = fixture()
    stats = {}
    if disabled == 'mercs_no_modifications': g.mercs_no_modifications = True
    else: stats[disabled] = True
    control = E.Controller(g, stats)
    assert control.select({'ptr': p, 'nades': {0x115: (11, 20)}}, 11)['state'] == 'disabled'
    assert writes == []


def test_controller_does_not_repeat_uncertain_request_for_same_player_life():
    g, p, obj, writes = fixture()
    stats = {}
    control = E.Controller(g, stats)
    player = {'ptr': p, 'nades': {0x115: (11, 20)}}
    assert control.select(player, 11)['state'] == 'requested'
    g._re6_native_equip['deadline'] = 0
    assert control.tick()['state'] == 'unconfirmed'
    n = len(writes)
    assert control.select(player, 11)['reason'] == 'previous_request_unconfirmed'
    assert len(writes) == n


@pytest.mark.parametrize('finished', [False, True])
def test_other_ticket_never_acknowledges_or_blacklists_the_new_kind(finished):
    g, p, obj, writes = fixture()
    control = E.Controller(g, {})
    player = {'ptr': p, 'nades': {0x115: (11, 20)}, 'guns': {0x111: 1}}
    assert control.select(player, 11)['state'] == 'requested'
    if finished:
        finish(g, p, obj, 11)
    else:
        g._re6_native_equip['deadline'] = 0
    n = len(writes)
    result = control.select(player, 1)
    assert result['state'] == 'deferred' and result['kind'] == 0x111
    assert result['pending_kind'] == 0x115
    assert len(writes) == n
    assert (p, 18, 0x111) not in control.failed
    assert ((p, 18, 0x115) in control.failed) is not finished


def test_uncertain_kinds_remain_refused_when_another_kind_also_fails(monkeypatch):
    g, p, obj, writes = fixture()
    control = E.Controller(g, {})
    player = {'ptr': p, 'guns': {0x111: 1, 0x108: 2}}
    called = []
    def uncertain(memory, base, actor, kind, **kw):
        called.append(kind)
        return {'state': 'unconfirmed', 'kind': kind, 'reason': 'request_interrupted'}
    monkeypatch.setattr(E, 'request', uncertain)
    assert control.select(player, 1)['state'] == 'unconfirmed'
    assert control.select(player, 2)['state'] == 'unconfirmed'
    assert control.select(player, 1)['reason'] == 'previous_request_unconfirmed'
    assert called == [0x111, 0x108] and not writes


@pytest.mark.parametrize('block', [None, 'pending', 'ticket', 'busy_action', 'generation'])
def test_ordinary_cycle_readiness_is_read_only_and_requires_idle_native_context(block):
    g, p, obj, writes = fixture(0x11b, 3)
    control = E.Controller(g, {})
    player = {'ptr': p, 'generation': 18, 'guns': {0x11b: 3}}
    if block == 'pending': g.put(p + E.MANAGER + 0x3c, b'\x01')
    if block == 'ticket': g._re6_native_equip = {'kind': 0x11b}
    if block == 'busy_action': g.q(p + E.MANAGER + 0x48, g.obj('cPlAction_pl_act_attack_ex'))
    if block == 'generation': player['generation'] = 19
    assert control.cycle_ready(player, 3) is (block is None)
    assert writes == []


class NativeBridge:
    def __init__(self): self.targets = []
    def tick(self): pass
    def select(self, p, index):
        self.targets.append(index)
        kinds = [kind for kind, slot in (p.get('guns') or {}).items() if slot == index]
        kinds += [kind for kind, row in (p.get('nades') or {}).items() if row[0] == index]
        if index == R.BOMB_INDEX and (p.get('bomb') or {}).get('count', 0) > 0:
            kinds.append(0x116)
        return {'state': 'requested', 'kind': kinds[0] if kinds else None, 'index': index}


def test_live_bot_weapon_request_targets_native_slot_without_wheel(monkeypatch):
    bridge = NativeBridge()
    bot = R.Bot(stats={}, equip=bridge)
    monkeypatch.setattr(R, 'WANT_WEAPON', 4)
    monkeypatch.setattr(R, 'WANT_WEAPON_AT', 100)
    p = {'ptr': 123, 'pos': (0, 0, 0), 'guns': {0x107: 4}, 'equipped': 0}
    assert bot._weapon_switch(p, 1) == {'hold': ()}
    assert bridge.targets == [4]


def test_legacy_flash_directive_never_substitutes_an_inventory_throw():
    from gbox.mercs import directives as D
    bridge = NativeBridge()
    bot = R.Bot(stats={}, equip=bridge)
    p = {'ptr': 123, 'pos': (0, 0, 0), 'nades': {0x115: (11, 20)}, 'equipped': 0}
    D.apply_to_stats(bot.stats, D.post('native-flash-6107', 'flashbang'))
    assert bot._emergency_flashbang(p, {}, 1) is None
    assert bridge.targets == [] and bot.nade is None
    assert 'native flash intervention endpoint' in bot.stats['directive_status']


def test_live_bot_remote_item_request_has_no_wheel_input():
    bridge = NativeBridge()
    bot = R.Bot(stats={}, equip=bridge)
    bot.bomb_phase, bot.bomb_phase_at = 'equip', -100
    p = {'ptr': 123, 'pos': (0, 0, 0), 'equipped': 0, 'bomb': {'count': 20}}
    assert bot._bomb_press(0, 1, p=p) == {'hold': ()}
    assert bridge.targets == [R.BOMB_INDEX]


def test_live_bot_returns_to_a_magnum_without_cycling_items():
    bridge = NativeBridge()
    bot = R.Bot(stats={}, equip=bridge)
    p = {'ptr': 123, 'pos': (0, 0, 0), 'equipped': 8, 'guns': {0x11B: 3, 0x107: 4}}
    assert bot._held_item(p, [], lambda _: 0, {}, 1) == {'hold': ()}
    assert bridge.targets == [4]
