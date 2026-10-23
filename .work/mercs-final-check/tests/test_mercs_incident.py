"""Damage receipts retain exact bounded witnesses and the navigation leading to the observed HP loss."""
import base64
import hashlib
import json
import random
import zlib
from types import SimpleNamespace

import pytest

from gbox import player_damage as P
from gbox.mercs import damage as D, incident as I
from test_player_damage import SID, event, observer, snap, tick, ledger, provider


def test_ram_witness_retains_exact_bytes_hashes_and_stays_read_only_within_budget():
    from test_re5_combat import world, PL
    memory, s = world(), snap(900)
    s['enemies'] = [dict(s['enemies'][0],ptr=0x30800000+i*0x10000,pos=[i*100,0,100]) for i in range(4)]
    original = memory.rd
    reads = []
    def read(address, count):
        reads.append((address, count))
        return original(address, count) if count == 4 else random.Random(address).randbytes(count)
    memory.rd = read
    s['ground_mines'] = {0x30900000 + i*0x10000: {'pos': [0,0,0]} for i in range(4)}
    writes = list(memory.writes)
    witness = I.ram_witness(memory, 'BLUS30491', s)
    assert witness['state'] == 'done' and witness['atomic'] is False
    assert witness['truncated_to_budget'] and witness['omitted_spans']
    assert sum(span['size'] for span in witness['spans']) <= 48*1024
    assert memory.writes == writes
    for span in witness['spans']:
        raw = zlib.decompress(base64.b64decode(span['data_b64'], validate=True))
        assert len(raw) == span['size']
        assert raw == random.Random(int(span['address'],16)).randbytes(span['size'])
        assert hashlib.sha256(raw).hexdigest() == span['sha256']
    assert witness['spans'][0]['address'] == hex(PL)
    assert 'reloads' in witness['native_save_state']


def test_ram_witness_reports_identity_change_and_short_read_without_claiming_atomic_state():
    from test_re5_combat import world, PL
    memory = world()
    original = memory.rd
    captured = False
    def read(address, size):
        nonlocal captured
        if address == PL and size == 0x3000:
            captured = True
        if captured and address == 0x30300028 and size == 4:
            return (PL+16).to_bytes(4,'big')
        return original(address,size)
    memory.rd = read
    witness = I.ram_witness(memory, 'BLUS30491', snap())
    assert witness['state'] == 'partial' and 'identity changed' in witness['error']
    assert witness['spans'] and witness['atomic'] is False
    memory = world(); original = memory.rd
    memory.rd = lambda address, size: b'x' if size == 0x3000 else original(address,size)
    witness = I.ram_witness(memory, 'BLUS30491', snap())
    assert witness['state'] == 'failed' and 'short player read' in witness['error']
    assert not witness['spans']


def test_damage_history_retains_stuck_intent_qte_mines_and_combo_before_hit():
    events, stats = [], {'rounds':1, 'stuck':'wall ahead', 'nav_recovery':'backtrack exit'}
    obs = observer(events, stats)
    bot = SimpleNamespace(plan=lambda: {'phase':'route', 'target':{'kind':'bonus','id':3},
        'note':'blocked crossing', 'route':[[100,0,0],[100,0,100]]},
        mines=SimpleNamespace(events=[{'kind':'placed','at':1,'position':[0,0,0]}]))
    s = snap()
    for when in [1.,1.25,1.5]:
        s['combo'],s['kills'],s['prompt']=12,14,{'token':'mash:circle','label':9}
        obs.before(s,'playing',None,bot=bot,held=['lup'],now=when)
        obs.after(s,'playing',now=when)
    s['player']['hp']=900
    result=obs.before(s,'playing',None,bot=bot,held=['circle'],now=1.75)
    history=result['preceding_history']
    assert [row['at'] for row in history] == [1.,1.25,1.5,1.75]
    assert all(row['pos']==[0,0,0] and row['navigation']['stuck']=='wall ahead' for row in history)
    assert history[0]['plan']['target']=={'kind':'bonus','id':3}
    assert history[0]['mine_events'][0]['kind']=='placed'
    assert history[-1]['combo']==12 and history[-1]['held']==['circle']
    assert history[-1]['prompt']['token']=='mash:circle'
    assert 'cyan past path' in result['map_at_observation_svg']
    assert result['cause']==result['self_damage']=='unknown'


@pytest.mark.parametrize('transition',['player','round','geometry','loading','gap'])
def test_new_player_round_geometry_or_unknown_interval_cannot_inherit_a_previous_path(transition):
    events,stats=[],{'rounds':1}
    obs=observer(events,stats)
    s=snap();s['nav']=SimpleNamespace(sig='old-mesh')
    tick(obs,s,1.)
    s['player']['pos']=[999,0,999]
    if transition=='player': s['player']['ptr']+=16
    elif transition=='round': stats['rounds']=2
    elif transition=='geometry': s['nav']=SimpleNamespace(sig='new-mesh')
    elif transition=='loading': tick(obs,{},1.1,screen='loading')
    when=5. if transition=='gap' else 1.3
    tick(obs,s,when)
    s['player']['hp']=900
    result=tick(obs,s,when+.3)
    assert result is not None
    assert all(row['pos']==[999,0,999] for row in result['preceding_history'])
    assert len(result['preceding_history'])==2


def test_compressed_verbose_event_fits_wire_budget_and_freezes_all_original_context(tmp_path):
    box=D.Outbox(tmp_path,SID,None,{},threaded=False)
    s=snap(900)
    s['ground_mines']={str(0x30900000+i*0x10000): {'pos':[i*20,0,i*20], 'placed':True} for i in range(100)}
    history=[{'at':i/5,'pos':[100,0,100],'held':['lup'],'plan':{'route':[[0,0,0]]*8},
              'navigation':{'stuck':'wall ahead '*30}} for i in range(60)]
    svg='<svg>'+('<path d="M0,0 L10,10" stroke="#64748b"/>'*600)+'</svg>'
    e=event(snapshot=s,preceding_history=history,map_at_observation_svg=svg,logic={'route':'bonus '*25000},
        ram_witness={'state':'done','spans':[{'data_b64':base64.b64encode(random.Random(3).randbytes(48000)).decode()}]},
        frame_at_hit={'state':'cached-at-observation','at':99.9,
                      'data_b64':base64.b64encode(b'\xff\xd8'+b'x'*120000+b'\xff\xd9').decode()})
    box.emit(e)
    saved=json.loads(box.files()[0].read_bytes())
    assert len(box.files()[0].read_bytes())<=D.EVENT_MAX and not box.capacity_blocked
    assert saved['packed_context']['format']=='zlib+base64-json/1'
    assert 'data_b64' not in saved['frame_at_hit']
    expanded=I.unpack_context(saved)
    assert expanded['preceding_history']==history and expanded['snapshot']==s
    assert expanded['map_at_observation_svg']==svg and expanded['logic']==e['logic']
    assert P.validate(saved,SID)
    packet=P.freeze(None,SID,saved,100.1)
    receipt=packet['sources']['ram_fields']['data']
    assert receipt['preceding_history']==history and receipt['map_at_observation_svg']==svg
    assert receipt['ram_witness']==e['ram_witness']
    assert packet['context_compression']['sha256']==saved['packed_context']['sha256']
    assert 'packed_context' not in e and e['frame_at_hit']['data_b64']


def test_packed_context_rejects_corruption_unbounded_expansion_and_header_overrides():
    packed=I.pack_context(event(logic={'route':'repeat '*1000}))
    assert 'packed_context' in packed
    packed['packed_context']['sha256']='0'*64
    with pytest.raises(ValueError,match='SHA256'): P.validate(packed,SID)
    packed=I.pack_context(event(logic={'route':'repeat '*1000}))
    packed['packed_context']['uncompressed_bytes']=I.CONTEXT_MAX+1
    with pytest.raises(ValueError,match='budget'): I.unpack_context(packed)
    malicious=json.dumps({'loss':0}).encode()
    packed['packed_context'].update(uncompressed_bytes=len(malicious),fields=['loss'],
        sha256=hashlib.sha256(malicious).hexdigest(),data_b64=base64.b64encode(zlib.compress(malicious)).decode())
    with pytest.raises(ValueError,match='fields'): I.unpack_context(packed)


def test_damage_materialization_attaches_the_worker_map_with_preceding_path(ledger):
    store,create,_ = ledger
    svg=I.map_svg(snap(900),[{'pos':[0,0,0]},{'pos':[100,0,100]}],{'route':[[200,0,200]]})
    e=event(preceding_history=[{'pos':[0,0,0]},{'pos':[100,0,100]}],map_at_observation_svg=svg)
    P.ingest(store,SID,e,provider(),now=100.1)
    row=P.materialize(store,create,lambda *args:pytest.fail('RPCS3 checkpoint reload'),P.key(SID,e['event_id']))
    assert row['state']=='done' and row['save_state']['state']=='skipped_disruptive'
    image=next(a for a in row['attachments'] if a['type']=='image/svg+xml')
    assert store.read_artifact(image['sha256']).decode()==svg
    moment=json.loads(store.read_artifact(row['evidence']['moment']['sha256']))
    assert moment['sources']['ram_fields']['data']['preceding_history']==e['preceding_history']
