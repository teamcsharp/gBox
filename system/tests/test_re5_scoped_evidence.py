"""Native P2 damage witnesses preserve identity and never substitute P1 bytes."""
import base64
import struct
import zlib

from gbox.mercs import damage as D, incident as I
from gbox.mercs.titles import re5_combat as B, re5_ps3 as R
from test_re5_coop import world

P1,P2,A1,A2,MINE=0x303F7800,0x30407800,0x30500000,0x30510000,0x30600000


def scene(second=True):
    m=world(second);m.mercs_player_index=int(second)
    for actor,action in ([(P1,A1),(P2,A2)] if second else [(P1,A1)]):
        m.u(actor+B.P_ACTION_OBJ,action);m.u(action,B.FIRE_VT);m.u(action+0x18,actor)
    actor=P2 if second else P1
    s={'player':{'ptr':actor,'hp':600 if second else 700,'hp_max':1000,'pos':(101.,0.,200.)},
       'enemies':[],'ground_mines':{MINE:{'pos':(300.,0.,200.),'owner':'unknown'}}}
    return m,s


def test_scoped_p2_raw_fields_match_its_actor_inventory_and_hp_without_writes():
    m,s=scene();m.u(P1+B.P_INV,0x11111111);m.u(P2+B.P_INV,0x22222222)
    before=dict(m.data);raw=D.hook_bytes(m,'BLUS30491',s)
    assert raw['state']=='done' and raw['matches_snapshot_hp']
    assert raw['player']==P2 and raw['player_index']==1
    fields={row['name']:row for row in raw['fields']}
    assert fields['hp_max']['address']==hex(P2+R.P_HP) and fields['hp_max']['hex']=='025803e8'
    assert fields['inventory']['address']==hex(P2+B.P_INV) and fields['inventory']['hex'].startswith('22222222')
    assert fields['current_action']['address']==hex(A2) and m.data==before


def test_scoped_p2_ram_witness_keeps_all_observed_mines_and_own_player_bytes():
    m,s=scene();before=dict(m.data);witness=I.ram_witness(m,'BLUS30491',s)
    assert witness['state']=='done' and witness['player']==P2 and witness['player_index']==1
    spans=witness['spans']
    assert [(row['kind'],row['address']) for row in spans]==[
        ('player',hex(P2)),('action',hex(A2)),('mine',hex(MINE))]
    for row in spans:
        assert zlib.decompress(base64.b64decode(row['data_b64']))==m.rd(int(row['address'],16),row['size'])
    assert m.data==before and sum(row['size'] for row in spans)<=48*1024


def test_solo_raw_capture_and_ram_witness_preserve_default_p1():
    m,s=scene(False)
    raw=D.hook_bytes(m,'BLUS30491',s);witness=I.ram_witness(m,'BLUS30491',s)
    assert raw['state']==witness['state']=='done'
    assert raw['player']==witness['player']==P1 and raw['matches_snapshot_hp']
    assert raw['player_index']==witness['player_index']==0


def test_p1_snapshot_or_missing_p2_cannot_authorize_a_p2_evidence_dump():
    m,s=scene();s['player']['ptr']=P1
    assert D.hook_bytes(m,'BLUS30491',s)['state']=='failed'
    assert I.ram_witness(m,'BLUS30491',s)['spans']==[]
    m,s=scene();m.put(P2+0x2F14,b'\0')
    assert D.hook_bytes(m,'BLUS30491',s)['state']=='failed'
    assert I.ram_witness(m,'BLUS30491',s)['spans']==[]


def test_scoped_actor_change_during_raw_fields_or_bulk_witness_is_explicit():
    for capture in ('fields','bulk'):
        m,s=scene();original=m.rd
        def changing(address,size):
            value=original(address,size)
            if address==P2+B.P_INV and capture=='fields' or address==P2 and size==0x3000 and capture=='bulk':
                m.mercs_player_index=0
            return value
        m.rd=changing
        if capture=='fields':
            raw=D.hook_bytes(m,'BLUS30491',s)
            assert raw['state']=='failed' and 'changed during' in raw['detail']
        else:
            witness=I.ram_witness(m,'BLUS30491',s)
            assert witness['state']=='partial' and 'identity changed during' in witness['error']
            assert witness['spans'][0]['address']==hex(P2)


def test_foreign_or_reassigned_p2_action_is_not_claimed_as_owned_evidence():
    m,s=scene();m.u(A2+0x18,P1)
    assert D.hook_bytes(m,'BLUS30491',s)['state']=='failed'
    assert I.ram_witness(m,'BLUS30491',s)['spans']==[]
    for capture in ('fields','bulk'):
        m,s=scene();original=m.rd
        def changing(address,size):
            value=original(address,size)
            if address==A2 and size in (0x24,0x40):m.u(A2+0x18,P1)
            return value
        m.rd=changing
        if capture=='fields':assert D.hook_bytes(m,'BLUS30491',s)['state']=='failed'
        else:assert I.ram_witness(m,'BLUS30491',s)['state']=='partial'
