"""Only identified, usable RE5 recovery items may bypass the loose-item guard."""
import math
import struct

import pytest

from gbox.mercs.titles import re5_health as H
from gbox.mercs.titles import re5_ps3 as R


def test_carried_heals_keep_identity_and_exclude_mines_ammo_red_and_unknown_ids():
    rows = [{'id': item, 'type': item >> 8, 'rounds': 1,
             'slot': n, 'grid': n % 9, 'hand': n == 2}
            for n, item in enumerate((0x10A, 0x201, 0x304, 0x305, 0x306, 0x307, 0x308, 0x309))]
    selected = H.carried_heals(rows)
    assert [row['id'] for row in selected] == [0x304, 0x305, 0x307, 0x309]
    assert selected[0] is rows[2] and selected[0]['hand']
    assert selected[-1]['slot'] == 7


@pytest.mark.parametrize('change', [{'rounds': 0}, {'rounds': -1}, {'rounds': 0xFFFFFFFF},
                                  {'rounds': True}, {'rounds': math.nan}, {'rounds': '1'},
                                  {'type': 1}, {'id': '0x304'}, {'id': 0x1304}])
def test_empty_or_malformed_inventory_never_becomes_a_heal(change):
    assert H.carried_heals([{'id': 0x304, 'type': 3, 'rounds': 1, **change}]) == []


@pytest.mark.parametrize('hp,maximum,expected', [(400, 1000, True), (401, 1000, False),
                                              (2, 1000, True), (1, 1000, False),
                                              (0, 1000, False), (-1, 1000, False),
                                              (100, 0, False), (1100, 1000, False),
                                              (math.nan, 1000, False), (10, math.inf, False),
                                              (True, 1000, False)])
def test_healing_threshold_requires_valid_living_hp(hp, maximum, expected):
    assert H.needs_healing({'hp': hp, 'hp_max': maximum}) is expected


def test_missing_records_fail_closed():
    assert H.carried_heals(None) == []
    assert H.carried_heals([None, {}, {'id': 0x304}]) == []
    assert not H.needs_healing({})


PLAYER, MANAGER, ITEM = 0x30400000, 0x30300000, 0x30500000


class Memory:
    def __init__(self):
        self.values = {R.S_PLAYER: MANAGER, MANAGER + 0x28: PLAYER}
        self.writes = []

    def rd(self, address, size):
        assert size == 4
        return struct.pack('>I', self.values.get(address, 0))

    def write(self, address, data):
        self.writes.append((address, data))
        raise AssertionError('health identification must not write game memory')


@pytest.fixture
def pickup(monkeypatch):
    memory = Memory()
    item = {'ptr': ITEM, 'handle': 36, 'id': 0x305, 'name': 'Green Herb', 'pos': (0., 0., 100.)}
    request = {'token': 'mash:square', 'button': 0x30600000, 'kind': R.BTN_STAGE,
               'mode': 1, 'label': R.PICKUP_LABEL, 'owner': PLAYER, 'target': 36}
    monkeypatch.setattr(R, 'selected_prompt', lambda *a, **k: dict(request))
    monkeypatch.setattr(H, 'ground_items', lambda m: [dict(item)], raising=False)
    return memory, item, request


def test_only_fresh_exact_displayed_health_handle_authorizes_pickup(pickup):
    memory, item, request = pickup
    assert H.pickup_request(memory, request, [item]) == item
    assert memory.writes == []


@pytest.mark.parametrize('change', [{'id': 0x10A}, {'id': 0x201}, {'id': 0x306},
                                  {'ptr': ITEM + 4}, {'handle': 39}])
def test_stale_goal_never_picks_replaced_mine_ammo_red_or_different_actor(pickup, monkeypatch, change):
    memory, item, request = pickup
    monkeypatch.setattr(H, 'ground_items', lambda m: [{**item, **change}])
    assert H.pickup_request(memory, request, [item]) is None


@pytest.mark.parametrize('change', [{'token': 'mash:l1'}, {'kind': R.BTN_MELEE},
                                  {'label': R.PLACE_LABEL}, {'label': R.LOOSE_ITEM_PICKUP},
                                  {'owner': PLAYER + 4}, {'target': 39}])
def test_place_loose_unknown_foreign_or_wrong_handle_prompts_are_refused(pickup, change):
    memory, item, request = pickup
    assert H.pickup_request(memory, {**request, **change}, [item]) is None


def test_changed_prompt_during_native_item_read_refuses_square(pickup, monkeypatch):
    memory, item, request = pickup
    reads = iter((dict(request), {**request, 'target': 39}))
    monkeypatch.setattr(R, 'selected_prompt', lambda *a, **k: next(reads))
    assert H.pickup_request(memory, request, [item]) is None


def test_player_replacement_during_item_read_refuses_square(pickup, monkeypatch):
    memory, item, request = pickup
    def replace_player(m):
        memory.values[MANAGER + 0x28] = PLAYER + 4
        return [dict(item)]
    monkeypatch.setattr(H, 'ground_items', replace_player)
    assert H.pickup_request(memory, request, [item]) is None


def test_duplicate_or_missing_handle_has_no_pickup_authorization(pickup, monkeypatch):
    memory, item, request = pickup
    assert H.pickup_request(memory, request, []) is None
    assert H.pickup_request(memory, request, [item, dict(item)]) is None
    monkeypatch.setattr(H, 'ground_items', lambda m: [item, dict(item)])
    assert H.pickup_request(memory, request, [item]) is None


def test_unreadable_native_table_never_authorizes_pickup(pickup, monkeypatch):
    memory, item, request = pickup
    def unreadable(m):
        raise OSError('guest unloaded')
    monkeypatch.setattr(H, 'ground_items', unreadable)
    assert H.pickup_request(memory, request, [item]) is None


class NativeMemory:
    def __init__(self):
        self.bytes = {}
        self.reads = []
        self.writes = []

    def put(self, address, fmt, *values):
        self.bytes.update({address + i: b for i, b in enumerate(struct.pack(fmt, *values))})

    def rd(self, address, size):
        self.reads.append((address, size))
        return bytes(self.bytes.get(address + i, 0) for i in range(size))

    def write(self, *args):
        self.writes.append(args)
        raise AssertionError('native health identification must remain read-only')


def native_world(item=0x304):
    m = NativeMemory()
    array, volume = 0x30600000, 0x30700000
    m.put(R.S_ITEM, '>I', MANAGER)
    m.put(MANAGER, '>I', H.ITEM_MANAGER_VT)
    m.put(MANAGER + 0x28, '>I', 1)
    m.put(MANAGER + 0x34, '>I', array)
    m.put(array, '>I', ITEM)
    vt = next((vt for vt, iid in H.HEALTH_VTABLES.items() if iid == item), 0x015B44B8)
    m.put(ITEM, '>I', vt)
    m.put(ITEM + H.ITEM_HANDLE, '>I', 676)
    m.put(ITEM + 0x30, '>3f', -1161.7, .5, -897.3)
    m.put(ITEM + H.ITEM_DATA, '>I', H.ITEM_DATA_VT)
    m.put(ITEM + H.ITEM_ID, '>H', item)
    m.put(ITEM + H.ITEM_COUNT, '>I', 1)
    m.put(ITEM + H.ITEM_VOLUME, '>I', volume)
    m.put(ITEM + H.ITEM_SELF, '>I', ITEM)
    m.put(volume, '>3IB', H.PICKUP_VOLUME_VT, ITEM, 0x07000000 | item << 8, 1)
    return m, array, volume


@pytest.mark.parametrize('item', sorted(H.HEAL_IDS))
def test_native_health_actor_list_preserves_full_id_handle_position_read_only(item):
    m, _, volume = native_world(item)
    result = H.ground_items(m)
    assert len(result) == 1
    assert result[0]['ptr'] == ITEM and result[0]['handle'] == 676 and result[0]['id'] == item
    assert result[0]['pos'] == pytest.approx((-1161.7, .5, -897.3))
    # Far-away health must remain visible when the volume's nearby-player mask is zero.
    assert m.rd(volume + 0x10, 4) == bytes(4)
    assert m.writes == [] and max(size for _, size in m.reads) <= 0x3C


@pytest.mark.parametrize('item', [0x10A, 0x201, 0x306, 0x308])
def test_native_mines_ammo_uncombined_red_and_unknown_health_are_not_route_goals(item):
    m, _, _ = native_world(item)
    assert H.ground_items(m) == []


@pytest.mark.parametrize('address,fmt,value', [
    (MANAGER, '>I', 0), (MANAGER + 0x28, '>I', H.MAX_ITEMS + 1),
    (ITEM + H.ITEM_ID, '>H', 0x10A), (ITEM + H.ITEM_COUNT, '>I', 0),
    (ITEM + H.ITEM_HANDLE, '>I', 0), (ITEM + H.ITEM_VOLUME, '>I', 0),
    (ITEM + H.ITEM_SELF, '>I', ITEM + 4), (ITEM + 0x30, '>f', math.nan),
    (0x30700000, '>I', 0), (0x30700004, '>I', ITEM + 4),
    (0x30700008, '>I', 0x07010A00), (0x3070000C, '>B', 0)])
def test_native_identity_quantity_volume_and_position_are_required(address, fmt, value):
    m, _, _ = native_world()
    m.put(address, fmt, value)
    assert H.ground_items(m) == []


def test_item_list_replaced_during_reads_is_discarded():
    m, array, _ = native_world()
    rd = m.rd
    def changed(address, size):
        value = rd(address, size)
        if address == ITEM + 0x30:
            m.put(array, '>I', ITEM + 4)
        return value
    m.rd = changed
    assert H.ground_items(m) == []


def test_actor_collected_during_position_read_is_discarded():
    m, _, _ = native_world()
    rd = m.rd
    def collected(address, size):
        value = rd(address, size)
        if address == ITEM + 0x30:
            m.put(ITEM + H.ITEM_COUNT, '>I', 0)
        return value
    m.rd = collected
    assert H.ground_items(m) == []
