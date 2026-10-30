from types import SimpleNamespace

import pytest

from gbox.mercs import primary_weapon as P
from gbox.mercs.titles import re5_switch as R


def setup():
    ad = SimpleNamespace(_guest=lambda: (10, None))
    receipt = dict(state='confirmed', verified=True, item=25, weapon='Hydra', player=100,
                   player_generation=9, weapon_generation=15)
    P.install(ad, receipt, 10, clock=lambda: 1000)
    snap = dict(mercenaries_phase=1, player={'ptr': 100, 'generation': 9}, inventory=[
        {'type': 1, 'item': 25, 'grid': 0, 'id': 0x119, 'hand': True},
        {'type': 1, 'item': 11, 'grid': 1, 'id': 0x10B, 'hand': False},
        {'type': 1, 'item': 10, 'grid': 3, 'id': 0x10A, 'hand': False},
        {'type': 3, 'item': 4, 'grid': 5, 'hand': False}])
    return ad, snap


def test_three_minute_lock_then_match_preference_without_changing_telemetry_inventory():
    ad, snap = setup()
    snap['primary_weapon'] = P.snapshot(ad, snap, clock=lambda: 1179.9)
    locked = P.decision_snapshot(snap)
    assert locked['inventory'] == [snap['inventory'][0]]
    assert len(snap['inventory']) == 4 and locked['primary_weapon']['locked']
    assert P.snapshot(ad, snap, clock=lambda: 1120)['locked']
    snap['primary_weapon'] = P.snapshot(ad, snap, clock=lambda: 1180)
    later = P.decision_snapshot(snap)
    assert later['inventory'] == [snap['inventory'][0], snap['inventory'][3]]
    assert later['preferred_weapon']['item'] == 25 and not later['primary_weapon']['locked']


@pytest.mark.parametrize('change', ['pid', 'player', 'generation', 'phase'])
def test_selection_never_carries_into_a_different_process_or_player_life(change):
    ad, snap = setup()
    if change == 'pid': ad._guest = lambda: (11, None)
    elif change == 'phase': snap['mercenaries_phase'] = 3
    else: snap['player']['ptr' if change == 'player' else 'generation'] += 1
    assert P.snapshot(ad, snap, clock=lambda: 1010) is None
    assert ad._merc_primary_weapon is None


def test_quiescence_expires_and_never_releases_inputs_for_another_player():
    _, snap = setup()
    stats = {'native_weapon_pending': {'player':100, 'generation':9, 'until':20}}
    assert P.quiescing(stats, snap, clock=lambda:19)
    assert not P.quiescing(stats, snap, clock=lambda:20)
    snap['player']['generation'] = 10
    assert not P.quiescing(stats, snap, clock=lambda:19)


def test_handover_acknowledges_only_after_successful_input_release(monkeypatch):
    _, snap = setup()
    pending = {'player':100, 'generation':9, 'until':float('inf')}
    stats = {'native_weapon_pending': pending}
    def failed(_):
        raise OSError('input transport failed')
    with pytest.raises(OSError):
        P.release_for_handover(stats, snap, failed)
    assert not pending.get('released')
    released = []
    assert P.release_for_handover(stats, snap, lambda keys: released.append(keys))
    assert released == [set()] and pending['released']
    stats['operator_control'] = True
    assert not P.release_for_handover(stats, snap, lambda _: pytest.fail('operator owns input'))


def test_primary_grid_zero_returns_via_native_equip_without_a_dpad_or_inventory_key():
    _, snap = setup()
    snap['primary_weapon'] = {'item':25}
    snap['inventory'][0]['hand'] = False
    bot = R.Bot()
    calls=[]
    bot.native_equip = SimpleNamespace(select=lambda grid, item: calls.append((grid,item)))
    assert bot._gun_back(snap, 0) == {'hold': ()}
    assert calls == [(0,0x119)]


def test_live_driver_publishes_three_minute_lock_through_scalar_telemetry(monkeypatch):
    from gbox.mercs.titles import re5_switch_mods as M
    ad, snap = setup()
    P.install(ad, dict(state='confirmed', verified=True, item=25, weapon='Hydra', player=100,
                      player_generation=9, weapon_generation=15), 10)
    monkeypatch.setattr(M, 'maintain', lambda *a, **kw: {})
    monkeypatch.setattr(M, 'mine_settings', lambda *a: {})
    monkeypatch.setattr(M, 'preferred_weapon', lambda *a: None)
    stats = {}
    driver = R.RE5Switch()
    driver._mods(SimpleNamespace(adapter=ad), snap, True, stats)
    # This is the general telemetry publisher's scalar filter.
    sent = {k: v for k, v in stats.items() if isinstance(v, (int, float, str, bool))}
    assert sent['primary_weapon_item'] == 25 and sent['primary_weapon_name'] == 'Hydra'
    assert sent['primary_weapon_locked'] and 179 <= sent['primary_weapon_lock_remaining_s'] <= 180
    snap['mercenaries_phase'] = 3
    driver._mods(SimpleNamespace(adapter=ad), snap, False, stats)
    assert stats['primary_weapon_item'] == 0 and not stats['primary_weapon_locked']
    assert stats['primary_weapon_lock_remaining_s'] == 0
