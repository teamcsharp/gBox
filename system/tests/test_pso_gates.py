from pso_owned_evidence import original_test_path
import copy
import json
from pathlib import Path
import struct

import pytest
from gbox import pso_coop_gates as G

BASE=original_test_path('native-gates/test_gates.py').resolve().parent
EVIDENCE=BASE.parent/'native-geometry/gate-evidence-1793625208147107300.json'
CAPTURE=BASE.parent/'observer-v1/field-geometry-receipt-1793624681829990800.json'


def fixture():
    evidence=json.loads(EVIDENCE.read_text());capture=json.loads(CAPTURE.read_text())['result']
    object=next(o for o in capture['interactive_objects'] if o['entity']['entity_id']==16490)
    pointer=int(object['entity']['ptr'],16);raw=bytes.fromhex(object['raw_prefix'])[:0xd4]
    regions={g['address']:bytes.fromhex(g['bytes']) for g in evidence['guards']}
    regions[pointer]=raw
    regions[struct.unpack_from('>I',raw)[0]]=G.CLASS.encode()+b'\0'
    for addr,value in zip((0x804FE120,0x805D6060,0x805D5FC0,0x805D49B8),(14,0,1,0)):
        regions[addr]=struct.pack('>I',value)
    regions[0x8050EA10]=struct.pack('>2I',0x80DA62A0,0x80DA8590)
    state=copy.deepcopy(capture['state']);state['players']={int(k):v for k,v in state['players'].items()}
    state['entities']=[dict(object['entity'],kind='gate')]
    class Memory:
        callback=None
        reads=[]
        def read_memory(self,addr,n):
            self.reads.append((addr,n))
            if self.callback:self.callback(addr,n)
            for start,data in regions.items():
                if start<=addr and addr+n<=start+len(data):return data[addr-start:addr-start+n]
            raise OSError('Unexpected read')
    return Memory(),regions,pointer,state


def test_actual_mode_one_readback_is_enabled_without_claiming_passability():
    ad,regions,pointer,state=fixture();result=G.observe(ad,state)
    assert 'door_requirements' not in state['entities'][0]
    req=result['entities'][0]['door_requirements']
    assert req['predicate']=='unconditional_enable' and req['predicate_verified']
    assert req['enable_bit'] and req['native_state']==2 and req['mode']==1
    assert not req['enemy_or_switch_test_in_this_predicate']
    assert not req['passability_verified'] and not req['room_clear_verified']
    assert not hasattr(ad,'write_memory')


@pytest.mark.parametrize('mode',[0,2,3,9])
def test_unknown_native_modes_never_become_room_clear_or_switch_claims(mode):
    ad,regions,pointer,state=fixture();raw=bytearray(regions[pointer]);struct.pack_into('>I',raw,0xcc,mode);regions[pointer]=bytes(raw)
    req=G.observe(ad,state)['entities'][0]['door_requirements']
    assert not req['predicate_verified'] and not req['passability_verified']
    if mode in (2,3):
        assert req['predicate']=='native_stage_flag_accessor_unknown' and req['flag_index']==65535 and req['accessor']=='80229220'


@pytest.mark.parametrize('change',['vtable','name','entity_id','code','actors','area','travelling','unverified','range'])
def test_identity_or_code_failure_removes_all_predicates(change):
    ad,regions,pointer,state=fixture()
    if change in ('vtable','entity_id','name'):
        raw=bytearray(regions[pointer])
        if change=='vtable':struct.pack_into('>I',raw,0x18,0x804afb64)
        if change=='entity_id':struct.pack_into('>H',raw,0x1c,16491)
        if change=='name':regions[struct.unpack_from('>I',raw)[0]]=b'X'+G.CLASS.encode()[1:]+b'\0'
        regions[pointer]=bytes(raw)
    if change=='code':regions[0x8015DAE4]=bytes(224)
    if change=='actors':regions[0x8050EA10]=bytes(8)
    if change=='area':regions[0x805D5FC0]=struct.pack('>I',2)
    if change=='travelling':state['travelling']=True
    if change=='unverified':state['verified']=False
    if change=='range':state['entities'][0]['ptr']='90000000'
    result=G.observe(ad,state)
    assert result['door_requirements']['state']=='unverified'
    assert result['door_requirements']['objects']==[] and 'door_requirements' not in result['entities'][0]


def test_changed_object_between_reads_has_no_authority():
    ad,regions,pointer,state=fixture();count=[0]
    def changed(addr,n):
        if addr==pointer:
            count[0]+=1
            if count[0]==2:
                raw=bytearray(regions[pointer]);struct.pack_into('>I',raw,0xd0,0);regions[pointer]=bytes(raw)
    ad.callback=changed
    assert G.observe(ad,state)['door_requirements']['state']=='unverified'


def test_unrelated_entities_do_not_trigger_reads():
    ad,regions,pointer,state=fixture();state['entities'][0]['class']='TObjDoor'
    assert G.observe(ad,state)['door_requirements']['objects']==[] and not ad.reads


def test_exact_observer_graph_is_only_observed_16_to_11_not_invented_room15_edge():
    evidence=json.loads(EVIDENCE.read_text());edges=evidence['transitions']
    assert len(edges)==2
    assert {e['player'] for e in edges}=={1,2}
    for edge in edges:
        assert edge['before']['player']['room']==16 and edge['after']['player']['room']==11
        assert not edge['room_clear_verified'] and not edge['bidirectional_route_verified']
