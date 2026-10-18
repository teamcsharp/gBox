import json
import struct
import threading
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from gbox import re2gc_items as I
from gbox import re2gc_state as S
from gbox.debug import DolphinProcMem
from test_re2gc_state import build, snapshot


def ready(build):
    ram = bytearray(snapshot(build)); bss = 0x80800000; base = 0x80400000
    def put(a,data): ram[a-S.RAM_BASE:a-S.RAM_BASE+len(data)] = data
    character = 0 if build.scenario=='leon' else 1; weapon = 2+character
    put(I.CHARACTER,bytes((character,)))
    put(I.GAME_FLAGS,struct.pack('>I',0x40000000))
    put(S.INVENTORY,bytes((weapon,18,0,0xaa)))
    put(bss+I.TASK,struct.pack('>HHI',1,1,base+I.MENU[build.scenario])+b'\x01\0')
    control=bytearray(24);control[:4]=b'\x01\x03\0\0';control[8:12]=bytes((0,0,weapon,weapon));control[22]=1
    put(bss+I.CURRENT_TASK,struct.pack('>I',bss+I.TASK_TABLE+7*36))
    put(bss+I.CONTROL,control);put(I.LOADED,struct.pack('>H',0xf000+weapon))
    return bytes(ram)


def mutated(ram,changes):
    out=bytearray(ram)
    for address,data in changes:out[address-S.RAM_BASE:address-S.RAM_BASE+len(data)]=data
    return bytes(out)


def test_owned_ready_menu_token_and_identity(build):
    ram=ready(build);v=I.view(build,ram)
    assert v['editable'] and v['source_code_verified'] and not v['gameplay_verified']
    assert I.view(build,mutated(ram,[(0x80170000,b'\x07')]))['inventory_sha256']==v['inventory_sha256']
    for address,data in [(0x80800000+I.CONTROL,b'\x02'),(0x80800000+I.TASK,b'\0\0'),
                         (0x80800000+I.CONTROL+2,b'\x01'),(I.CHARACTER,b'\x0b'),
                         (0x80800000+S.EQUIPPED_SLOT,b'\xff')]:
        changed=I.view(build,mutated(ram,[(address,data)]))
        assert not changed['editable']
        with pytest.raises(ValueError):I.plan(build,mutated(ram,[(address,data)]),'set','inventory',2,1,1)


def test_plan_two_slot_placement_preserves_unknown_capacity_reserved_and_box(build):
    ram=ready(build); p=I.plan(build,ram,'set','inventory',2,17,255)
    out=bytes.fromhex(p['inventory'])
    assert out[8:16]==bytes((17,255,1,0,17,255,2,0))
    assert out[:8]==S._ram(ram,S.INVENTORY,8)
    assert out[32:]==S._ram(ram,S.INVENTORY+32,8)
    assert p['item_box']==S._ram(ram,S.ITEM_BOX,256).hex()
    assert all(row['address']!=S.INVENTORY+40 for row in p['changes'])
    assert sum(len(bytes.fromhex(row['after'])) for row in p['changes'])<=42
    with pytest.raises(ValueError,match='adjacent'):
        I.plan(build,ram,'set','inventory',7,17,255)
    with pytest.raises(ValueError,match='adjacent'):
        I.plan(build,ram,'set','inventory',0,17,255)


def test_pair_half_edit_removes_whole_pair_and_adjusts_equipment(build):
    ram=ready(build)
    ram=mutated(ram,[(S.INVENTORY,bytes((17,5,1,0xaa,17,5,2,0xbb))),
        (0x80800000+S.EQUIPPED_ITEM,b'\x11\x11'),(I.LOADED,b'\xf0\x11')])
    p=I.plan(build,ram,'set','inventory',1,1,1)
    assert bytes.fromhex(p['inventory'])[:8]==bytes((1,1,0,0xaa,0,0,0,0xbb))
    assert (p['equipped_slot'],p['equipped_item'])==(0,1)
    p=I.plan(build,ram,'set','inventory',1,20,10)
    assert (p['equipped_slot'],p['equipped_item'])==(0x80,0)


def test_box_is_single_record_and_never_rewrites_equipment(build):
    ram=ready(build);p=I.plan(build,ram,'set','box',63,17,255)
    assert bytes.fromhex(p['item_box'])[-4:]==bytes((17,255,3,0))
    assert p['inventory']==S._ram(ram,S.INVENTORY,40).hex()
    assert [r['address'] for r in p['changes']]==[S.ITEM_BOX]


@pytest.mark.parametrize('slot,item,qty',[(True,1,1),(1,True,1),(1,1,True),(-1,1,1),(8,1,1),
    (1,104,1),(1,1,256),(1,0,1),(1,20,0),(1,1,-1)])
def test_rejects_invalid_inputs_without_plan(build,slot,item,qty):
    with pytest.raises(ValueError):I.plan(build,ready(build),'set','inventory',slot,item,qty)


def test_rejects_placeholder_weapon_for_character_but_allows_storage(build):
    ram=ready(build);wrong=3 if build.scenario=='leon' else 2
    with pytest.raises(ValueError,match='animation resource'):I.plan(build,ram,'set','inventory',0,wrong,10)
    p=I.plan(build,ram,'set','inventory',2,wrong,10)
    ram=mutated(ram,[(r['address'],bytes.fromhex(r['after'])) for r in p['changes']])
    with pytest.raises(ValueError,match='animation resource'):I.plan(build,ram,'equip','inventory',2,0,0)
    assert I.plan(build,ram,'unequip','inventory',0,0,0)['equipped_item']==0


@pytest.mark.parametrize('records,box',[(bytes((17,1,1,0)),False),(bytes((17,1,2,0,17,1,1,0)),False),
    (bytes((17,1,1,0,17,2,2,0)),False),(bytes((1,1,1,0)),False),(bytes((0,2,0,0)),False),
    (bytes((17,1,0,0)),True)])
def test_malformed_pairs_fail_closed(records,box):
    with pytest.raises(ValueError):I.pairs([records[i:i+4] for i in range(0,len(records),4)],len(records)//4,box)


class Memory(DolphinProcMem):
    def __init__(self,ram):
        self.lock=threading.RLock();self.ram=bytearray(ram);self.pid=123;self.events=[];self.fail=0;self.calls=0;self.closed=False
    def read(self,a,n):return S._ram(self.ram,a,n)
    def write(self,a,data):
        self.calls+=1;self.events.append(('write',a,bytes(data)))
        if self.calls==self.fail:
            self.ram[a-S.RAM_BASE]=data[0];raise OSError('partial write')
        self.ram[a-S.RAM_BASE:a-S.RAM_BASE+len(data)]=data
    def close(self):pass


@pytest.mark.parametrize('failure',[1,2,3])
def test_partial_write_and_close_request_roll_back_while_held(build,failure):
    ram=ready(build);p=I.plan(build,ram,'set','inventory',0,1,1);m=Memory(ram);m.fail=failure
    with pytest.raises(RuntimeError,match='restored before native dispatch'):I.apply_staged(m,p)
    assert bytes(m.ram)==ram


def harness(monkeypatch,build,*,dispatch=True,stale=False,release_failure=False,paused=False,backup_failure=False,expired=False,cancelled=False):
    ram=ready(build);m=Memory(ram);ad=SimpleNamespace(proc=SimpleNamespace(pid=123),debugger=lambda:m,paused_tids=[5] if paused else None)
    events=[];holds=0
    class Source:
        builds={build.scenario:build};path='owned.gcz'
        def __init__(self,path):pass
        def check(self):events.append('source check')
        def close(self):events.append('source close')
        def weapon(self,character,item):return {'path':'owned.plw','sha256':'evidence'}
    monkeypatch.setattr(I,'Source',Source)
    monkeypatch.setattr(I,'progress',lambda *args,**kw:None)
    @contextmanager
    def hold(ad):
        nonlocal holds
        holds+=1;events.append('hold')
        try:yield (123,456.0)
        finally:
            events.append('release')
            if release_failure and holds==2:raise RuntimeError('release failed')
            if dispatch and m.read(0x80800000+I.CONTROL,1)==b'\x02':
                m.ram[0x80800000+I.TASK-S.RAM_BASE:0x80800000+I.TASK-S.RAM_BASE+2]=b'\0\0'
                at=0x80800000+I.TASK-S.RAM_BASE
                struct.pack_into('>I',m.ram,at+4,0x80400000+I.IDLE[build.scenario]);m.ram[at+0x13]=1
                item=m.read(0x80800000+S.EQUIPPED_ITEM,1)[0]
                m.ram[I.LOADED-S.RAM_BASE:I.LOADED-S.RAM_BASE+2]=struct.pack('>H',0xf000+item)
    def backup(report):
        assert events[-1]=='release';assert not m.events
        events.append('backup')
        if backup_failure:raise OSError('backup storage unavailable')
        if stale:m.ram[S.INVENTORY+1-S.RAM_BASE]+=1
        return {'path':'backup.json','sha256':'receipt'}
    inp=I.ItemsIn(session_id='w-s',op='set',slot=0,item_id=1,quantity=1,
        expected_inventory_sha256=I.public_view(I.view(build,ram),(123,456.0))['inventory_sha256'])
    ticks=[0]
    def clock():
        ticks[0]+=2
        return ticks[0]+(100 if expired and 'backup' in events else 0)
    def prepare():
        if cancelled:raise RuntimeError('cancelled before dispatch')
    run=lambda **overrides:I.execute(ad,{'game_id':S.GAME_ID,'platform':'gamecube','_rom_path':'owned.gcz'},inp,backup,
                         hold=hold,sleep=lambda _:None,prepare=prepare,**{'clock':clock,**overrides})
    return m,events,run,inp


def test_transaction_backups_before_writes_and_native_completion(monkeypatch,build):
    m,events,run,inp=harness(monkeypatch,build)
    out=run()
    assert out['verified'] and out['native_transition_verified'] and not out['gameplay_verified']
    assert out['equipped']['item_id']==1 and out['equipped']['loaded_weapon_word']==0xf001
    assert events.count('hold')==events.count('release')==3
    assert events.index('backup')<events.index('hold',events.index('backup'))
    assert m.events[-1]==('write',0x80800000+I.CONTROL,b'\x02')


def test_stale_after_backup_does_not_write(monkeypatch,build):
    m,events,run,inp=harness(monkeypatch,build,stale=True)
    with pytest.raises(ValueError,match='while preparing'):run()
    assert not m.events
    assert events.count('hold')==events.count('release')


def test_post_dispatch_timeout_is_unknown_without_retry_or_byte_rollback(monkeypatch,build):
    m,events,run,inp=harness(monkeypatch,build,dispatch=False)
    out=run()
    assert out['outcome']=='unknown' and not out['verified'] and out['retry_allowed'] is False
    assert m.read(0x80800000+S.EQUIPPED_ITEM,1)==b'\x01'
    assert sum(a==0x80800000+I.CONTROL for _,a,_ in m.events)==1
    assert events.count('hold')==events.count('release')


def test_stale_sidebar_token_does_not_backup_or_write(monkeypatch,build):
    m,events,run,inp=harness(monkeypatch,build);inp.expected_inventory_sha256='old'
    with pytest.raises(ValueError,match='since the sidebar'):run()
    assert 'backup' not in events and not m.events


def test_durable_backup_precedes_artifact_and_is_exact(tmp_path):
    events=[]
    ctx=SimpleNamespace(config=SimpleNamespace(cache=tmp_path),artifact=lambda *args,**kwargs:events.append(args))
    result=I.durable_backup(ctx,{'plan':{'before':'abc'}})
    data=__import__('pathlib').Path(result['path']).read_bytes()
    assert I.digest(data)==result['sha256'] and events[0][1]==data
    assert json.loads(data)=={'plan':{'before':'abc'}}


def test_native_progress_requires_two_counter_advances():
    bss=0x80800000
    class Mem:
        def __init__(self,values):self.values=iter(values);self.last=0
        def read(self,a,n):
            assert (a,n)==(bss+I.FRAME_COUNTER,4)
            self.last=next(self.values,self.last)
            return struct.pack('>I',self.last)
    for values in ([5],[5,6]):
        with pytest.raises(ValueError,match='no bytes were written'):
            I.progress(Mem(values),bss,sleep=lambda _:None)
    with pytest.raises(ValueError,match='unexpectedly'):
        I.progress(Mem([5,0]),bss,sleep=lambda _:None)
    I.progress(Mem([5,5,6,8]),bss,sleep=lambda _:None)
    I.progress(Mem([0xfffffffe,0,1]),bss,sleep=lambda _:None)


def test_running_rejects_operator_pause_without_resuming():
    with pytest.raises(ValueError,match='pause was preserved'):
        I.running(SimpleNamespace(paused_tids=[5,6]))


def test_process_bound_sidebar_token_changes_on_pid_reuse(build):
    v=I.view(build,ready(build))
    assert I.public_view(v,(123,1))['inventory_sha256']!=I.public_view(v,(123,2))['inventory_sha256']


def test_active_inventory_callback_cannot_be_mutated(build):
    ram=mutated(ready(build),[(0x80800000+I.CURRENT_TASK,struct.pack('>I',0x80800000+I.TASK))])
    assert not I.view(build,ram)['editable']
    with pytest.raises(ValueError,match='still executing'):I.plan(build,ram,'set','inventory',0,1,1)


def test_post_stage_release_failure_returns_unknown_and_backup(monkeypatch,build):
    m,events,run,inp=harness(monkeypatch,build,release_failure=True)
    out=run()
    assert out['outcome']=='unknown' and not out['verified'] and out['retry_allowed'] is False
    assert out['backup']['path']=='backup.json' and 'release failed' in out['error']
    assert m.read(0x80800000+I.CONTROL,1)==b'\x02'
    assert m.events[-1]==('write',0x80800000+I.CONTROL,b'\x02')


def test_known_pause_rejects_before_backup_or_mutation(monkeypatch,build):
    m,events,run,inp=harness(monkeypatch,build,paused=True)
    with pytest.raises(ValueError,match='pause was preserved'):run()
    assert 'backup' not in events and not m.events


def test_readback_mismatch_rolls_back_including_close_phase(build):
    ram=ready(build);p=I.plan(build,ram,'set','inventory',0,1,1);m=Memory(ram)
    write=m.write
    def corrupt(a,data):
        write(a,data)
        if m.calls==1:m.ram[a-S.RAM_BASE+1]^=1
    m.write=corrupt
    with pytest.raises(RuntimeError,match='restored before native dispatch'):I.apply_staged(m,p)
    assert bytes(m.ram)==ram


def test_resource_preparation_failure_prevents_every_write(monkeypatch,build):
    m,events,run,inp=harness(monkeypatch,build)
    def fail(*args,**kwargs):raise OSError('weapon source unavailable')
    monkeypatch.setattr(I.Source,'weapon',fail)
    with pytest.raises(OSError,match='source unavailable'):run()
    assert not m.events


def test_backup_failure_prevents_mutation(monkeypatch,build):
    m,events,run,inp=harness(monkeypatch,build,backup_failure=True)
    with pytest.raises(OSError,match='backup storage unavailable'):run()
    assert not m.events and events.count('hold')==1


def test_fsync_failure_does_not_publish_backup_artifact(monkeypatch,tmp_path):
    events=[]
    ctx=SimpleNamespace(config=SimpleNamespace(cache=tmp_path),artifact=lambda *args,**kwargs:events.append(args))
    def fail(fd):raise OSError('disk full')
    monkeypatch.setattr(I.os,'fsync',fail)
    with pytest.raises(OSError,match='disk full'):I.durable_backup(ctx,{'plan':{}})
    assert not events


@pytest.mark.parametrize('condition',['expired','cancelled'])
def test_expired_or_cancelled_preparation_never_dispatches(monkeypatch,build,condition):
    m,events,run,inp=harness(monkeypatch,build,**{condition:True})
    with pytest.raises((TimeoutError,RuntimeError),match='expired|cancelled'):run()
    assert not m.events


@pytest.mark.parametrize('pointer',[0,0x80800000+I.TASK_TABLE-36,0x80800000+I.TASK_TABLE+8*36,0x80800000+I.TASK_TABLE+1])
def test_unknown_scheduler_task_pointer_prevents_writes(build,pointer):
    ram=mutated(ready(build),[(0x80800000+I.CURRENT_TASK,struct.pack('>I',pointer))])
    assert not I.view(build,ram)['editable']
    with pytest.raises(ValueError,match='task pointer is invalid'):I.plan(build,ram,'set','inventory',0,1,1)
