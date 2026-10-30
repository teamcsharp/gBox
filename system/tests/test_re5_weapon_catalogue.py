import struct
from types import SimpleNamespace

import pytest

from gbox.mercs.titles import re5_weapon_catalogue as C


def fixture(monkeypatch):
    data = bytearray(C.M.UPG_STRIDE * C.M.N_WEAPONS)
    for item in range(C.M.N_WEAPONS):
        struct.pack_into('<f', data, C.M.UPG_STRIDE * item + C.M.UPG_GROUP0, float('nan'))
    def damage(item, value):
        struct.pack_into('<f', data, C.M.UPG_STRIDE * item + C.M.UPG_GROUP0, value)
    damage(0x1B, 50000);damage(0x19, 5500);damage(0x08, 1);damage(0x0D, 1)
    inventory = [{'type': 1, 'item': 0x19, 'grid': 0, 'hand': True},
                 {'type': 1, 'item': 0x1B, 'grid': 5, 'hand': False},
                 {'type': 3, 'item': 0x02, 'grid': 6, 'hand': False}]
    monkeypatch.setattr(C.R, 'inventory', lambda ctl, player: inventory)
    reads = []
    def read(at, n):
        reads.append((at, n))
        assert (at, n) == (0x100000000 + C.M.UPG_TABLE, len(data))
        return data
    return SimpleNamespace(base=0x100000000, ready=lambda: (10, 20), rd=read), reads, damage


def test_all_weapons_including_absent_inventory_rank_by_live_modified_firepower(monkeypatch):
    ctl, reads, damage = fixture(monkeypatch)
    rows = C.choices(ctl)
    assert len(reads) == 1
    assert {r['item'] for r in rows} == set(C.re5_weapons.WEAPONS)
    assert [r['item'] for r in rows[:3]] == [0x1B, 0x0D, 0x19]
    assert rows[0]['in_inventory'] and not rows[0]['equipped']
    assert rows[2]['equipped'] and rows[2]['inventory_slots'] == [0]
    assert rows[1]['damage'] == 30000 and rows[1]['damage_basis'] == 'reference_base_damage'
    assert next(r for r in rows if r['item'] == 8)['damage'] is None
    absent = next(r for r in rows if r['item'] == 2)
    assert not absent['in_inventory'] and absent['damage'] is None
    assert next(r for r in rows if r['item'] == 0x36)['damage'] is None
    damage(0x19, 60000)
    assert C.choices(ctl)[0]['item'] == 0x19


def test_life_change_does_not_label_previous_players_inventory(monkeypatch):
    ctl, _, _ = fixture(monkeypatch)
    lives = iter([(10, 20), (10, 21)])
    ctl.ready = lambda: next(lives)
    with pytest.raises(RuntimeError, match='player changed'):
        C.choices(ctl)
