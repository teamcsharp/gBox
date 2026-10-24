"""Two persisted authorities exchange synthetic closed evidence, never game inputs."""
import copy
import gzip
import json
import threading
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from gbox.mercs import evidence_sync as E
from gbox.mercs.atlas import NavigationAtlas
from gbox.mercs.notebook import Notebook
from gbox.mercs.reviewer import Reviewer
from gbox.mercs.titles.re5_nav import NavMesh
from gbox.models import WorkerInfo
from gbox.server import create_app
from gbox.store import Store,canon,sha256

AUTH='a'*64
KEY='b'*64
WID='c'*16
SID=WID+'-'+'d'*32
RID='f'*32
TITLE='BLUS30491'
GID=E.TITLES[TITLE][0]


def source(root,*,title=TITLE,rid=RID,outcome='completed',note=True):
    atlas=NavigationAtlas(root/'mercs'/'navigation',title)
    if title==TITLE:
        mesh=NavMesh([(0.,0.,0.),(1000.,0.,0.),(1000.,0.,1000.),(0.,0.,1000.)],
                     [(0,1,2),(0,2,3)],[[(1,2,1.)],[(0,0,1.)]])
        stage=atlas.stage(mesh);full=rid+':'+stage;units=100
    else:
        stage=atlas.observed_stage('G4BE08-room-0400-geometry-unknown',units_per_m=1000)
        full=rid;units=1000
    meta={'mode':'mercenaries','character':'Synthetic fixture','source_session_id':SID,
          'source_autoplay_job_id':'1'*32}
    atlas.begin(full,stage,100.,meta)
    for at,x in ((100.,100.),(100.5,200.),(101.,300.)):
        frame={'title':title,'units_per_m':units,'units':'cm' if units==100 else 'native',
               'player':{'pos':[x,0.,100.],'hp':1000},'enemies':[],
               'clock':{'score':1000,'kills':1,'combo':1},'plan':{'phase':'gather_time'}}
        atlas.sample(full,at,frame,inputs=['lup'])
    atlas.event(full,101.,'checkpoint_acquired',{'key':'time:300:0:100','pos':[300.,0.,100.],
                'evidence':{'clock_gain_s':30}})
    atlas.finish(full,101.,outcome,{'units_per_m':units})
    atlas.close()
    if note:
        notebook=Notebook(root/'mercs',title)
        notebook.finish(stage,'mercenaries','Synthetic fixture',outcome,
                        {'score':60000,'kills':1,'bonuses_taken':1,'source_session_id':SID,
                         'round_semantic_recalled':99,'knowledge_delivered':True},round_id=rid)
        with notebook.connect() as db:db.execute('UPDATE rounds SET ts=1234 WHERE id=?',(rid,))
    session={'session_id':SID,'game_id':E.TITLES[title][0]}
    return full,session


@pytest.fixture
def pair(cfg,tmp_path,monkeypatch):
    monkeypatch.setattr(Notebook,'publish',lambda *a:None)
    local=tmp_path/'local';rid,session=source(local)
    store=Store(local);store.put('session',SID,session)
    app=create_app(cfg)
    client=TestClient(app,headers={'Authorization':'Bearer '+cfg.token(),'x-gbox-federation-key':KEY},
                      raise_server_exceptions=False)
    response=client.post('/api/federation/'+AUTH+'/snapshot',json={'epoch':'e'*32,
        'worker':WorkerInfo(id=WID,name='Synthetic owned local fixture',os='windows',tools=[]).model_dump(),
        'sessions':[session|{'adapter':'rpcs3','state':'ended','detail':{}}]})
    assert response.status_code==200,response.text
    bridge=SimpleNamespace(cfg=cfg.model_copy(update={'data_dir':local}),store=store,authority=AUTH,
        remote='http://central.test',_headers=lambda:{},stop=threading.Event(),active_worker_id=WID)
    return SimpleNamespace(cfg=cfg,local=local,rid=rid,session=session,app=app,client=client,
                           bridge=bridge,receiver=app.state.mercs_evidence_sync)


def upload(pair,bundle=None):
    if bundle is None:bundle,raw=E.export_round(pair.local,TITLE,pair.rid,pair.session)
    else:raw=canon(bundle)
    data=gzip.compress(raw,mtime=0)
    pieces=[data[i:i+E.CHUNK] for i in range(0,len(data),E.CHUNK)]
    manifest={'sha256':sha256(raw),'bytes':len(raw),'title':bundle['title'],'source':bundle['source'],
              'chunks':[{'sha256':sha256(part),'size':len(part)} for part in pieces]}
    for part in pieces:
        response=pair.client.put('/api/federation/'+AUTH+'/evidence/chunks/'+sha256(part),content=part)
        assert response.status_code==200,response.text
    return pair.client.post('/api/federation/'+AUTH+'/evidence/import',json=manifest),manifest


def test_closed_round_upload_is_idempotent_and_existing_reviewer_reads_measured_paths(pair):
    response,manifest=upload(pair)
    assert response.status_code==200,response.text
    ack=response.json();assert ack['imported'] and ack['knowledge_delivered'] is False
    # A lost import response retries without its already-pruned chunks.
    retry=pair.client.post('/api/federation/'+AUTH+'/evidence/import',json=manifest)
    assert retry.json()==ack
    service=Reviewer(pair.cfg.data_dir)
    runs=service.runs(TITLE,limit=100,paths=True)['runs']
    assert len(runs)==1 and len(runs[0]['path'])==3
    round=service.round(TITLE,pair.rid)
    assert round['geometry'].get('units_per_m',100)==100 and len(round['events'])==1
    assert round['samples'][0]['frame']['units_per_m']==100
    note=round['notebook'];observed=note['observed']
    assert observed['source_session_id']==SID and observed['source_note_ts']==1234
    assert observed['source_authority']==AUTH and not observed['s_rank_verified']
    assert 'round_semantic_recalled' not in observed and 'knowledge_delivered' not in observed
    assert note['knowledge_delivered'] is False and round['knowledge']['semantic_recall'] is None
    db=NavigationAtlas(pair.cfg.data_dir/'mercs'/'navigation',TITLE)
    assert db.db.execute('select count(*) from rounds').fetchone()[0]==1
    assert db.db.execute('select rounds from stages').fetchone()[0]==1
    assert db.db.execute('select count(*) from checkpoint_routes').fetchone()[0]==0
    paths=db.db.execute('select json_path,map_path,metadata from rounds').fetchone();db.close()
    from pathlib import Path
    assert Path(paths[0]).is_relative_to(pair.cfg.data_dir) and '<svg' in Path(paths[1]).read_text()
    assert json.loads(paths[2])['evidence_import']['sha256']==manifest['sha256']


@pytest.mark.parametrize('change',[
    lambda b:b['source'].update(session_id='1'*16+'-'+'d'*32),
    lambda b:b['source'].update(game_id=E.TITLES['G4BE08'][0]),
    lambda b:b['round']['metadata'].update(source_session_id='other'),
    lambda b:b['samples'][0]['payload'].update(at=999),
    lambda b:b['samples'][0]['payload']['frame'].update(title='G4BE08'),
    lambda b:b['samples'][0]['payload']['frame'].update(units='mm'),
    lambda b:b['stage']['geometry'].update(units_per_m=1000),
    lambda b:b['notebook'].update(ts=float('nan')),
    lambda b:b['notebook']['observed'].update(source_session_id='other'),
    lambda b:b['notebook']['observed'].update(score='fabricated'),
    lambda b:b['round'].update(ended=None),
])
def test_contradictory_or_unbounded_evidence_is_rejected_without_an_ack(pair,change):
    bundle,_=E.export_round(pair.local,TITLE,pair.rid,pair.session);change(bundle)
    response,_=upload(pair,bundle)
    assert response.status_code in (403,422),response.text
    assert not pair.app.state.store.all('mercs_evidence')


def test_event_payload_cannot_shadow_its_outer_time_or_kind(pair):
    bundle,_=E.export_round(pair.local,TITLE,pair.rid,pair.session)
    bundle['events'][0]['payload'].update(at=999,kind='untrusted-inner-kind')
    response,_=upload(pair,bundle)
    assert response.status_code==200,response.text
    row=E.read_rows(pair.cfg.data_dir/'mercs'/'navigation'/TITLE/'atlas.sqlite','select json_path from rounds')[0]
    artifact=json.loads(__import__('pathlib').Path(row['json_path']).read_text())
    assert artifact['events'][0]['at']==101 and artifact['events'][0]['kind']=='checkpoint_acquired'


def test_same_authority_reenrolled_worker_can_import_acknowledged_historical_evidence(pair):
    owner=pair.app.state.store.get('federation',AUTH)
    pair.app.state.store.put('federation',AUTH,owner|{'worker_id':'1'*16})
    response,_=upload(pair)
    assert response.status_code==200,response.text


def test_prior_source_worker_still_requires_exact_authority_ownership(pair):
    row=pair.app.state.store.get('worker',WID)
    pair.app.state.store.put('worker',WID,row|{'federation':{'authority':'1'*64}})
    response,_=upload(pair)
    assert response.status_code==403


def test_re4_unknown_geometry_stays_unknown_and_native_units_are_retained(pair):
    title='G4BE08';rid,session=source(pair.local,title=title,rid='2'*32,outcome='interrupted')
    pair.app.state.store.put('session',SID,session|{'federation':{'authority':AUTH}})
    bundle,_=E.export_round(pair.local,title,rid,session)
    response,_=upload(pair,bundle)
    assert response.status_code==200,response.text
    data=Reviewer(pair.cfg.data_dir).round(title,rid)
    assert data['geometry']['geometry_available'] is False and data['geometry']['units_per_m']==1000
    assert data['geometry']['points']==[] and data['run']['outcome']=='interrupted'
    assert not data['notebook']['observed']['s_rank_verified']


def test_immutable_notebook_collision_is_rejected_before_atlas_write(pair):
    Notebook(pair.cfg.data_dir/'mercs',TITLE).finish('other','mercenaries','fixture','died',{},round_id=RID)
    response,_=upload(pair)
    assert response.status_code==422
    assert not (pair.cfg.data_dir/'mercs'/'navigation'/TITLE/'atlas.sqlite').exists()


def test_pending_outbox_survives_lost_ack_and_source_is_never_removed(pair):
    service=E.Service(pair.bridge)
    assert service.scan() and not service.scan()
    class LostAck:
        def put(self,*a,**kw):return pair.client.put(*a,**kw)
        def post(self,*a,**kw):
            response=pair.client.post(*a,**kw)
            assert response.status_code==200,response.text
            raise OSError('synthetic lost final response')
    with pytest.raises(OSError):service.flush_one(LostAck())
    service=E.Service(pair.bridge)
    records=[json.loads(p.read_text()) for p in service.root.glob('*.json') if p.name not in E.STATE_FILES]
    assert records and records[0]['delivered'] is False
    assert service.flush_one(pair.client)
    assert len(pair.app.state.store.all('mercs_evidence'))==1
    assert (pair.local/'mercs'/'navigation'/TITLE/'atlas.sqlite').exists()
    assert json.loads((service.root/'index.json').read_text())


def test_bad_newest_round_does_not_starve_valid_round_or_repeat_missing_count(pair):
    bad='3'*32
    full,_=source(pair.local,rid=bad,note=False)
    import sqlite3
    with sqlite3.connect(pair.local/'mercs'/'navigation'/TITLE/'atlas.sqlite') as db:
        db.execute('UPDATE rounds SET ended=102 WHERE id=?',(full,))
    service=E.Service(pair.bridge)
    assert service.scan()
    assert service.state['origin_missing']==1
    assert not service.scan() and service.state['origin_missing']==1
    notebook=Notebook(pair.local/'mercs',TITLE)
    stage=E.read_rows(pair.local/'mercs'/'navigation'/TITLE/'atlas.sqlite','select stage from rounds where id like ?',
                      (bad+':%',))[0]['stage']
    notebook.finish(stage,'mercenaries','fixture','completed',{},round_id=bad)
    assert service.scan()  # the delayed exact Notebook can now be packaged.


def test_durable_scan_cursor_eventually_reaches_closed_rounds_older_than_100(pair):
    import sqlite3
    path=pair.local/'mercs'/'navigation'/TITLE/'atlas.sqlite'
    with sqlite3.connect(path) as db:
        original=db.execute('SELECT * FROM rounds WHERE id=?',(pair.rid,)).fetchone()
        for n in range(101):
            values=list(original);values[0]=f'{n:032x}:'+original[1];values[3]=200.+n
            db.execute('INSERT INTO rounds VALUES(?,?,?,?,?,?,?,?,?)',values)
    service=E.Service(pair.bridge)
    assert not service.scan()  # bounded page: 100 records await a Notebook.
    service=E.Service(pair.bridge)  # cursor survives a process restart.
    assert service.scan() and service.state['pending']==1
    assert json.loads((service.root/'index.json').read_text())[TITLE+':'+pair.rid]


def test_chunk_hash_and_size_enforced(pair):
    path='/api/federation/'+AUTH+'/evidence/chunks/'+'0'*64
    assert pair.client.put(path,content=b'wrong digest').status_code==422
    assert pair.client.put(path,content=b'x'*(E.CHUNK+1)).status_code==422
