import struct
from types import SimpleNamespace

import pytest
from gbox import pso_gc_adventure as A,pso_gc_live as G,pso_live as L,pso_mods_tool as T
from gbox.registry import Unsupported
from test_pso_gc_live import RAM


def memory():
    ram=RAM()
    for address,data in A.GUARDS.items():ram.put(address,data)
    for address,(before,_) in A.COLLISION.items():ram.put(address,bytes.fromhex(before))
    ram.put(A.DROP_ENTRY,A.DROP_ORIGINAL)
    ram.word(0x805D6060,0);ram.put(ram.player+0x32C,struct.pack('>H',27))
    return ram


@pytest.mark.parametrize('damage',['revision','online','entry','caller','occupied'])
def test_foreign_revision_hook_or_occupied_memory_is_preserved(damage):
    ram=memory()
    if damage=='revision':ram.put(0x80000007,b'\x01')
    if damage=='online':ram.word(G.PHASE,15)
    if damage=='entry':ram.put(A.DROP_ENTRY,b'bad!')
    if damage=='caller':ram.put(0x8011C3D4,b'bad!')
    if damage=='occupied':ram.put(A.CONFIG,b'somebody')
    with pytest.raises(Unsupported):A.Adventure(ram).enemy_drops(True,['000100'])
    assert ram.writes==[]


def test_enemy_pool_owns_only_its_scratch_and_entry_and_restores_original_routine():
    ram=memory();m=A.Adventure(ram);flush=[];m.flush=lambda addresses:flush.extend(addresses)
    result=m.enemy_drops(True,['000100','010122'],{'000100':35})
    assert result['verified'] and result['codes']==['000100','010122']
    assert ram.read_memory(A.CONFIG+32,4)==bytes.fromhex('00010023')
    assert ram.read_memory(A.CONFIG+32+12,4)==b'\xff'*4
    assert A.DROP_ENTRY in flush
    assert m.enemy_drops(False)['verified'] and ram.read_memory(A.DROP_ENTRY,4)==A.DROP_ORIGINAL
    assert A.CODE_ADDRESS>=G.END and A.CONFIG+32+20*20<A.HEADER
    assert all(a==A.DROP_ENTRY or G.QUEUE<=a<G.END or a==G.VT_UPDATE or A.CODE_ADDRESS<=a<A.REGION_END for a,_ in ram.writes)


def test_collision_preflights_every_instruction_before_any_write_and_restores_exactly():
    ram=memory();m=A.Adventure(ram);m.flush=lambda addresses:None
    last=list(A.COLLISION)[-1];ram.put(last,b'bad!')
    with pytest.raises(Unsupported):m.walk_through(True)
    assert not ram.writes
    ram.put(last,bytes.fromhex(A.COLLISION[last][0]))
    assert m.walk_through(True)['verified'] and m.walk_state()
    assert m.walk_through(False)['verified'] and not m.walk_state()
    for address,(original,_) in A.COLLISION.items():assert ram.read_memory(address,4).hex()==original


def test_partial_collision_state_is_reported_instead_of_silently_treated_as_off():
    ram=memory();m=A.Adventure(ram);m.flush=lambda addresses:None
    address=next(iter(A.COLLISION));ram.put(address,bytes.fromhex(A.COLLISION[address][1]))
    with pytest.raises(Unsupported,match='partially applied'):m.walk_state()
    assert not ram.writes
    assert m.walk_through(False)['verified'] and not m.walk_state()


def test_boss_choices_use_episode_and_current_floor_without_installing_a_hook():
    ram=memory();m=A.Adventure(ram)
    ram.word(G.FLOOR,8)
    assert m.destinations()['episode']==1 and m.destinations()['default']=='dark_falz'
    ram.word(0x805D6060,1);ram.word(G.FLOOR,1)
    assert m.destinations()['episode']==2 and m.destinations()['default']=='barba_ray'
    assert not ram.writes
    with pytest.raises(ValueError,match='current episode'):m.teleport_boss('dragon')
    assert not ram.writes


def test_boss_travel_acknowledges_loader_and_player_in_one_batch_but_does_not_claim_arrival():
    ram=memory();m=A.Adventure(ram);calls=[]
    def execute(batch):
        calls.extend(batch);ram.word(A.TRAVEL_STATE+12,batch[0][2]);ram.word(A.TRAVELLING,1);return [0]*len(batch)
    m.call=execute
    r=m.teleport_boss('dragon')
    assert r['verified'] and r['requested'] and not r['arrived']
    assert calls==[(A.SET_TARGET,A.TRAVEL_STATE,11),(A.BEGIN_TRAVEL,),(A.WARP,ram.player,11)]
    assert m.travel_status()['state']=='loading'
    ram.word(G.FLOOR,11);assert m.travel_status()['state']=='loading'
    ram.word(A.TRAVELLING,0);assert m.travel_status()['state']=='arrived'
    assert not ram.writes


@pytest.mark.parametrize('reason',['dead','transition'])
def test_boss_travel_refuses_dead_player_and_overlapping_transitions(reason):
    ram=memory();m=A.Adventure(ram)
    if reason=='dead':ram.put(ram.player+0x32C,bytes(2))
    else:ram.word(A.TRAVELLING,1)
    m.call=lambda *args:pytest.fail('No native travel should execute')
    with pytest.raises(ValueError):m.teleport_boss('dragon')
    assert not ram.writes


def test_pool_validation_cannot_substitute_unknown_or_duplicate_codes():
    rows=[{'code':'000100','max_grind':35},{'code':'010122'}]
    assert A.validate_pool(rows,['000100'],True)==(['000100'],{'000100':35})
    assert A.validate_pool(rows,['000100'],False)==(['000100'],{})
    for codes in ([],['ffffff'],['000100']*2,['000100']*21):
        with pytest.raises(ValueError):A.validate_pool(rows,codes,True)


def test_rpc_checks_catalog_and_deadline_before_enemy_drop_mutation(monkeypatch):
    ram=memory();ctx=SimpleNamespace(pso_expires=0)
    monkeypatch.setattr(L,'catalog',lambda *args:[{'code':'000100','max_grind':35}])
    with pytest.raises(TimeoutError):L.gamecube(T.ModsIn(session_id='x',op='enemy_drops',codes=['000100']),ctx,ram)
    assert not ram.writes
    with pytest.raises(ValueError,match='disc database'):
        L.gamecube(T.ModsIn(session_id='x',op='enemy_drops',codes=['ffffff']),ctx,ram)
    assert not ram.writes
