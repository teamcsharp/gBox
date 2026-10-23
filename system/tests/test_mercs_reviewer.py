import json
import sqlite3
import time
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
import pytest

from gbox.mercs.atlas import NavigationAtlas
from gbox.mercs.notebook import Notebook
from gbox.mercs.reviewer import Reviewer, routes, validated_suggestions
from gbox.mercs.titles.re5_nav import NavMesh
from gbox import screensaver
from gbox.tactical_map import Store as Tactical

TITLE='BLUS30491'
RID='a'*32


def mesh():
    return NavMesh([(0.,0.,0.),(1000.,0.,0.),(1000.,0.,1000.),(0.,0.,1000.)],
                   [(0,1,2),(0,2,3)],[[(1,2,1.)],[(0,0,1.)]])


@pytest.fixture
def evidence(tmp_path):
    nav=mesh()
    atlas=NavigationAtlas(tmp_path/'mercs'/'navigation',TITLE)
    geometry=atlas.stage(nav)
    rid=RID+':'+geometry
    atlas.begin(rid,geometry,100.,{'mode':'mercenaries','character':'Sheva (Tribal)','game_stage':'The Mines'})
    for at,x,hp,enemy in [(100.,100.,1000,True),(100.5,200.,804,True),(101.,300.,1000,False)]:
        frame={'title':TITLE,'player':{'pos':[x,0.,100.],'hp':hp,'hp_max':1000},
               'enemies':[{'id':1,'pos':[500.,0.,500.],'hp':800,'hp_max':800}] if enemy else [],
               'clock':{'score':1000,'combo':2,'kills':int(not enemy),'left':120-at+100},'plan':{'phase':'gather_time'}}
        atlas.sample(rid,at,frame,inputs=['lup'])
    atlas.event(rid,101.,'checkpoint_acquired',{'key':'time:300:0:100','pos':[300.,0.,100.],'evidence':{'clock_gain_s':30}})
    atlas.db.commit()
    notebook=Notebook(tmp_path/'mercs',TITLE)
    notebook.finish(geometry,'mercenaries','Sheva (Tribal)','completed',{'score':60000,'round_used_health_protection':False},round_id=RID)
    with notebook.connect() as db:
        db.execute('update rounds set ts=101 where id=?',(RID,))
        db.execute('insert into semantic_recall values(?,?,?,?)',(geometry,'mercenaries',123.,json.dumps({'accepted_round_ids':[RID],'accepted_chunk_ids':[99]})))
    app=FastAPI()
    def auth(request:Request):
        if request.headers.get('authorization')!='Bearer fixture':
            raise HTTPException(401,'bad token')
        return 'operator'
    app.state.store=SimpleNamespace(running_sessions=lambda:[{'session_id':'worker-session'}])
    app.state.tactical_map=Tactical()
    routes(app,SimpleNamespace(data_dir=tmp_path),auth)
    client=TestClient(app,headers={'authorization':'Bearer fixture'})
    yield SimpleNamespace(root=tmp_path,atlas=atlas,nav=nav,geometry=geometry,rid=rid,notebook=notebook,
                          service=Reviewer(tmp_path),client=client,app=app)
    atlas.close()


def test_catalog_and_exact_sources_do_not_claim_a_vector_search(evidence):
    e=evidence
    catalog=e.client.get('/api/mercs/reviewer/catalog').json()
    assert catalog['games'][0]['visible_runs']==1 and 'preserved' in catalog['retention']
    data=e.client.get('/api/mercs/reviewer/round',params={'title':TITLE,'id':e.rid}).json()
    assert len(data['samples'])==3 and data['events'][0]['kind']=='checkpoint_acquired'
    assert data['notebook']['source_id']==f'gbox:mercs:{TITLE}:{RID}'
    assert data['notebook']['knowledge_delivered'] is False
    assert data['notebook']['vector_features'][0]['name']=='kills'
    assert 'not semantic embeddings' in data['notebook']['vector_kind']
    assert data['knowledge']['semantic_recall']['receipt']['accepted_chunk_ids']==[99]
    assert data['provenance']['semantic_search_performed'] is False
    assert not data['notebook']['observed']['s_rank_verified']  # 60k alone isn't observed UI rank.
    assert data['samples'][-1]['frame']['enemies']==[]


def test_incremental_live_recording_keeps_samples_and_all_existing_rounds(evidence):
    e=evidence
    result=e.client.get('/api/mercs/reviewer/round',params={'title':TITLE,'id':e.rid,'after':1}).json()
    assert [r['seq'] for r in result['samples']]==[2]
    before=e.atlas.db.execute('select count(*) from rounds').fetchone()[0]
    e.client.get('/api/mercs/reviewer/runs',params={'title':TITLE,'paths':True})
    assert e.atlas.db.execute('select count(*) from rounds').fetchone()[0]==before
    with e.atlas.db:
        for i in range(105):
            e.atlas.db.execute('insert into rounds(id,stage,started,metadata) values(?,?,?,?)',
                               (f'new{i:03}',e.geometry,200+i,json.dumps({'game_stage':'The Mines','character':'Chris'})))
    rows=e.service.runs(TITLE,character='Chris',limit=100)['runs']
    assert len(rows)==100 and rows[0]['id']=='new104' and rows[-1]['id']=='new005'
    assert e.atlas.db.execute('select count(*) from rounds').fetchone()[0]==106


def test_notebook_join_rejects_same_id_from_other_geometry_or_mode(evidence):
    e=evidence
    with e.notebook.connect() as db:
        db.execute('update rounds set stage=? where id=?',('other-geometry',RID))
    data=e.service.round(TITLE,e.rid)
    assert data['notebook'] is None
    assert next(r for r in e.service.summaries(TITLE) if r['id']==e.rid)['notebook_source_id'] is None


def test_legacy_atlas_without_mode_does_not_claim_verified_notebook_mode(evidence):
    e=evidence
    with e.atlas.db:
        e.atlas.db.execute('update rounds set metadata=? where id=?',
                          (json.dumps({'game_stage':'The Mines','character':'Sheva (Tribal)'}),e.rid))
    data=e.service.round(TITLE,e.rid)
    assert data['notebook'] is None and data['run']['mode'] is None
    assert data['run']['notebook_source_id'] is None
    assert data['provenance']['notebook_join']=='no matching saved Notebook row'
    assert data['samples']  # measured spatial evidence remains available.


def test_geometry_facets_prefer_observed_stage_name_over_legacy_hash_label(evidence):
    e=evidence
    with e.atlas.db:
        e.atlas.db.execute('insert into rounds(id,stage,started,metadata) values(?,?,?,?)',('legacy',e.geometry,99.,'{}'))
    stages=e.service.catalog()['games'][0]['stages']
    assert stages==[{'id':e.geometry,'name':'The Mines'}]


def test_route_annotations_are_exact_geometry_validated_and_survive_reopen(evidence):
    e=evidence
    response=e.client.post('/api/mercs/reviewer/suggestions',json={'title':TITLE,'geometry':e.geometry,
        'name':'Operator suggestion','points':[[100.,0.,800.],[800.,0.,100.]]})
    assert response.status_code==200,response.text
    row=response.json()
    assert row['bot_eligible'] and row['actor']=='operator' and row['status']=='validated_floor_suggestion'
    assert Reviewer(e.root).suggestions(TITLE,e.geometry)[0]['id']==row['id']
    assert validated_suggestions(e.root,TITLE,e.nav)[0]['id']==row['id']
    e.nav.links=[[],[]]
    assert not validated_suggestions(e.root,TITLE,e.nav)  # topology changed, no reuse.


def test_wall_or_unknown_action_link_annotations_remain_drafts(evidence):
    e=evidence
    points=[[100.,0.,100.],[2000.,0.,100.]]
    row=e.service.save({'title':TITLE,'geometry':e.geometry,'points':points},'operator')
    assert row['status']=='draft' and not row['bot_eligible']
    assert not validated_suggestions(e.root,TITLE,e.nav)
    nav=NavMesh([(0.,0.,0.),(1000.,0.,0.),(1000.,0.,1000.),(0.,0.,1000.),
                 (0.,300.,0.),(1000.,300.,0.),(1000.,300.,1000.),(0.,300.,1000.)],
                [(0,1,2),(0,2,3),(4,5,6),(4,6,7)],
                [[(1,2,1.)],[(0,0,1.)],[(3,2,1.),(0,0,1.)],[(2,0,1.)]])
    key=e.atlas.stage(nav)
    row=e.service.save({'title':TITLE,'geometry':key,'points':[[800.,300.,100.],[800.,0.,100.]]},'operator')
    assert not row['bot_eligible'] and row['validation'][0]['candidate_action_links']


@pytest.mark.parametrize('body',[
    {'title':'../secret','geometry':'x','points':[[0,0,0],[1,0,0]]},
    {'title':TITLE,'geometry':'unknown','points':[[0,0,0],[1,0,0]]},
    {'title':TITLE,'geometry':[],'points':[[0,0,0],[1,0,0]]},
    {'title':TITLE,'geometry':'x','points':[[0,0],[1,0]]},
    {'title':TITLE,'geometry':'x','points':[[True,0,0],[1,0,0]]},
    {'title':TITLE,'geometry':'x','points':[[0,0,0]]*257},
])
def test_malformed_or_unmeasured_routes_never_become_movement(evidence,body):
    assert evidence.client.post('/api/mercs/reviewer/suggestions',json=body).status_code in (400,404)


def test_endpoints_require_authentication_and_bounded_history(evidence):
    e=evidence
    assert TestClient(e.app).get('/api/mercs/reviewer/catalog').status_code==401
    assert e.client.get('/api/mercs/reviewer/runs',params={'title':'../secret'}).status_code==400
    assert e.client.get('/api/mercs/reviewer/runs',params={'title':TITLE,'limit':101}).status_code==400
    assert e.client.get('/api/mercs/reviewer/round',params={'title':TITLE,'id':'arbitrary'}).status_code==404


def test_fresh_live_feed_requires_exact_active_uuid_and_geometry(evidence,monkeypatch):
    e=evidence
    monkeypatch.setattr(screensaver,'TELEMETRY',{})
    screensaver.telemetry_put('worker-session',{'running':True,'stats':{'round_evidence_id':RID,'nav_geometry':e.geometry}})
    e.app.state.tactical_map.put_frame('worker-session',{'v':1,'title':TITLE,'screen':'playing','t':time.time(),
                                                       'player':{'pos':[100,0,100],'hp':1000}})
    url='/api/mercs/reviewer/live'
    params={'title':TITLE,'id':e.rid}
    result=e.client.get(url,params=params).json()
    assert result['live'] and result['provenance']['recorded'] is False
    screensaver.telemetry_put('worker-session',{'running':True,'stats':{'round_evidence_id':'b'*32,'nav_geometry':e.geometry}})
    assert not e.client.get(url,params=params).json()['live']


def test_geometry_filtered_mine_learning_is_exposed_without_kill_attribution(evidence):
    e=evidence
    path=e.root/'mercs'/'lessons';path.mkdir()
    (path/(TITLE+'-navigation.json')).write_text(json.dumps({'stages':{e.geometry:{'mine_sites':{'2':{'placements':3,'confirmed_kills':0}}}}}))
    data=e.service.round(TITLE,e.rid)
    assert data['navigation_learning']['observed']['mine_sites']['2']['confirmed_kills']==0
    assert not data['navigation_learning']['historical_snapshot']


def test_global_shell_entry_and_routes_are_registered_without_running_game(tmp_path):
    from gbox.server import create_app
    from gbox.config import Config
    config=Config(data_dir=tmp_path/'data',cache_dir=tmp_path/'cache')
    client=TestClient(create_app(config))
    response=client.get('/mercenaries')
    assert response.status_code==200 and 'Mercenaries: mercsReviewerView' in response.text
    assert '/viz/mercs-reviewer.js' in response.text
    assert client.get('/api/mercs/reviewer/catalog').status_code==401
    result=client.get('/api/mercs/reviewer/catalog',headers={'authorization':'Bearer '+config.token()})
    assert result.status_code==200 and result.json()['games']==[]
