"""Sniper-specific tuning and finite-ammo exceptions to operator selections."""
import struct
from types import SimpleNamespace

import pytest

from gbox.mercs.titles import re5_switch as R5, re6_switch as R6
from gbox.mercs.titles import re5_switch_mods as M5, re6_switch_mods as M6
from gbox.mercs.titles import re6_switch_weapon_native as W6, re6_switch_native as N6
from tests.test_re5_switch_mods import weapon_guest, Adapter, snap_of, scale
from tests.test_re6_switch import round_guest, weapon_table, Adapter as Adapter6, BASE as BASE6


@pytest.fixture(autouse=True)
def fresh_mods():
    M5.ORIG.clear(); M6.ORIG.clear()
    yield
    M5.ORIG.clear(); M6.ORIG.clear()


@pytest.mark.parametrize('item', sorted(M5.SNIPER_ITEMS))
def test_re5_sniper_30x_only_during_shot_and_owned_scale_tracks_weapon(item):
    guest = weapon_guest()
    ad = Adapter(guest)
    M5.run(ad, 'fire_rate', multiplier=5)
    snap = snap_of(guest, M5.MOTION_SHOT)
    snap['inventory'] = [{'item': item, 'hand': True}]
    M5.maintain(ad, snap)
    assert scale(guest) == 30
    snap['inventory'][0]['item'] = 0x0B
    M5.maintain(ad, snap)
    assert scale(guest) == 5
    snap['player']['motion'] = 26
    M5.maintain(ad, snap)
    assert scale(guest) == 1
    assert M5.run(ad, 'fire_rate', multiplier=1)['sniper_fire_rate_x'] == 1


def test_re6_all_verified_sniper_records_30x_and_off_restores_native_values():
    guest = round_guest()
    table = weapon_table(guest)
    ad = Adapter6(guest)
    def interval(index):
        return struct.unpack('<f', guest.rd(table + M6.FIRE_STRIDE * index + M6.FIRE_INTERVAL, 4))[0]
    result = M6.run(ad, 'fire_rate', multiplier=5)
    assert result['verified'] and result['sniper_fire_rate_x'] == 30
    for index in M6.SNIPER_RECORDS:
        assert interval(index) == pytest.approx(M6.FIRE_ORIGINAL[index] / 30)
    assert interval(7) == pytest.approx(M6.FIRE_ORIGINAL[7] / 5)
    assert interval(0x13) == M6.FIRE_ORIGINAL[0x13]
    M6.run(ad, 'fire_rate', multiplier=1)
    assert all(interval(i) == pytest.approx(original) for i, original in enumerate(M6.FIRE_ORIGINAL))


def test_re5_empty_primary_selects_existing_loaded_slot_without_creating_ammo():
    bot = R5.Bot(stats={}, clock=lambda: 10)
    selected = []
    bot.native_equip = SimpleNamespace(select=lambda *a: selected.append(a))
    bot._infinite_ammo = False
    empty = {'slot': 0, 'grid': 0, 'type': 1, 'item': 0x0B, 'id': 0x10B, 'hand': True, 'rounds': 0}
    loaded = {'slot': 1, 'grid': 5, 'type': 1, 'item': 4, 'id': 0x104, 'hand': False, 'rounds': 6}
    snap = {'inventory': [empty, loaded], 'primary_weapon': {'item': 0x0B, 'locked': True, 'usable': False}}
    bot._now = 10
    snap.update(player={'hp': 1000}, mercenaries_phase=1)
    intent = bot._gun_back(snap, 10)
    assert intent == {'tap': 'dright'}
    assert bot._native_equipment(intent, snap) == {'hold': ()}
    assert selected == [(5, 0x104)] and empty['rounds'] == 0
    bot._infinite_ammo = True
    selected.clear()
    assert bot._gun_back(snap, 11) is None and not selected


def test_re6_empty_pin_does_not_redirect_a_loaded_native_selection():
    bot = R6.Bot(stats={})
    selected = []
    bot.native_equip = SimpleNamespace(select=lambda p, i: selected.append(i) or
                                      {'state': 'equipped', 'kind': 0x104, 'index': i})
    bot._operator_primary = {'item': 7, 'locked': True, 'usable': False}
    p = {'guns': {0x107: 0, 0x104: 1}, 'gun_ammo': {0: 0, 1: 8}}
    assert bot._equip_keys(p, 1) == {'hold': ()}
    assert selected == [1]


def test_re6_verified_infinite_mode_preserves_pin_across_transient_zero_rounds():
    from test_re6_switch_equip import NativeBridge
    bridge = NativeBridge()
    bot = R6.Bot(stats={}, equip=bridge)
    bot._operator_primary = {'item': 7, 'locked': True, 'usable': True}
    bot._infinite_ammo = True
    p = {'ptr': 123, 'generation': 1, 'pos': (0, 0, 0), 'ammo': 0, 'equipped': 0,
         'guns': {0x107: 0, 0x104: 1}, 'gun_ammo': {0: 0, 1: 8}}
    assert bot._gun_index(p, preferred=1) == 0
    assert bot._weapon_switch(p, 0) is None
    assert bot._weapon_switch(p, 10) is None
    assert bridge.targets == [] and bot._empty_weapon is None
    bot._equip_keys(p, 1)
    assert bridge.targets == [0]
    bot._infinite_ammo = False
    assert bot._weapon_switch(p, 11) is None
    bot._weapon_switch(p, 15)
    assert bridge.targets == [0, 1]


def test_re6_catalogue_lists_all_named_weapons_with_honest_native_availability(monkeypatch):
    ctl = SimpleNamespace(ready=lambda: (123, 7))
    monkeypatch.setattr(R6, 'inventory_guns', lambda *_: {0x107: 0, 0x104: 1})
    monkeypatch.setattr(R6, 'inventory_state', lambda *_: (0, 7, None))
    rows = {row['item']: row for row in W6.choices(ctl)}
    assert set(rows) == set(M6.WEAPON_NAMES)
    assert rows[7]['available'] and rows[7]['equipped'] and rows[4]['in_inventory']
    assert not rows[9]['available'] and not rows[9]['in_inventory']
    assert 'creation' in rows[9]['reason']
    assert not rows[24]['available'] and 'lifecycle' in rows[24]['reason']


def test_re6_absent_weapon_never_publishes_a_selection_or_claims_creation(monkeypatch):
    ctl = SimpleNamespace(ready=lambda: (123, 7), base=BASE6, rd=lambda *_: R6.SIGNATURE)
    monkeypatch.setattr(R6, 'inventory_guns', lambda *_: {0x107: 0})
    monkeypatch.setattr(W6.E, 'request', lambda *_a, **_kw: pytest.fail('No native request for an absent object'))
    with pytest.raises(N6.Unavailable, match='not loaded'):
        W6.select(ctl, 9, expected=(123, 7), allowed=lambda: True)
