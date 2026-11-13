"""Automine templates must leave native throwing ammunition for the next round."""
import random
import struct

import pytest

from gbox.mercs.titles import re5_switch_mods as M
from tests.test_re5_switch_mods import Adapter
from tests.test_re5_switch_parity import parity_guest, block_at, put_block, ids


@pytest.fixture(autouse=True)
def fresh_state():
    M.ORIG.clear()
    yield
    M.ORIG.clear()


def test_automine_preserves_chriss_original_grenade_and_supplies_grenade_free_costumes():
    guest = parity_guest(player=False)
    ad = Adapter(guest)
    original = {i: ids(guest, i) for i in M.MERC_DESC}
    result = M.maintain(ad, {}, enabled=False, prepare_mines=True, clock=lambda: 0)
    assert result['verified'] and result['mine_supply']['grenade_supply_verified']
    for i in M.MERC_DESC:
        block = guest.rd(block_at(i), M.TEMPLATE_REC*M.TEMPLATE_RECS)
        assert M._quick_mine(block) and M._has_damage_grenade(block)
        assert all(w in ids(guest, i) for w in original[i] if w and w >> 8 != 2)
        occupied = [struct.unpack_from('<I', block, k*M.TEMPLATE_REC+M.REC_GRID)[0]
                    for k, item in enumerate(ids(guest, i)) if item and
                    struct.unpack_from('<I', block, k*M.TEMPLATE_REC+M.REC_GRID)[0] < 9]
        assert len(occupied) == len(set(occupied))
    assert ids(guest, 14)[1] == M.GRENADE_ID
    writes = len(ad.writes)
    assert M.maintain(ad, {}, enabled=False, prepare_mines=True, clock=lambda: 3)['writes'] == 0
    assert len(ad.writes) == writes


def test_full_inventory_only_replaces_ammo_when_infinite_ammo_is_enabled():
    guest = parity_guest()
    rows = {k: (0x102, -1, int(k == 3)) for k in range(9)}
    rows.update({0: (0x201, 50, 0), 1: (M.MINE_ID, 5, 0), 7: (M.SPRAY_ID, 2, 0)})
    put_block(guest, block_at(16), rows)
    original = guest.rd(block_at(16), M.TEMPLATE_REC*M.TEMPLATE_RECS)
    t = bytearray(original)
    assert not M._grenade_block(t, random.Random(0)) and t == original
    assert M._grenade_block(t, random.Random(0), replace_ammo=True)
    assert M._has_damage_grenade(t)
    assert t[M.TEMPLATE_REC:] == original[M.TEMPLATE_REC:]  # guns, mine, heal unchanged


def test_full_protected_inventory_reports_missing_grenade_without_deleting_guns():
    guest = parity_guest()
    rows = {k: (0x102, -1, int(k == 3)) for k in range(9)}
    rows[1] = (M.MINE_ID, 5, 0)
    put_block(guest, block_at(16), rows)
    before = guest.rd(block_at(16), M.TEMPLATE_REC*M.TEMPLATE_RECS)
    g = M.RE5Switch(Adapter(guest))
    g.state.update(mine_loadout=True, infinite_ammo=True)
    result = M.compose_templates(g)
    assert result['verified']  # mines are independently available
    assert not result['grenade_supply_verified'] and result['missing_grenade_blocks']
    after = guest.rd(block_at(16), len(before))
    assert after[:M.TEMPLATE_REC] == before[:M.TEMPLATE_REC]
    assert after[2*M.TEMPLATE_REC:] == before[2*M.TEMPLATE_REC:]  # only existing mine normalization


def test_round_seed_can_vary_added_damage_grenade_and_original_items_restore_exactly():
    guest = parity_guest(player=False)
    ad = Adapter(guest)
    before = {i: guest.rd(block_at(i), M.TEMPLATE_REC*M.TEMPLATE_RECS) for i in M.MERC_DESC}
    added = set()
    for seed in range(10):
        t = bytearray(before[16])
        assert M._grenade_block(t, random.Random(seed))
        added.update(struct.unpack_from('<I', t, k*M.TEMPLATE_REC)[0]
                     for k in range(M.TEMPLATE_RECS)
                     if struct.unpack_from('<I', t, k*M.TEMPLATE_REC)[0] in (0x106, 0x107))
    assert added == {0x106, 0x107}
    M.mines(M.RE5Switch(ad), 30, True)
    M.mines(M.RE5Switch(ad), 30, False)
    assert all(guest.rd(block_at(i), len(raw)) == raw for i, raw in before.items())


def test_overlapping_or_no_free_protected_records_are_never_blessed():
    guest = parity_guest()
    t = bytearray(guest.rd(block_at(16), M.TEMPLATE_REC*M.TEMPLATE_RECS))
    struct.pack_into('<Ii', t, M.REC_ID, 0x106, 5)
    struct.pack_into('<I', t, M.REC_GRID, 3)  # overlaps equipped gun
    original = bytes(t)
    assert not M._has_damage_grenade(t)
    assert not M._grenade_block(t, random.Random(0), replace_ammo=True)
    assert t == original
