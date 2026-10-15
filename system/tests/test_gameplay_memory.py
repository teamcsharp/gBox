import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from gbox.gameplay_memory import Archive, install
from gbox import gameplay_replay as R
from tests.test_inspection_builds import Store

SESSION={'session_id':'pc-human','game_id':'pso','title':'Phantasy Star Online','mod':'sonic','started':100}


def test_durable_inputs_actions_search_and_idempotent_receipts(tmp_path):
    a=Archive(tmp_path)
    a.record(SESSION,'pad',{'events':[{'key':'a','down':True}]},at=101)
    a.record(SESSION,'mod_action',{'tool':'pso_inventory','weapon':'saber'},at=102,token='job1')
    assert not a.record(SESSION,'mod_action',{'weapon':'other'},at=103,token='job1')
    a.record(SESSION,'note',{'text':'Forest one completed, saber equipped'},at=104)
    b=Archive(tmp_path)
    assert len(b.events('pc-human'))==3
    assert b.events('pc-human',after=1)[0]['payload']['weapon']=='saber'
    assert b.search('Forest saber')[0]['run_id']=='pc-human'
    assert b.search('Forest saber',game_id='another-game')==[]
    assert b.runs('pso')[0]['replay_status']=='observations only; not a TAS'
    assert not b.status()['exact_replay']


def test_pad_flood_preserves_meaningful_note_and_bounded_summary(tmp_path):
    a=Archive(tmp_path);a.record(SESSION,'note',{'text':'Forest milestone'},at=100)
    for _ in range(300):a.record(SESSION,'pad',{'events':[{'key':'a'}]},at=101)
    assert 'Forest milestone' in a.search('Forest')[0]['summary']
    assert a.status()['events']==301


@pytest.mark.parametrize('kind,payload', [('unknown',{}),('pad',{'large':'x'*17000}),('note',{'n':float('nan')})])
def test_rejects_invalid_events(tmp_path,kind,payload):
    with pytest.raises(ValueError):Archive(tmp_path).record(SESSION,kind,payload)


def test_budget_preserves_old_runs_and_pauses_new_data(tmp_path):
    a=Archive(tmp_path);a.record(SESSION,'note',{'text':'keep'})
    a.max_bytes=1
    with pytest.raises(ValueError,match='budget'):a.record(SESSION,'pad',{})
    assert a.events('pc-human')[0]['payload']['text']=='keep'


def client(tmp_path):
    app=FastAPI();s=Store();s.put('session','pc-human',SESSION)
    s.put('session','pc-test',SESSION|{'session_id':'pc-test'});s.put('slabel','pc-test',{'owner':'agent'})
    install(app,s,SimpleNamespace(data_dir=tmp_path,gameplay_memory_enabled=True),lambda:'operator')
    return TestClient(app),app


def test_observe_excludes_test_and_unknown_session_without_false_saved_claim(tmp_path):
    c,app=client(tmp_path);body={'kind':'pad','payload':{'events':[]},'token':'one'}
    assert c.post('/api/gameplay-memory/runs/missing/observe',json=body).json()['saved'] is False
    assert c.post('/api/gameplay-memory/runs/pc-test/observe',json=body).json()['saved'] is False
    assert c.post('/api/gameplay-memory/runs/pc-human/observe',json=body).json()['saved'] is True
    assert c.post('/api/gameplay-memory/runs/pc-human/observe',json=body).json()['saved'] is True
    assert app.state.gameplay_memory.status()['events']==1
    assert c.get('/api/gameplay-memory').json()['demonstrations']['state']=='waiting_for_validated_native_run'


def test_streamed_native_archive_hash_download_validation_and_cleanup(tmp_path):
    c,app=client(tmp_path);data=b'BSV test fixture only'+bytes(100)
    r=c.post('/api/gameplay-memory/runs/pc-human/native',content=data)
    assert r.status_code==200,r.text
    import hashlib
    assert r.json()['sha256']==hashlib.sha256(data).hexdigest()
    assert c.get(r.json()['url']).content==data
    assert c.post('/api/gameplay-memory/runs/pc-human/native',content=b'x').status_code==422
    assert c.post('/api/gameplay-memory/runs/unknown/native',content=data).status_code==404
    assert not list((tmp_path/'gameplay-memory/native').glob('upload-*'))
    # Upload alone is not a claim the file can replay the game.
    assert app.state.gameplay_memory.runs()==[]


def test_native_prepare_has_unique_files_and_no_recording_for_agents(tmp_path,monkeypatch):
    cfg=SimpleNamespace(runtime=tmp_path,gameplay_memory_enabled=True,gameplay_native_replay_enabled=True)
    ad=SimpleNamespace(config=cfg,capture_gameplay=False)
    assert R.prepare(ad,'missing','core','rom')==[]
    ad.capture_gameplay=True
    exe=tmp_path/'retroarch';exe.write_bytes(b'exe')
    rom=tmp_path/'game';rom.write_bytes(b'rom')
    monkeypatch.setattr(R.shutil,'disk_usage',lambda p:SimpleNamespace(free=30*2**30))
    monkeypatch.setattr(R.subprocess,'run',lambda *a,**kw:SimpleNamespace(stdout='--bsvrecord',stderr=''))
    first=R.prepare(ad,str(exe),'core',str(rom));second=R.prepare(ad,str(exe),'core',str(rom))
    assert first!=second and first[0].startswith('--bsvrecord=')
    assert ad.gameplay_replay['replay_verified'] is False
    assert ad.gameplay_replay['content_identity']['sha256'] is None
    assert not list(tmp_path.glob('*.state'))


def test_recording_space_limit_does_not_delete_or_launch(tmp_path,monkeypatch):
    ad=SimpleNamespace(config=SimpleNamespace(runtime=tmp_path,gameplay_native_replay_enabled=True),capture_gameplay=True)
    monkeypatch.setattr(R.shutil,'disk_usage',lambda p:SimpleNamespace(free=1))
    assert R.prepare(ad,'exe','core','rom')==[]
    assert ad.gameplay_replay['state']=='paused'


def test_replay_metadata_rejects_wrong_types(tmp_path):
    c,_=client(tmp_path)
    assert c.post('/api/gameplay-memory/runs/pc-human/observe',json={'kind':'not-real','payload':{},'token':'x'}).status_code==422


def test_native_default_off_preserves_normal_save_workflow(tmp_path):
    ad=SimpleNamespace(config=SimpleNamespace(runtime=tmp_path),capture_gameplay=True)
    assert R.prepare(ad,'not-run','not-opened','not-opened')==[]
    assert ad.gameplay_replay['state']=='observations_only'
    assert not list(tmp_path.iterdir())


def test_halt_checks_file_identifier_and_leaves_another_replay_alone(tmp_path):
    import struct
    path=tmp_path/'input.bsv'
    path.write_bytes(struct.pack('<IIIIq',0x42535632,2,0,0,123)+bytes(16))
    calls=[]
    def cmd(text,**kw):
        calls.append(text);return 'GET_CONFIG_PARAM active_replay 456 2 100'
    assert not R.halt_owned(SimpleNamespace(cmd=cmd),path)
    assert calls==['GET_CONFIG_PARAM active_replay']
    def same(text,**kw):
        calls.append(text);return 'GET_CONFIG_PARAM active_replay 123 2 100'
    assert R.halt_owned(SimpleNamespace(cmd=same),path)
    assert calls[-1]=='HALT_REPLAY'


def test_server_input_and_physical_pad_are_archived_without_injection(cfg):
    from gbox.server import create_app
    app=create_app(cfg);s=app.state.store;s.put('session','pc-human',SESSION)
    c=TestClient(app,headers={'Authorization':f'Bearer {cfg.token()}'})
    payload={'events':[{'key':'a','down':True}]}
    assert c.post('/api/sessions/pc-human/input',json=payload).status_code==200
    assert c.post('/api/sessions/pc-human/pad',json=payload|{'source':'player'}).status_code==200
    assert len(app.state.gameplay_memory.events('pc-human'))==2
    assert c.get('/api/gameplay-memory').status_code==200

