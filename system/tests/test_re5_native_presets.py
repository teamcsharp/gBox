"""Replay actual BLUS30491 descriptor/record bytes, without running a game.

The native selector uses descriptor10 for original Chris, and the constructor
copies all twelve records. Former bases started six records before this block.
The retained executable's bytes are evidence for this build, not a clean-save
or factory-image claim. Live constructor acceptance is a separate check.
"""
import json
import struct
from pathlib import Path

import pytest

from gbox import re5_mods_tool as T
from gbox.mercs.titles import re5_eggs as E, re5_mines as N
from test_re5_mods import FakeRE5, fresh_originals  # noqa: F401
from test_re5_mines import template_game


DATA = json.loads((Path(__file__).parent/'fixtures'/'re5-native-presets.json').read_text(encoding='utf-8-sig'))
CHRIS = 0x0172C790


def recorded_game():
    raw = template_game()
    for row in DATA['descriptor_records']:
        raw.put(int(row['address'], 16), struct.pack('>2I', int(row['pointer'], 16), row['count']))
    for address, block in DATA['blocks'].items():
        records = block['retained_inventory_records']
        assert len(records) == 12 and all(len(row) == 11 for row in records)
        raw.put(int(address, 16), b''.join(struct.pack('>11I', *row) for row in records))
    return raw, T.RE5(raw)


def rows(g, address):
    data = g.rd(address, T.TEMPLATE_BLOCK)
    return [struct.unpack_from('>11I', data, i*T.TEMPLATE_REC) for i in range(12)]


def same_items_except_grid(before, after, excluded=()):
    def identities(values):
        return sorted(r[:5]+r[6:] for r in values if r[0] not in (0, *excluded))
    assert identities(before) == identities(after)
    occupied = [r[5] for r in after if r[0] and r[5] < 9]
    assert len(occupied) == len(set(occupied))


def test_recorded_native_chris_twelve_record_copy_has_mine_and_preserves_all_items():
    raw, g = recorded_game()
    before = rows(g, CHRIS)
    assert [r[0] for r in before[:6]] == [0x102, 0x104, 0x106, 0x201, 0x203, 0x304]
    assert before[9][0] == 0x101 and before[11][0] == 0x100
    adjacent = {a: g.rd(a, T.TEMPLATE_BLOCK) for a in (CHRIS-T.TEMPLATE_BLOCK, CHRIS+T.TEMPLATE_BLOCK)}
    ok, count = N._bank(g, CHRIS, 1, 'recorded_chris')
    assert ok and count == 1
    after = rows(g, CHRIS)
    assert [(r[0], r[1], r[5]) for r in after if r[0] == 0x10A] == [(0x10A, 5, 7)]
    assert after[:5] == before[:5]  # exact gun, grenade and ammo records
    same_items_except_grid(before, after, excluded=(0x10A,))
    assert next(r for r in after if r[0] == 0x304)[5] != 7
    assert after[9:] == before[9:]
    for address, expected in adjacent.items():
        assert g.rd(address, len(expected)) == expected
    written = g.rd(CHRIS, T.TEMPLATE_BLOCK)
    assert N._bank(g, CHRIS, 1, 'recorded_chris')[0]
    assert g.rd(CHRIS, T.TEMPLATE_BLOCK) == written


def test_recorded_eggs_and_mines_target_the_same_native_chris_block():
    raw, g = recorded_game()
    before = rows(g, CHRIS)
    outside = g.rd(CHRIS-T.TEMPLATE_BLOCK, T.TEMPLATE_BLOCK)
    inventory = g.rd(0x303F89E0+T.INV_OFS, T.INV_SLOTS*T.SLOT)
    assert N.templates(g)['mine_loadout_blocks'] == 50
    assert any(r[0] == 0x10A and r[5] == 7 for r in rows(g, CHRIS))
    result = E.templates(g)
    assert result['verified']
    after = rows(g, CHRIS)
    assert any(r[0] == E.EGG_ID and r[1] == 5 for r in after)
    assert not any(r[0] == 0x10A for r in after)
    same_items_except_grid(before, after, excluded=(E.EGG_ID,))
    assert g.rd(CHRIS-T.TEMPLATE_BLOCK, T.TEMPLATE_BLOCK) == outside
    assert g.rd(0x303F89E0+T.INV_OFS, len(inventory)) == inventory


def test_native_main_thirty_bounds_include_reordered_last_four_descriptors():
    raw, g = recorded_game()
    recorded = {int(r['address'], 16): (int(r['pointer'], 16), r['count']) for r in DATA['descriptor_records']}
    assert len(recorded) == 64
    assert T.TEMPLATE_DESCRIPTORS[0] == 0x0175496C
    assert T.TEMPLATE_DESCRIPTORS[-1] == 0x01754874
    assert [recorded[a] for a in T.TEMPLATE_DESCRIPTORS] == [(T.TEMPLATE+i*T.TEMPLATE_BLOCK, 12) for i in range(30)]
    assert T.TEMPLATE+29*T.TEMPLATE_BLOCK == 0x01733D20
    T.verify_main_presets(g)


@pytest.mark.parametrize('descriptor', [0x0175488C, 0x017548DC, 0x0175496C, 0x01754874])
@pytest.mark.parametrize('field,value', [(0, 0x01730048), (4, 11), (4, 13)])
def test_wrong_native_pointer_or_record_count_refuses_before_any_template_write(descriptor, field, value):
    raw, g = recorded_game()
    raw.u32(descriptor+field, value)
    for operation in (N.templates, E.templates):
        with pytest.raises((ValueError, RuntimeError), match='descriptor'):
            operation(g)
        assert raw.writes == []


def test_generic_loadout_checks_native_last_descriptor_before_writing():
    raw, g = recorded_game()
    raw.u32(T.TEMPLATE_DESCRIPTORS[-1]+4, 0)
    with pytest.raises(RuntimeError, match='descriptor'):
        T.loadout(g, seed=1)
    assert raw.writes == []
