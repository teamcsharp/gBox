import json
import struct
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from gbox import pso_rom_export as P, romexport as R, romexport_recovery as Q
from gbox.config import Config
from gbox.formats.lz import prs_compress
from gbox.server import create_app


def cfg(tmp_path):
    return SimpleNamespace(cache=tmp_path/'cache', data_dir=tmp_path/'data', runtime=tmp_path/'runtime')


def tables():
    indexes=bytearray(0x3C00);values=bytearray(0x4000)
    struct.pack_into('<I',indexes,0x3BFC,0x8C008500)
    struct.pack_into('<I',values,0x3FFC,0x8C004100)
    return bytes(indexes),bytes(values)


@pytest.mark.parametrize('data',[b'A'*3000,bytes(range(256))*8,b'abcdXYZabcdXYZabcdXYZ'])
def test_codec_rewrite_preserves_every_other_byte(data):
    packed=prs_compress(data)
    for offset in [0,len(data)//2,len(data)-2]:
        target=bytearray(data);target[offset:offset+2]=b'?!'
        result=P._rewrite(packed,bytes(target))
        assert P._unpack(result,len(data))==target
    assert P._unpack(P._rewrite(packed,data),len(data))==data
    indexes,values=tables()
    encoded,updated=P.encode(data,indexes,0x12345678)
    assert P.decode(encoded,updated,values)==data


def test_fixup_restores_obscured_word_before_decode():
    indexes,values=map(bytearray,tables())
    raw=bytes(range(100))*10;packed=bytearray(prs_compress(raw))
    indexes[0x100:0x104]=bytes([2,0,0,0]);values[0x100:0x104]=packed[8:12];packed[8:12]=b'BAD!'
    encoded=struct.pack('<II',len(raw),42)+P.PSOV2Cipher(42).crypt(packed)[:len(packed)]
    assert P.decode(encoded,indexes,values)==raw


@pytest.mark.parametrize('kind',['pointer','value_pointer','size','short','backref'])
def test_corrupt_inputs_fail_with_bounded_errors(kind):
    indexes,values=map(bytearray,tables());encoded,_=P.encode(b'hello',indexes,1)
    if kind=='pointer':struct.pack_into('<I',indexes,0x3BFC,0)
    if kind=='value_pointer':struct.pack_into('<I',values,0x3FFC,0xFFFFFFFF)
    if kind=='size':encoded=struct.pack('<I',P.MAX_EXECUTABLE+1)+encoded[4:]
    if kind=='short':encoded=b'123'
    if kind=='backref':
        with pytest.raises(ValueError):P._unpack(b'\x02\xf8\xff',4)
        return
    with pytest.raises(ValueError):P.decode(encoded,indexes,values)


def test_unknown_disc_refused_before_compression():
    with pytest.raises(ValueError,match='verified US v2'):
        P.prepare(SimpleNamespace(read=lambda name:b'wrong revision'))


def test_empty_selection_has_choices_and_concrete_recovery(tmp_path):
    c=cfg(tmp_path);folder=c.cache/'mods'/'game'/'built';folder.mkdir(parents=True)
    (folder/'.gbox-mod.json').write_text(json.dumps({'name':'built','title':'My native build'}))
    saved=[{'id':'saved','game_id':'game','title':'My saved mod','calls':[]}]
    result=Q.plan(c,{'game_id':'game','platform':'gamecube'},saved=saved)
    assert not result['ready'] and result['status']=='needs_selection'
    assert {o['id'] for o in result['options']}=={'original','saved','built'}
    assert result['issues'][0]['code']=='selection_required'
    with pytest.raises(ValueError,match='Choose a saved mod'):Q.require_ready(result)
    assert not c.data_dir.exists()


def test_live_only_and_mixed_game_require_writer(tmp_path):
    game={'game_id':'game','platform':'dreamcast'}
    live={'id':'live','game_id':'game','calls':[{'tool':'pso_mods','input':{'op':'meseta'}}]}
    result=Q.plan(cfg(tmp_path),game,[live]);assert not result['ready']
    assert any(i['code']=='writer_required' for i in result['issues'])
    wrong={'game_id':'other','calls':[{'tool':'@launch','input':{'mod':'build'}}]}
    assert not Q.plan(cfg(tmp_path),game,[wrong])['ready']


def test_pso_native_patch_classification_and_combination_guard(tmp_path):
    mod={'game_id':'game','calls':[{'tool':'pso_mods','input':{'op':'crit_always','on':True}}]}
    c=cfg(tmp_path);g={'game_id':'game','platform':'dreamcast'}
    assert Q.plan(c,g,[mod])['ready']
    assert R.classify(mod)[0]['kind']=='pso_code_patch'
    assert not Q.plan(c,g|{'platform':'gamecube'},[mod])['ready']
    assert not Q.plan(c,g,[mod],names=['another'])['ready']
    with pytest.raises(ValueError,match='alone'):
        R.export(c,g,Path('unused'),mods=[mod],changes={'@image':{'patch':[]}})


def test_selection_preserves_named_saved_and_file_mods():
    saved=[{'id':'saved','game_id':'game','calls':[]}]
    assert Q.selection({'mod_id':'saved','mods':['saved','native']},saved)==('game',saved,['native'])
    with pytest.raises(ValueError,match='no longer exists'):Q.selection({'mod_id':'gone'},saved)


def test_api_preflight_rejects_empty_before_queuing_and_accepts_selection(tmp_path):
    config=Config(data_dir=tmp_path);app=create_app(config);store=app.state.store
    store.upsert_catalog([{'game_id':'game','title':'RE2','platform':'gamecube','source_paths':['test.iso'],
                           'format':'iso','profile_id':'game','launch':{}}])
    store.put('mod','saved',{'id':'saved','game_id':'game','title':'Ammo','calls':[{'tool':'re_mods','input':{'op':'infinite_ammo'}}]})
    with TestClient(app,headers={'Authorization':'Bearer '+config.token()}) as client:
        before=len(store.all('job'))
        plan=client.post('/api/romexport/plan',json={'game_id':'game'})
        assert plan.status_code==200 and not plan.json()['ready']
        failed=client.post('/api/romexport',json={'game_id':'game'})
        assert failed.status_code==422 and len(store.all('job'))==before
        assert failed.json()['detail']['plan']['options'][1]['id']=='saved'
        result=client.post('/api/romexport',json={'mod_id':'saved'})
        assert result.status_code==200,result.text
        assert result.json()['input']['mod_id']=='saved'


def test_agent_does_not_repeat_empty_export():
    from gbox.agent import Agent
    # Find the registered implementation without constructing a model client.
    calls=[]
    result={'ready':False,'status':'needs_selection','options':[]}
    stub=SimpleNamespace(_job=lambda *args,**kwargs:(calls.append(args) or {'state':'succeeded','output':{'result':result}}))
    assert Agent.rom_export(stub,game_id='game')==result
    assert len(calls)==1 and calls[0][1]['op']=='plan'


def test_original_export_is_explicit_and_preserves_source_and_previous_export(tmp_path):
    c=cfg(tmp_path);g={'game_id':'game','title':'RE2','platform':'gamecube'}
    source=tmp_path/'original.gcz';source.write_bytes(b'owned original bytes'*100)
    assert not Q.plan(c,g)['ready']
    assert Q.plan(c,g,original=True)['ready']
    assert not Q.plan(c,g,names=['changed'],original=True)['ready']
    first=Q.export_original(c,g,source);second=Q.export_original(c,g,source)
    assert first['name']!=second['name']
    assert (Path(first['dir'])/first['image']).read_bytes()==source.read_bytes()
    assert first['mode']=='original' and not first['patches']
    assert 'Original library file:' in (Path(first['dir'])/'README.txt').read_text()
    assert 'Bootable image:' not in (Path(first['dir'])/'README.txt').read_text()


def test_original_folder_entry_is_not_misrepresented_as_complete_game(tmp_path):
    source=tmp_path/'EBOOT.BIN';source.write_bytes(b'not a complete disc')
    with pytest.raises(ValueError,match='complete library'):
        Q.export_original(cfg(tmp_path),{'game_id':'game'},source)

