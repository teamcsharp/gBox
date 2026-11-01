"""Native equipment targets one verified actor; shared patches never masquerade as player-two controls."""
import struct
from types import SimpleNamespace

import pytest
from gbox import pso_gc_live as G, pso_gc_extras as E, pso_controls as C, pso_modes as M
from gbox import pso_mods_tool as T
from gbox.registry import Unsupported
from test_pso_gc_live import RAM


def two_players(probed=True):
    ram=RAM()
    p=0x80DB62A0
    ram.word(G.PLAYER+4,p)
    ram.word(p,0x80430000)
    ram.word(p+0x18,G.VT_UPDATE-12)
    ram.put(p+0x1C,struct.pack('>H',1))
    ram.put(G.ENTITY_TABLE,struct.pack('>3I',ram.player,p,0))
    for a,b in E.EXTRA_GUARDS.items():ram.put(a,b)
    if probed:ram._pso_verified_player_slots={0,1}
    return ram,p


@pytest.mark.parametrize('fault',['unprobed','duplicate','identity','class','vtable','entity_table','null'])
def test_secondary_guards_refuse_before_any_write(fault):
    ram,p=two_players(fault!='unprobed')
    if fault=='duplicate':ram.word(G.PLAYER+4,ram.player)
    if fault=='identity':ram.put(p+0x1C,struct.pack('>H',0))
    if fault=='class':ram.word(p,0x80430100)
    if fault=='vtable':ram.word(p+0x18,0x80400000)
    if fault=='entity_table':ram.word(G.ENTITY_TABLE+4,0)
    if fault=='null':ram.word(G.PLAYER+4,0)
    with pytest.raises((Unsupported,RuntimeError)):
        G.GC(ram,player_index=1).hook()
    assert not ram.writes


def test_player_two_capability_is_provisional_until_session_probe():
    ram,p=two_players(False)
    game={'platform':'gamecube','title':'Phantasy Star Online Episode I & II Plus'}
    cap=C.capabilities(game,ram.read_memory,player_index=1,adapter=ram)
    assert cap['players'][1]['available'] and not cap['players'][1]['verified']
    assert not cap['supported'] and 'movement verification' in cap['reason']
    ram._pso_verified_player_slots={0,1}
    cap=C.capabilities(game,ram.read_memory,player_index=1,adapter=ram)
    assert cap['supported'] and cap['features']['equip'] and cap['features']['randomized']
    assert not any(cap['features'][k] for k in ('survival','revive','multi_equip','equip_any','always_hit','floor_spawn'))
    assert not ram.writes


def test_native_inventory_and_equip_use_only_selected_player():
    ram,p=two_players();m=E.Extras(ram,player_index=1,pin_player=True);calls=[]
    def inventory_call(batch):
        calls.extend(batch)
        return [0]*len(batch)
    m.call=inventory_call
    assert m.inventory()==[] and calls==[(G.F_INVENTORY,p,G.BUF)]
    rows=[{'id':G.ID_BASE,'code':'000100','equipped':False}]
    m.inventory=lambda:rows
    m.item_object=lambda item:0x80DC0000
    def equip_call(batch):
        calls.extend(batch);rows[0]['equipped']=True
        return [0]*len(batch)
    m.call=equip_call
    assert m.equip_id(G.ID_BASE)
    assert (G.F_EQUIP,p,0x80DC0000,0) in calls
    assert not any(ram.player in batch[1:] for batch in calls)
    assert not ram.writes


def test_only_command_instances_pin_actor_across_area_recreation():
    ram=RAM();reader=G.GC(ram);command=G.GC(ram,pin_player=True)
    reader.check();command.check()
    replacement=0x80DB62A0
    ram.put(replacement,ram.read_memory(ram.player,0x1200));ram.word(G.PLAYER,replacement)
    assert reader.check()==replacement
    with pytest.raises(Unsupported,match='selected PSO player changed'):command.check()


def test_player_randomizer_epochs_and_status_are_separate(monkeypatch):
    ram,p=two_players();m=G.GC(ram)
    a={'player_index':0,'on':True};b={'player_index':1,'on':False}
    M.new_epoch(m,a);M.new_epoch(m,b)
    assert M.epoch_valid(m,a) and M.epoch_valid(m,b)
    ram.put(M.MARKER+16,bytes(16))
    assert M.epoch_valid(m,a) and not M.epoch_valid(m,b)
    monkeypatch.setattr(M,'_states',{'session':a,('session',1):b})
    assert M.status('session')['on'] and not M.status('session',1)['on']


def test_randomizer_cleanup_refuses_recreated_actor_with_reused_item_ids():
    ram,p=two_players();m=E.Extras(ram,player_index=1,pin_player=True)
    state={'player_index':1,'_actor_pointer':p+0x4000,'original':{},'owned':{7:'weapon'}}
    M.new_epoch(m,state);ram.writes.clear()
    with pytest.raises(ValueError,match='identities are no longer trusted'):
        M.cleanup(m,state)
    assert state['owned']=={7:'weapon'}
    assert not ram.writes


def test_speed_capability_reports_adapter_requested_value():
    ram,_=two_players();ram._pso_coop_new_card=True;ram.autoplay_speed=8
    ram.set_autoplay_speed=lambda value:None
    cap=C.capabilities({'platform':'gamecube'},ram.read_memory,adapter=ram)
    assert cap['autoplay_speed']['requested']==8
    assert cap['features']['autoplay_speed']
    assert not cap['autoplay_speed']['achieved_verified']


@pytest.mark.parametrize('op',['survival','equip_any','always_hit','floor_spawn','multi_equip'])
def test_secondary_requests_cannot_apply_shared_or_primary_patches(monkeypatch,op):
    from gbox.tools import SESSIONS
    ram,p=two_players();monkeypatch.setitem(SESSIONS,'two',(ram,{'platform':'gamecube'}))
    with pytest.raises(Unsupported,match='player-one-only'):
        T.pso_mods(T.ModsIn(session_id='two',player_index=1,op=op),None)
    assert not ram.writes


def test_speed_only_reaches_dedicated_coop_adapter_and_never_claims_achieved_rate(monkeypatch):
    from gbox.tools import SESSIONS
    calls=[]
    ad=SimpleNamespace(set_autoplay_speed=lambda v:calls.append(v) or
                       {'requested':v,'input_delivered':True,'achieved_verified':False})
    monkeypatch.setitem(SESSIONS,'speed',(ad,{'platform':'gamecube'}))
    args=T.ModsIn(session_id='speed',op='autoplay_speed',multiplier=4)
    with pytest.raises(Unsupported):T.pso_mods(args,None)
    assert not calls
    ad._pso_coop_new_card=True
    result=T.pso_mods(args,None)['result']
    assert calls==[4] and result['requested']==4 and not result['achieved_verified']
    with pytest.raises(ValueError):T.pso_mods(T.ModsIn(session_id='speed',op='autoplay_speed',multiplier=3),None)
    assert calls==[4]
