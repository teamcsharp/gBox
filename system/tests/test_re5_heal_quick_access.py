import struct

from gbox.mercs.titles import re5_switch_mods as M, re5_switch as R
from gbox.mercs.flight_recorder import FlightRecorder


def template(rows):
    t = bytearray(M.TEMPLATE_REC * M.TEMPLATE_RECS)
    for k in range(M.TEMPLATE_RECS):
        item, count, grid, hand = rows.get(k, (0, -1, k, 0))
        struct.pack_into('<Ii', t, k*M.TEMPLATE_REC, item, count)
        struct.pack_into('<II', t, k*M.TEMPLATE_REC+M.REC_GRID, grid, hand)
    return t


def record(t, k):
    return bytes(t[k*M.TEMPLATE_REC:(k+1)*M.TEMPLATE_REC])


def test_mine_swap_preserves_every_healing_quick_slot_and_uses_other_item():
    t = template({0:(M.MINE_ID,5,0,0), 1:(0x304,1,1,0), 3:(0x305,2,3,0),
                  5:(0x119,10,5,0), 7:(0x11B,8,7,1)})
    heals = [record(t, i) for i in (1,3)]
    assert M._mine_block(t)
    assert [record(t, i) for i in (1,3)] == heals
    assert struct.unpack_from('<I',t,M.REC_GRID)[0] == 5
    assert struct.unpack_from('<I',t,5*M.TEMPLATE_REC+M.REC_GRID)[0] == 0
    assert not M._mine_block(t)


def test_mine_leaves_template_unchanged_when_only_heals_can_be_displaced():
    t = template({0:(M.GRENADE_ID,5,0,0), 1:(0x304,1,1,0), 3:(0x305,2,3,0),
                  5:(0x307,1,5,0), 7:(0x11B,8,7,1)})
    before = bytes(t)
    assert not M._mine_block(t) and bytes(t) == before


def test_inventory_diagnostics_distinguish_missing_off_quick_and_accessible_heals():
    driver = R.DRIVER()
    assert driver.progress({})['heal_inventory_slots'] is None
    inv = [{'id':0x304,'rounds':1,'grid':0}, {'id':0x305,'rounds':2,'grid':7},
           {'id':0x307,'rounds':0,'grid':1}, {'id':0x11B,'rounds':8,'grid':3}]
    progress = driver.progress({'inventory':inv})
    assert progress['heal_inventory_read'] and progress['heal_inventory_slots'] == 2
    assert progress['heal_quick_slots'] == 1
    recorder = FlightRecorder()
    recorder.observe(1, {'player':{'pos':[0,0,0]}, 'inventory':inv}, {}, progress)
    assert recorder.tail[-1]['inventory'][0]['grid'] == 0
    assert recorder.tail[-1]['diagnostics']['heal_quick_slots'] == 1
