"""Native RE5 request and readback guards; no UI or inventory mutation."""
import struct

import pytest

from gbox.mercs.titles import re5_switch as R, re5_switch_equip as E
from tests.test_re5_switch import BASE, Guest


def fixture():
    g = Guest()
    main, gs, sp, p = (g.obj(name, size) for name, size in
                       [('sBioMain', 0x60000), ('cGameSys', 0x1000), ('sPlayer', 0x1000), ('uPl00', 0x8000)])
    g.q(BASE + R.S_MAIN, main)
    g.q(main + R.MAIN_GAMESYS, gs)
    g.i32(gs + R.GS_PHASE, R.PHASE_PLAYING)
    g.q(BASE + R.S_PLAYER, sp)
    g.q(sp + R.P_FIRST, p)
    g.put(p + R.P_HP, struct.pack('<h', 1000))
    g.q(p + E.GENERATION, 28)
    g.i32(p + E.COUNT, 64)
    table = g.alloc(64 * 8)
    g.q(p + E.TABLE, table)
    g.i32(p + E.REQUESTED, 1)
    g.i32(p + E.PRIORITY, -1)
    current = g.obj('cPlAct_wait')
    g.q(current + 0x10, p)
    g.q(p + E.CURRENT, current)
    action = g.alloc(0x100)
    g.q(table + 8 * E.ACTION_ID, action)
    g.q(action, BASE + E.ACTION_VTABLE)
    g.q(BASE + E.ACTION_VTABLE + 0x28, BASE + E.ACTION_DTI_GETTER)
    g.q(action + 0x10, p)
    g.q(action + 0x18, p)
    for i, (kind, grid, hand) in enumerate([(0x10b, 1, 1), (0x119, 3, 0)]):
        slot = p + R.P_INV + i * R.INV_SLOT
        obj = g.obj(f'uWp{kind & 0xff:02x}', 0x2000)
        g.q(obj + E.GENERATION, i + 1)
        for off, val in ((R.INV_ID, kind), (R.INV_GRID, grid), (R.INV_HAND, hand), (R.INV_ROUNDS, 99)):
            g.i32(slot + off, val)
        g.q(slot + R.INV_OBJ, obj)
    writes = []
    def write(a, data):
        writes.append((a, bytes(data)))
        g.put(a, data)
    return g, p, writes, write


def test_native_request_publishes_pending_last_and_readback_requires_native_hand():
    g, p, writes, write = fixture()
    request = E.Request(g, 'owned-re5', BASE, 3, 0x119)
    assert request.publish('owned-re5', write) == {'state': 'disabled'}
    assert writes == []
    assert request.publish('owned-re5', write, enabled=True)['state'] == 'requested'
    assert writes[-1] == (p + E.PENDING, b'\x01')
    assert set(a for a, _ in writes) <= {p + off for off in (E.REQUEST_GRID, E.PREVIOUS, E.RESET, E.REQUESTED, E.PENDING)}
    n = len(writes)
    assert request.observe('owned-re5')['state'] == 'waiting'
    g.i32(p + R.P_INV + R.INV_HAND, 0)
    g.i32(p + R.P_INV + R.INV_SLOT + R.INV_HAND, 1)
    g.put(p + E.PENDING, b'\x00')
    assert request.observe('owned-re5')['state'] == 'equipped'
    request.publish('owned-re5', write, enabled=True)
    assert len(writes) == n


@pytest.mark.parametrize('bad', ['busy', 'dead', 'context', 'signature', 'generation', 'motion'])
def test_native_request_refuses_missing_witness_without_writes(bad):
    g, p, writes, write = fixture()
    if bad == 'busy': g.put(p + E.PENDING, b'\x01')
    elif bad == 'dead': g.put(p + R.P_HP, bytes(2))
    elif bad == 'context': g.q(p + 0x3bd8, p)
    elif bad == 'signature': g.put(BASE + R.SIG_OFF, bytes(len(R.SIGNATURE)))
    elif bad == 'generation': g.q(p + E.GENERATION, 0)
    elif bad == 'motion': g.put(p + R.P_MOTION, b'\xff')
    with pytest.raises(E.Refused):
        E.Request(g, 'owned-re5', BASE, 3, 0x119)
    assert writes == []


def test_session_change_and_reused_player_are_not_equipped():
    g, p, writes, write = fixture()
    request = E.Request(g, 'owned-re5', BASE, 3, 0x119)
    assert request.publish('other', write, enabled=True)['state'] == 'refused'
    assert writes == []
    g.q(p + E.GENERATION, 29)
    assert request.observe('owned-re5')['state'] == 'unknown'
    assert request.publish('owned-re5', write, enabled=True)['state'] != 'requested'
    assert writes == []


def test_error_after_publication_is_ambiguous_and_never_replayed():
    g, p, writes, write = fixture()
    request = E.Request(g, 'owned-re5', BASE, 3, 0x119)
    def uncertain(a, data):
        write(a, data)
        if a == p + E.PENDING: raise OSError('readback raced consumer')
    assert request.publish('owned-re5', uncertain, enabled=True)['reason'] == 'publication_ambiguous'
    n = len(writes)
    request.publish('owned-re5', uncertain, enabled=True)
    assert len(writes) == n


def test_controller_requires_session_and_respects_operator_control():
    g, p, writes, write = fixture()
    g.wr = write
    stats = {}
    control = E.Controller(g, stats)
    assert control.select(3, 0x119)['reason'] == 'session_required'
    stats.update(source_session_id='owned-re5', operator_control=True)
    assert control.select(3, 0x119)['state'] == 'disabled'
    assert writes == []


def test_controller_timeout_does_not_reissue_the_request():
    g, p, writes, write = fixture()
    g.wr = write
    clock = [1.0]
    control = E.Controller(g, {'source_session_id': 'owned-re5'}, clock=lambda: clock[0])
    assert control.select(3, 0x119)['state'] == 'requested'
    clock[0] = 3
    assert control.tick()['reason'] == 'request_timeout'
    # The game is idle again but the earlier publication remains unconfirmed.
    g.put(p + E.PENDING, b'\x00')
    g.i32(p + E.REQUESTED, 1)
    n = len(writes)
    assert control.select(3, 0x119)['reason'] == 'previous_request_unconfirmed'
    assert len(writes) == n


class Bridge:
    def __init__(self): self.targets = []
    def tick(self): pass
    def select(self, grid, item): self.targets.append((grid, item))


@pytest.mark.parametrize('kind,grid,doing,key', [(0x10b, 1, 'rearm', 'dup'), (0x119, 3, 'raise', 'dleft'),
                                             (0x108, 5, 'flashbang', 'dright'), (0x10a, 7, 'mine', 'ddown')])
@pytest.mark.parametrize('held', [False, True])
def test_weapon_intents_use_native_requests_without_quick_slot_input(kind, grid, doing, key, held):
    bridge = Bridge()
    bot = R.Bot(stats={}, equip=bridge)
    bot.doing = doing
    snap = {'mercenaries_phase': R.PHASE_PLAYING, 'player': {'hp': 1000}, 'inventory': [{'grid': grid, 'id': kind}]}
    act = {'hold': (key,)} if held else {'tap': key}
    assert bot._native_equipment(act, snap) == {'hold': ()}
    assert bridge.targets == [(grid, kind)]


def test_prompt_and_dead_menu_directions_are_not_equipment_requests():
    bridge = Bridge()
    bot = R.Bot(stats={}, equip=bridge)
    snap = {'mercenaries_phase': R.PHASE_PLAYING, 'player': {'hp': 1000}, 'inventory': [{'grid': 1, 'id': 0x10b}]}
    for doing in ('prompt', 'dead', 'held'):
        bot.doing = doing
        assert bot._native_equipment({'tap': 'dup'}, snap) == {'tap': 'dup'}
    assert bridge.targets == []


def test_legacy_flash_directive_does_not_select_an_inventory_grenade():
    bridge = Bridge()
    bot = R.Bot(stats={}, equip=bridge)
    p = {'ptr': 123, 'hp': 1000}
    snap = {'inventory': [{'id': 0x108, 'item': 8, 'grid': 4, 'rounds': 99, 'hand': False}]}
    bot._emergency_flashbang_arm(p, snap, 1)
    assert bot._flashbang_throw(p, snap, 1) is None
    assert bridge.targets == []
    assert 'Native flash intervention required' in bot.stats['directive_status']
