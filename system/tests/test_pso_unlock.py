from pso_owned_evidence import original_test_path
import contextlib
import copy
import importlib.util
import json
from pathlib import Path
import struct
import sys
import types
import pytest

BASE=original_test_path('unlock-policy/test_unlock.py').resolve().parent
PKG='_unlock_policy_test'
pkg=types.ModuleType(PKG);pkg.__path__=[];sys.modules[PKG]=pkg
registry=types.ModuleType(PKG+'.registry');registry.Unsupported=RuntimeError;sys.modules[registry.__name__]=registry

def load(name,path):
    spec=importlib.util.spec_from_file_location(PKG+'.'+name,path)
    module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module);return module

mapping=load('pso_coop_mapping',Path(__file__).resolve().parents[1]/'gbox/pso_coop_mapping.py')
live=types.ModuleType(PKG+'.pso_gc_live');live.GC=object;live.dispatcher_lock=lambda ad:contextlib.nullcontext();sys.modules[live.__name__]=live
unlock=load('pso_coop_unlock',Path(__file__).resolve().parents[1]/'gbox/pso_coop_unlock.py')
guards=json.loads((BASE.parent/'observer-v1/quest-guards-receipt-1793620544264647000.json').read_text())['report']['callsites']

class Fake:
    def __init__(self,episode=1):
        self.proc=object();self.environment={'sid':'abc','pid':22,'birth':12.3,'card':'privateA','epoch':0}
        self.bitmap=bytearray(512);self.visited=0;self.calls=[];self.stop=False;self.behavior=None
        self.words={unlock.MODE:2,unlock.DIFFICULTY:0,unlock.EPISODE:episode-1}
        self.code={r['address']:bytes.fromhex(r['bytes']) for r in guards}
        self.state=dict(verified=True,cooperative=True,phase=14,travelling=False,floor=0,
                        episode=episode,difficulty=0,difficulty_verified=True,players={
            i:dict(ptr=f'{0x80da4000+i*0x2000:08X}',**{'class':'TObjPlayer'},entity_id=i-1,controller=i)
            for i in (1,2)})
    def snapshot(self):return copy.deepcopy(self.state)
    def read_memory(self,address,length):
        if address in self.code:return self.code[address][:length]
        if address==unlock.BITMAP:return bytes(self.bitmap[:length])
        if address==unlock.VISITED:return struct.pack('>I',self.visited)
        return struct.pack('>I',self.words[address])
    def mark(self,difficulty,flag):self.bitmap[difficulty*128+(flag>>3)]|=0x80>>(flag&7)
    def apply(self):return unlock.apply_once(self,self,'abc',{'game_id':'exact'},lambda:self.stop)

class Native:
    def __init__(self,ad,index=0,**kwargs):self.ad=ad;self.index=index
    def check(self,**kwargs):
        assert kwargs=={'require_probe':False}
        return int(self.ad.state['players'][self.index+1]['ptr'],16)
    def call(self,rows):
        ad=self.ad;assert 1<=len(rows)<=20;ad.calls.append(tuple(rows))
        for fn,*args in rows:
            if fn==unlock.SET_FLAG:ad.mark(*args)
            elif fn==unlock.SET_DESTINATION:ad.visited|=1<<(args[0]-1)
            else:raise AssertionError('unknownnativecall')
        if ad.behavior:ad.behavior(ad)

@pytest.fixture(autouse=True)
def stubs(monkeypatch):
    monkeypatch.setattr(mapping,'_environment',lambda ad,sid,game:copy.deepcopy(ad.environment))
    monkeypatch.setattr(unlock,'GC',Native)

@pytest.mark.parametrize('episode,mask',[(1,0x3ff),(2,0x187ff)])
def test_native_or_calls_and_readback_keep_completion_and_other_difficulty(episode,mask):
    ad=Fake(episode);ad.mark(0,0x65);ad.mark(3,0x1f7);before=bytes(ad.bitmap)
    result=ad.apply()
    assert result['status']=='applied_readback_verified' and ad.visited==mask
    assert result['native_menu_acceptance_verified'] is False
    assert result['completion_credit_awarded'] is False and result['card_saved'] is False
    assert all(unlock.flag_set(ad.bitmap,0,f) for f in unlock.FLAGS)
    assert ad.bitmap[128:]==before[128:]
    assert all(unlock.flag_set(ad.bitmap,0,f)==(f==0x65) for f in range(0x65,0x96,2))
    assert all(len(batch)<=20 for batch in ad.calls)
    count=len(ad.calls);again=ad.apply();assert again['repeated'] and len(ad.calls)==count
    called_floors={args[0] for batch in ad.calls for fn,*args in batch if fn==unlock.SET_DESTINATION}
    assert called_floors==set(unlock.DESTINATIONS[episode])

@pytest.mark.parametrize('field,value',[('phase',15),('cooperative',False),('travelling',True),('floor',1),('episode',3),('difficulty',True),('difficulty_verified',False)])
def test_unverified_state_never_calls(field,value):
    ad=Fake();ad.state[field]=value
    with pytest.raises((ValueError,InterruptedError)):ad.apply()
    assert not ad.calls

@pytest.mark.parametrize('address,value',[(unlock.MODE,1),(unlock.DIFFICULTY,1),(unlock.EPISODE,1)])
def test_native_binding_mismatch_never_calls(address,value):
    ad=Fake();ad.words[address]=value
    with pytest.raises(ValueError):ad.apply()
    assert not ad.calls

@pytest.mark.parametrize('address',list(unlock.GUARDS))
def test_changed_exact_code_never_calls(address):
    ad=Fake();raw=ad.code[address];ad.code[address]=bytes([raw[0]^1])+raw[1:]
    with pytest.raises(ValueError):ad.apply()
    assert not ad.calls

@pytest.mark.parametrize('change',[lambda ad:ad.state['players'].pop(2),lambda ad:ad.state['players'][2].update(ptr=ad.state['players'][1]['ptr']),lambda ad:ad.state['players'][2].update(controller=1)])
def test_bad_players_never_call(change):
    ad=Fake();change(ad)
    with pytest.raises(ValueError):ad.apply()
    assert not ad.calls

def test_operator_stop_before_and_between_batches():
    ad=Fake();ad.stop=True
    with pytest.raises(InterruptedError):ad.apply()
    assert not ad.calls
    ad.stop=False;ad.behavior=lambda ad:setattr(ad,'stop',True)
    with pytest.raises(InterruptedError):ad.apply()
    assert len(ad.calls)==1
    ad.stop=False;ad.behavior=None
    assert ad.apply()['status']=='interrupted' and len(ad.calls)==1

def test_native_queue_timeout_is_not_retried():
    ad=Fake()
    def fail(ad):raise RuntimeError('native queue acknowledgement timeout')
    ad.behavior=fail
    with pytest.raises(RuntimeError):ad.apply()
    count=len(ad.calls);ad.behavior=None
    assert ad.apply()['status']=='outcome_unknown' and len(ad.calls)==count

def test_binding_change_between_batches_stops_further_native_calls():
    ad=Fake();ad.behavior=lambda ad:ad.environment.update(epoch=1)
    with pytest.raises(ValueError):ad.apply()
    assert len(ad.calls)==1
    assert ad.apply()['blocked_by_prior_outcome'] is True
    assert len(ad.calls)==1

def test_incomplete_native_readback_is_not_success():
    ad=Fake();ad.behavior=lambda ad:setattr(ad,'visited',0)
    with pytest.raises(RuntimeError,match='readback'):ad.apply()
    assert getattr(ad,unlock.ATTRIBUTE).receipts[-1].status=='outcome_unknown'

def test_preexisting_bit_loss_is_detected():
    ad=Fake();ad.mark(0,0x65)
    ad.behavior=lambda ad:ad.bitmap.__setitem__(0x65>>3,ad.bitmap[0x65>>3]&~(0x80>>(0x65&7)))
    with pytest.raises(RuntimeError,match='unexpectedly'):ad.apply()

def test_process_identity_change_gets_fresh_proof_not_old_receipt():
    ad=Fake();ad.apply();ad.proc=object();ad.environment['birth']=16.8
    result=ad.apply();assert result['repeated'] is False and result['native_calls']==0

@pytest.mark.parametrize('difficulty,flag',[(True,0),(4,0),(0,True),(0,1024),(0,-1)])
def test_flag_coordinates_fail_closed(difficulty,flag):
    with pytest.raises(ValueError):unlock.flag_set(bytes(512),difficulty,flag)


def test_stale_snapshot_actor_is_rejected(monkeypatch):
    ad=Fake();original=ad.snapshot
    def stale():
        result=original();result['players'][2]['ptr']='80DB0000';return result
    monkeypatch.setattr(ad,'snapshot',stale)
    with pytest.raises(ValueError,match='player changed'):ad.apply()
    assert not ad.calls


def test_applied_policy_allows_later_episode_and_difficulty_with_fresh_actors():
    ad=Fake();ad.apply();count=len(ad.calls)
    ad.state['episode']=2;ad.words[unlock.EPISODE]=1;ad.visited=0
    ad.state['players'][1]['ptr']='80DB0000';ad.state['players'][2]['ptr']='80DB2000'
    assert ad.apply()['episode']==2 and len(ad.calls)>count
    ad.state['difficulty']=1;ad.words[unlock.DIFFICULTY]=1
    assert ad.apply()['difficulty']==1
    assert len(getattr(ad,unlock.ATTRIBUTE).receipts)==3
    assert all(unlock.flag_set(ad.bitmap,1,f) for f in unlock.FLAGS)


def test_applied_receipt_requires_fresh_readback_and_reapplies_loaded_flags():
    ad=Fake();ad.apply();count=len(ad.calls)
    ad.state['players'][1]['ptr']='80DB0000';ad.state['players'][2]['ptr']='80DB2000'
    assert ad.apply()['fresh_access_readback_verified'] and len(ad.calls)==count
    ad.bitmap=bytearray(512);ad.visited=0
    assert ad.apply()['repeated'] is False and len(ad.calls)>count
    assert len(getattr(ad,unlock.ATTRIBUTE).receipts)==1


@pytest.mark.parametrize('kind',['unknown','interrupted'])
def test_uncertain_batch_blocks_new_episode_and_difficulty_for_same_process(kind):
    ad=Fake()
    def fail(ad):
        if kind=='interrupted':ad.stop=True
        else:raise RuntimeError('unknown queue outcome')
    ad.behavior=fail
    with pytest.raises((RuntimeError,InterruptedError)):ad.apply()
    count=len(ad.calls);ad.behavior=None;ad.stop=False
    ad.state['episode']=2;ad.words[unlock.EPISODE]=1
    ad.state['difficulty']=2;ad.words[unlock.DIFFICULTY]=2
    result=ad.apply();assert result['blocked_by_prior_outcome'] and len(ad.calls)==count


def test_code_change_between_batches_prevents_additional_calls():
    ad=Fake()
    def mutate(ad):
        address=unlock.SET_FLAG;ad.code[address]=bytes(len(ad.code[address]))
    ad.behavior=mutate
    with pytest.raises(ValueError,match='executable differs'):ad.apply()
    assert len(ad.calls)==1
