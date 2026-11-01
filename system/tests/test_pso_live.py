import time
import uuid
from types import SimpleNamespace

import pytest
from gbox import pso_live as L, pso_mods_tool as T, tools
from gbox.registry import Ctx, Unsupported
from gbox.config import Config


def body(op='floor_clear',**args):
    return {'command_id':str(uuid.uuid4()),'expires':time.time()+8,'input':{'op':op,**args}}


def test_modes_reuses_cached_measured_speed_without_a_native_clock_call(monkeypatch):
    from gbox import pso_controls as C, pso_gc_live as G, pso_gc_extras as E, pso_gc_adventure as A
    from test_pso_controls import measured_speed_adapter
    ad = measured_speed_adapter()
    ad.read_memory = lambda *_: b''
    ad.write_memory = lambda *_: pytest.fail('Status must not write game memory')
    ad.set_autoplay_speed = lambda *_: pytest.fail('Status must not change speed')
    monkeypatch.setattr(C.time, 'monotonic', lambda: 100.)
    monkeypatch.setattr(G.GC, 'check', lambda *_: 1)
    monkeypatch.setattr(E.Extras, 'check', lambda *_: 1)
    monkeypatch.setattr(E.Extras, 'u32', lambda *_: 0)
    monkeypatch.setattr(A.Adventure, 'travel_status', lambda *_: {})
    monkeypatch.setattr(G.GC, 'call', lambda *_: pytest.fail('Status must not enqueue a native call'))
    result = L.gamecube(T.ModsIn(session_id='buddy', op='modes'), None, ad)
    assert result['autoplay_speed']['measurement_verified']
    assert result['autoplay_speed']['actual'] == 1 and result['autoplay_speed']['requested'] == 10
    assert not result['autoplay_speed']['achieved_verified']


@pytest.mark.parametrize('mutation',[lambda b:b.update(expires=0),lambda b:b.update(expires=float('nan')),
    lambda b:b['input'].update(op='write_memory'),lambda b:b['input'].update(address=0x80000000),
    lambda b:b['input'].update(session_id='other'),lambda b:b.update(command_id='invalid')])
def test_live_input_refuses_arbitrary_or_expired_commands(mutation):
    request=body();mutation(request)
    with pytest.raises((ValueError,TypeError)):
        L.validate('sid',request)


def test_once_only_receipts_and_parameter_conflicts(monkeypatch,tmp_path):
    ctx=Ctx(Config(data_dir=tmp_path,granted_permissions=['memory_write']))
    monkeypatch.setitem(tools.SESSIONS,'sid',(object(),{'title':'Phantasy Star Online','platform':'gamecube'}))
    calls=[]
    monkeypatch.setattr(T,'pso_mods',lambda inp,ctx: calls.append(inp.op) or {'result':{'removed':2,'verified':True}})
    request=body()
    a=L.execute('sid',request,ctx);b=L.execute('sid',request,ctx)
    assert a==b and calls==['floor_clear'] and a['command_id']==request['command_id']
    request['input']['on']=False
    with pytest.raises(ValueError,match='different parameters'):
        L.execute('sid',request,ctx)


def test_failure_is_not_executed_again(monkeypatch,tmp_path):
    ctx=Ctx(Config(data_dir=tmp_path,granted_permissions=['memory_write']))
    monkeypatch.setitem(tools.SESSIONS,'fail',(object(),{'title':'Phantasy Star Online','platform':'gamecube'}))
    calls=[]
    def fail(*args):
        calls.append(1);raise RuntimeError('outcome unknown')
    monkeypatch.setattr(T,'pso_mods',fail);request=body()
    for _ in range(2):
        with pytest.raises(RuntimeError,match='outcome unknown'):L.execute('fail',request,ctx)
    assert calls==[1]


@pytest.mark.parametrize('op,player,records',[('give',0,1),('give',1,0),('autoplay_speed',0,0)])
def test_receipts_keep_selected_player_actions_out_of_legacy_primary_replay(monkeypatch,tmp_path,op,player,records):
    from gbox import gameplay_actions
    ctx=Ctx(Config(data_dir=tmp_path,granted_permissions=['memory_write']))
    monkeypatch.setitem(tools.SESSIONS,'selected-record',(object(),{'title':'Phantasy Star Online','platform':'gamecube'}))
    captured=[]
    monkeypatch.setattr(gameplay_actions,'record',lambda *args:captured.append(args))
    monkeypatch.setattr(T,'pso_mods',lambda inp,ctx:{'result':{'verified':True}})
    request=body(op,player_index=player)
    result=L.execute('selected-record',request,ctx)
    assert result['command_id']==request['command_id']
    assert len(captured)==records


def test_worker_permission_and_missing_context_are_enforced(monkeypatch,tmp_path):
    monkeypatch.setitem(tools.SESSIONS,'permission',(object(),{'title':'Phantasy Star Online','platform':'gamecube'}))
    with pytest.raises(Unsupported):L.execute('permission',body(),None)
    with pytest.raises(PermissionError):L.execute('permission',body(),Ctx(Config(data_dir=tmp_path)))


def test_catalog_delay_checks_expiry_before_native_mutation(monkeypatch):
    from gbox import pso_gc_live
    calls=[]
    monkeypatch.setattr(pso_gc_live,'GC',lambda ad,**kw:SimpleNamespace(check=lambda:None,floor_spawn=lambda *a:calls.append(a)))
    ctx=SimpleNamespace(pso_expires=time.time()+8)
    def late(*args):
        ctx.pso_expires=0
        from gbox.psoitems import CATALOG_SCHEMA
        return [{'code':'000100','schema':CATALOG_SCHEMA}]
    monkeypatch.setattr(L,'catalog',late)
    with pytest.raises(TimeoutError):L.gamecube(T.ModsIn(session_id='x',op='floor_spawn',code='000100'),ctx,None)
    assert calls==[]


def test_server_authorization_requires_live_pso_current_worker_and_permission(tmp_path):
    from pathlib import Path
    import hashlib
    sources={}
    for name in ('pso_live.py','pso_rehook.py','pso_accuracy.py','pso_gc_live.py','pso_gc_extras.py','pso_gc_adventure.py','pso_modes.py','psoitems.py','pso_loadouts.py','tools.py','pso_mods_tool.py','pso_controls.py'):
        sources['gbox/'+name]=hashlib.sha256((Path(L.__file__).parent/name).read_bytes().replace(b'\r\n',b'\n')).hexdigest()
    rows={('session','w-s'):{'state':'running','game_id':'gc'},('worker','w'):{'last_seen':time.time(),'build_sources':sources}}
    store=SimpleNamespace(get=lambda kind,key:rows.get((kind,key)),catalog_get=lambda key:{'title':'Phantasy Star Online','platform':'gamecube'})
    cfg=Config(data_dir=tmp_path,granted_permissions=['memory_write'])
    assert L.authorize(store,cfg,'w-s',body()).op=='floor_clear'
    cfg.granted_permissions=[]
    with pytest.raises(PermissionError):L.authorize(store,cfg,'w-s',body())
    assert L.authorize(store,cfg,'w-s',body('capabilities')).op=='capabilities'
    sources.pop('gbox/pso_gc_live.py')
    with pytest.raises(ValueError,match='safe refresh'):L.authorize(store,cfg,'w-s',body())
    rows[('session','w-s')]['state']='ended'
    with pytest.raises(ValueError,match='ended'):L.authorize(store,cfg,'w-s',body())
