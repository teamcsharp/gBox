"""Live bow requests must create native objects, never relabel carried slots."""
import struct
from types import SimpleNamespace

import pytest

from gbox.mercs.titles import re5_live_weapon as L, re5_controls as C, re5_ps3 as R
from test_re5_eggs import memory as egg_memory, ACTOR, VOLUME, MANAGER
from test_re5_mods import PLAYER, fresh_originals


def memory():
    ad, g, snap = egg_memory()
    ad.proc = SimpleNamespace(pid=1234)
    ad.generation = 0
    C.bind_adapter(g.orig, ad)
    words = {0x01714EE0: 0x016A4AB0, 0x0169CB3C: 0x009D67AC,
             0x009D67B8: 0xFFFFFFB4, 0x009D6854: 0xFFFFFFB4,
             0x018704A8: 0x01423AD0, 0x018704C4: 0x07010F00,
             0x01628A0C: 0x016EFCC8, 0x016EFCC8: 0x010F1FD4, 0x016EFCCC: 0x0171C590}
    for address, value in words.items():
        ad.u32(address, value)
    ad.put(L.NAME, b'uWp0f\0')
    snap['inventory'] = [{'slot': 0, 'id': 0x103, 'item': 3, 'type': 1, 'grid': 1,
                          'rounds': 10, 'cap': 30, 'hand': True}]
    C.publish(g.orig, 'bot', snap, True)
    ad.writes.clear()
    return ad, g, snap


def request(g):
    result = L.configure(g, 15)
    assert result['queued'] and not result['verified']
    assert result['live_weapon']['phase'] == 'pending'
    return g.orig['live_weapon']


def add_native(ad, snap, *, held=False, actor=True):
    item = {'slot': 5, 'id': L.ITEM, 'type': 1, 'item': 15, 'rounds': 1,
            'cap': 1, 'grid': 8, 'hand': held}
    at = PLAYER + R.P_INV + 5 * R.INV_SLOT
    ad.u32(at + 8, L.ITEM)
    ad.u32(at + 12, 1)
    ad.u32(at + 0x20, int(held))
    ad.put(at + 0x2D, b'\1')
    weapon = 0x31D00000
    ad.u32(at + 0x30, weapon if actor else 0)
    ad.u32(weapon, L.VTABLE)
    ad.u32(weapon + 0x111C, PLAYER)
    snap['inventory'] = [item]
    return item, weapon


def test_queue_is_not_completion_and_native_source_is_only_write():
    ad, g, snap = memory()
    request(g)
    before = ad.read_memory(PLAYER + R.P_INV, 24 * R.INV_SLOT + 4)
    row = L.prepare(g, snap)
    assert row['id'] == L.ITEM and row['converted']
    assert ad.writes == [(ACTOR + 0x1C36, 6)]
    assert ad.read_memory(PLAYER + R.P_INV, len(before)) == before
    assert g.u32(ACTOR) == 0x15BC398 and g.u32(VOLUME + 8) == 0x07021000
    assert L.status(g.orig)['phase'] == 'donor' and not L.status(g.orig)['completed']


@pytest.mark.parametrize('unsafe', ['owner', 'handle', 'volume', 'player', 'crowd', 'route', 'full'])
def test_invalid_or_unsafe_source_never_writes(unsafe):
    ad, g, snap = memory()
    request(g)
    if unsafe == 'owner': ad.u32(ACTOR + 0x111C, PLAYER)
    if unsafe == 'handle': ad.u32(ACTOR + 0x1110, 0)
    if unsafe == 'volume': ad.u32(VOLUME + 4, ACTOR + 4)
    if unsafe == 'player': snap['player']['ptr'] += 4
    if unsafe == 'crowd': snap['enemies'] = [{'hp': 800, 'pos': (80., 0., 0.)}]
    if unsafe == 'route': snap['nav'].route_avoiding_hazards = lambda *a: None
    if unsafe == 'full': snap['inventory'] = [{'id': 0x103, 'grid': i} for i in range(9)]
    assert L.prepare(g, snap) is None and not ad.writes


def test_constructor_build_mismatch_rejects_before_write():
    ad, g, snap = memory()
    request(g)
    ad.u32(0x009D67B8, 0)
    with pytest.raises(ValueError, match='factory'):
        L.prepare(g, snap)
    assert not ad.writes


def test_source_list_changed_before_mutation_is_not_written(monkeypatch):
    ad, g, snap = memory()
    request(g)
    real = L.rows
    count = [0]
    def changing(*args, **kwargs):
        count[0] += 1
        if count[0] == 2:
            ad.u32(MANAGER + 0x28, 0)
        return real(*args, **kwargs)
    monkeypatch.setattr(L, 'rows', changing)
    assert L.prepare(g, snap) is None and not ad.writes


def test_donor_becoming_owned_after_source_read_is_not_written():
    ad, g, snap = memory()
    request(g)
    read = g.rd
    def changing(address, size):
        result = read(address, size)
        if address == ACTOR + 0x1C36 and size == 6:
            ad.u32(ACTOR + 0x111C, PLAYER)
        return result
    g.rd = changing
    assert L.prepare(g, snap) is None and not ad.writes


def test_cancel_restores_only_our_unchanged_source():
    ad, g, snap = memory()
    request(g)
    before = g.rd(ACTOR + 0x1C36, 6)
    L.prepare(g, snap)
    result = L.configure(g, on=False)
    assert result['cancelled'] and result['verified']
    assert result['live_weapon']['phase'] == 'cancelled'
    assert g.rd(ACTOR + 0x1C36, 6) == before
    assert all(address == ACTOR + 0x1C36 and size == 6 for address, size in ad.writes)


@pytest.mark.parametrize('change', ['owner', 'reuse', 'count'])
def test_cancel_never_overwrites_reused_or_changed_source(change):
    ad, g, snap = memory()
    request(g)
    L.prepare(g, snap)
    if change == 'owner': ad.u32(ACTOR + 0x111C, PLAYER)
    if change == 'reuse': ad.u32(ACTOR + 0x1110, 999)
    if change == 'count': ad.u32(ACTOR + 0x1C38, 2)
    ad.writes.clear()
    L.configure(g, on=False)
    assert not ad.writes


def test_game_created_inventory_can_equip_before_actor_but_never_claims_complete():
    ad, g, snap = memory()
    request(g)
    item, _ = add_native(ad, snap, actor=False)
    assert L.inventory_item(g, PLAYER, [item]) is item
    assert L.native_item(g, PLAYER, [item]) is None
    L.observe(g, g.orig, snap, 'playing')
    assert L.status(g.orig)['phase'] == 'inventory_present'
    assert not L.status(g.orig)['native_created']
    assert not L.status(g.orig)['verified']


@pytest.mark.parametrize('wrong', ['model', 'owner', 'in_hand', 'player_root'])
def test_wrong_weapon_model_owner_or_equipped_flag_is_not_completion(wrong):
    ad, g, snap = memory()
    request(g)
    _, weapon = add_native(ad, snap, held=True)
    if wrong == 'model': ad.u32(weapon, 0x01632928)
    if wrong == 'owner': ad.u32(weapon + 0x111C, PLAYER + 4)
    if wrong == 'in_hand': ad.u32(PLAYER + R.P_INV + 5 * R.INV_SLOT + 0x20, 0)
    if wrong == 'player_root': ad.u32(g.u32(R.S_PLAYER) + 0x28, PLAYER + 4)
    L.observe(g, g.orig, snap, 'playing')
    assert not L.status(g.orig)['verified']


def test_only_native_equipped_bow_completes_and_changed_round_invalidates():
    ad, g, snap = memory()
    request(g)
    add_native(ad, snap, held=True)
    L.observe(g, g.orig, snap, 'playing')
    assert L.status(g.orig)['completed'] and g.orig['preferred_weapon']['item'] == 15
    L.observe(g, g.orig, snap, 'dead')
    assert L.status(g.orig)['phase'] == 'rejected' and not L.status(g.orig)['completed']


def test_stale_equipped_observation_does_not_report_current_completion():
    ad, g, snap = memory()
    request(g)
    add_native(ad, snap, held=True)
    L.observe(g, g.orig, snap, 'playing')
    g.orig['live_weapon']['verified_at'] -= 6.
    assert not L.status(g.orig)['verified']


def test_cancel_releases_only_the_preference_installed_by_this_request():
    ad, g, snap = memory()
    previous = {'item': 3, 'weapon': 'VZ61', 'target': (0, 0x103, 1)}
    g.orig['preferred_weapon'] = previous
    request(g)
    add_native(ad, snap, held=True)
    L.observe(g, g.orig, snap, 'playing')
    assert g.orig['preferred_weapon']['item'] == 15
    L.configure(g, on=False)
    assert g.orig['preferred_weapon'] == previous


def test_request_does_not_require_a_gun_already_available():
    _, g, snap = memory()
    C.publish(g.orig, 'bot', {**snap, 'inventory': []}, True)
    assert L.configure(g, 15)['queued']


def test_other_weapons_are_explicitly_unsupported_without_mutation():
    ad, g, _ = memory()
    result = L.configure(g, 3)
    assert result['live_weapon']['phase'] == 'unsupported' and not result['queued']
    assert not ad.writes and 'live_weapon' not in g.orig


def test_another_adapter_cannot_inherit_a_pending_live_request():
    class Adapter:
        pass
    first, second = Adapter(), Adapter()
    state = {}
    C.bind_adapter(state, first)
    state['live_weapon'] = {'active': True, 'phase': 'pending'}
    C.bind_adapter(state, second)
    assert 'live_weapon' not in state


def test_bot_uses_ordinary_inventory_for_a_native_nonquick_bow(tmp_path, monkeypatch):
    from test_re5_laserless_fire import scene
    m, snap = scene()
    bot = R.Bot(m, clock=lambda: 10., learn_dir=tmp_path)
    item = dict(snap['inventory'][0], grid=8, hand=False)
    snap.update(inventory=[item], enemies=[], prompt=None, recovery_active=False)
    bot._control_state = {'live_weapon': {'active': True, 'player': snap['player']['ptr'],
                                          'controller_owner': id(bot)}}
    monkeypatch.setattr(L, 'current_request', lambda state, cfg, ad: cfg['active'])
    monkeypatch.setattr(L, 'native_item', lambda *a, **k: None)
    monkeypatch.setattr(L, 'inventory_item', lambda *a: item)
    calls = []
    bot.inventory_live_weapon.tick = lambda *a: calls.append(a) or {'tap': 'triangle'}
    assert bot._live_weapon_action(snap['player'], snap, 10.) == {'tap': 'triangle'}
    assert len(calls) == 1 and calls[0][2] is item
    assert bot._control_state['live_weapon'].get('equipped') is not True


@pytest.mark.parametrize('change', ['process', 'pid', 'generation', 'exited'])
def test_process_restart_never_restores_old_guest_addresses(change):
    ad, g, snap = memory()
    cfg = request(g)
    L.prepare(g, snap)
    ad.writes.clear()
    if change == 'process': ad.proc = SimpleNamespace(pid=1234)
    if change == 'pid': ad.proc.pid += 1
    if change == 'generation': ad.generation += 1
    if change == 'exited': ad.proc.poll = lambda: 0
    C.bind_adapter(g.orig, ad)
    result = L.configure(g, on=False)
    assert not result['verified'] and not ad.writes
    assert cfg['donor'] and cfg['restoration_pending']
    assert not L.status(g.orig)['completed']


@pytest.mark.parametrize('change', ['owner', 'stale', 'expired'])
def test_changed_controller_or_expired_request_cannot_prepare(change):
    ad, g, snap = memory()
    cfg = request(g)
    if change == 'owner': g.orig['controller']['owner'] = 'other-bot'
    if change == 'stale': g.orig['controller']['seen'] -= C.FRESH_S + 1.
    if change == 'expired': cfg['expires'] = 0.
    assert L.prepare(g, snap) is None and not ad.writes
    assert not cfg['active'] and cfg['phase'] == 'rejected'


@pytest.mark.parametrize('unknown', ['empty_list', 'read_error', 'changing_identity', 'wrong_build'])
def test_unverified_restore_retains_donor_and_pending_status(unknown, monkeypatch):
    ad, g, snap = memory()
    cfg = request(g)
    L.prepare(g, snap)
    ad.writes.clear()
    read = g.rd
    if unknown == 'empty_list': monkeypatch.setattr(L, 'rows', lambda *a: [])
    if unknown == 'wrong_build': ad.u32(0x009D67B8, 0)
    if unknown in ('read_error', 'changing_identity'):
        calls = [0]
        def changed(address, size):
            if address == ACTOR:
                calls[0] += 1
                if unknown == 'read_error': raise OSError('unavailable')
                if calls[0] == 2: return struct.pack('>I', 0)
            return read(address, size)
        g.rd = changed
    result = L.configure(g, on=False)
    assert not result['verified'] and not ad.writes
    assert cfg['donor'] and cfg['restoration_pending'] and not cfg['restored']


@pytest.mark.parametrize('completed', [False, True])
def test_new_operator_preference_supersedes_live_request(completed):
    ad, g, snap = memory()
    cfg = request(g)
    add_native(ad, snap, held=True)
    if completed:
        L.observe(g, g.orig, snap, 'playing')
        assert L.status(g.orig)['verified']
    newer = {'item': 3, 'weapon': 'VZ61', 'target': (0, 0x103, 1)}
    g.orig['preferred_weapon'] = newer
    L.observe(g, g.orig, snap, 'playing')
    assert g.orig['preferred_weapon'] is newer and not cfg['active']
    assert cfg['phase'] == 'cancelled' and not L.status(g.orig)['completed']
    L.configure(g, on=False)
    assert g.orig['preferred_weapon'] is newer


def test_controller_stop_cancels_and_requests_source_cleanup(monkeypatch):
    ad, g, snap = memory()
    cfg = request(g)
    L.prepare(g, snap)
    calls = []
    monkeypatch.setattr(L, 'queue_supply', lambda adapter, **kw: calls.append((adapter, kw)))
    L.stop(g.orig, ad, 'another-bot')
    assert cfg['active'] and not calls
    L.stop(g.orig, ad, 'bot')
    assert not cfg['active'] and cfg['phase'] == 'cancelled' and cfg['restoration_pending']
    assert calls == [(ad, {'force': True})]
    assert not L.status(g.orig)['completed']
    assert L.restore(g, cfg) and not cfg['restoration_pending']


def test_stopped_controller_is_not_reported_as_equipped():
    ad, g, snap = memory()
    request(g)
    add_native(ad, snap, held=True)
    L.observe(g, g.orig, snap, 'playing')
    assert L.status(g.orig)['completed']
    C.publish(g.orig, 'bot', snap, False)
    assert not L.status(g.orig)['completed']


def test_cancel_during_inventory_read_suppresses_bot_equip_action(tmp_path, monkeypatch):
    from test_re5_laserless_fire import scene
    m, snap = scene()
    bot = R.Bot(m, clock=lambda: 10., learn_dir=tmp_path)
    item = dict(snap['inventory'][0], grid=8, hand=False)
    snap.update(inventory=[item], enemies=[], prompt=None, recovery_active=False)
    cfg = {'active': True, 'player': snap['player']['ptr'], 'controller_owner': id(bot)}
    bot._control_state = {'live_weapon': cfg}
    monkeypatch.setattr(L, 'current_request', lambda state, current, ad: current['active'])
    monkeypatch.setattr(L, 'native_item', lambda *a, **k: None)
    monkeypatch.setattr(L, 'inventory_item', lambda *a: item)
    def equip(*args):
        cfg['active'] = False
        return {'tap': 'triangle'}
    bot.inventory_live_weapon.tick = equip
    assert bot._live_weapon_action(snap['player'], snap, 10.) == {'hold': set()}


@pytest.mark.parametrize('mapping', ['pid', 'base', 'win_base', 'win_handle'])
@pytest.mark.parametrize('operation', ['prepare', 'restore'])
def test_resolved_guest_reassignment_never_writes_old_addresses(mapping, operation):
    ad, g, snap = memory()
    if mapping.startswith('win'):
        ad.base, ad._handle = 0x300000000, 123
    else:
        ad._mem = (4321, 0x300000000)
    cfg = request(g)
    if operation == 'restore': L.prepare(g, snap)
    ad.writes.clear()
    if mapping == 'pid': ad._mem = (4322, ad._mem[1])
    if mapping == 'base': ad._mem = (ad._mem[0], 0x500000000)
    if mapping == 'win_base': ad.base = 0x500000000
    if mapping == 'win_handle': ad._handle = 124
    if operation == 'prepare':
        assert L.prepare(g, snap) is None
    else:
        assert not L.restore(g, cfg) and cfg['restoration_pending'] and cfg['donor']
    assert not ad.writes


@pytest.mark.parametrize('operation', ['prepare', 'restore'])
def test_final_write_fence_refreshes_linux_guest_resolution(operation):
    ad, g, snap = memory()
    ad._mem = (4321, 0x300000000)
    cfg = request(g)
    if operation == 'restore': L.prepare(g, snap)
    ad.writes.clear()
    calls = []
    def rebound():
        calls.append(True)
        ad._mem = (4322, 0x500000000)
        return ad._mem
    ad._guest = rebound
    if operation == 'prepare':
        assert L.prepare(g, snap) is None
    else:
        assert not L.restore(g, cfg) and cfg['restoration_pending'] and cfg['donor']
    assert calls and not ad.writes


def test_guest_rebind_during_native_observation_is_not_completion():
    ad, g, snap = memory()
    ad._mem = (4321, 0x300000000)
    cfg = request(g)
    add_native(ad, snap, held=True)
    read = g.rd
    def rebound(address, size):
        if address == PLAYER + R.P_INV + 5 * R.INV_SLOT:
            ad._mem = (4322, 0x500000000)
        return read(address, size)
    g.rd = rebound
    L.observe(g, g.orig, snap, 'playing')
    assert not L.status(g.orig)['completed'] and cfg['phase'] == 'rejected'


def test_guest_rebind_during_consumed_donor_read_does_not_drop_receipt():
    ad, g, snap = memory()
    ad._mem = (4321, 0x300000000)
    cfg = request(g)
    L.prepare(g, snap)
    ad.u32(ACTOR + 0x111C, PLAYER)
    ad.writes.clear()
    read, reads = g.rd, [0]
    def rebound(address, size):
        if address == ACTOR:
            reads[0] += 1
            if reads[0] == 2:
                ad._mem = (4322, 0x500000000)
        return read(address, size)
    g.rd = rebound
    assert not L.restore(g, cfg) and cfg['restoration_pending'] and cfg['donor']
    assert not ad.writes
