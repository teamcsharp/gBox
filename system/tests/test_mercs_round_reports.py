import json
import sqlite3
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
import pytest

from gbox.store import Store
from gbox.mercs.atlas import NavigationAtlas
from gbox.mercs.notebook import Notebook
from gbox.mercs import round_reports as R
from gbox.mercs.titles.re5_nav import NavMesh

TITLE, RID, SID = 'BLUS30491', 'a'*32, 'worker-session'


@pytest.fixture
def evidence(tmp_path, monkeypatch):
    monkeypatch.setenv('GBOX_HERMES_HOME', str(tmp_path/'hermes'))
    store = Store(tmp_path)
    store.put('session', SID, {'session_id':SID,'game_id':R.TITLES[TITLE][0],'state':'ended'})
    store.put('job','1'*16,{'id':'1'*16,'tool':'autoplay','worker_id':'worker',
        'input':{'op':'start','session_id':SID},'state':'succeeded'})
    mesh = NavMesh([(0.,0.,0.),(1000.,0.,0.),(1000.,0.,1000.),(0.,0.,1000.)],
                   [(0,1,2),(0,2,3)],[[(1,2,1.)],[(0,0,1.)]])
    atlas = NavigationAtlas(tmp_path/'mercs/navigation', TITLE)
    stage = atlas.stage(mesh)
    notebook = Notebook(tmp_path/'mercs', TITLE)
    clock = [1000.]
    runner = R.Reports(store, tmp_path, now=lambda:clock[0])
    stats = {'source_session_id':SID,'source_autoplay_job_id':'1'*16,'team_role':'solo_p1',
             'score':10000,'rank':'SS','completed_score_rank':'SS',
             'completed_score_rank_source':'terminal_ram_score_and_solo_thresholds',
             'stuck':2,'time_bonuses_remaining':3,'bonuses_taken':2,'player_damage_events':1,
             'round_shots':10,'round_hits':4,'round_accuracy':.4,'round_used_health_protection':False}

    def record(rid=RID, outcome='died', at=990., extra=None, with_atlas=True):
        observed = {**stats, **(extra or {})}
        notebook.finish(stage,'mercenaries','Sheva (Tribal)',outcome,observed,round_id=rid)
        with notebook.connect() as db:
            db.execute('UPDATE rounds SET ts=? WHERE id=?',(at,rid))
        if with_atlas:
            atlas.begin(rid,stage,at-30,{'mode':'mercenaries','character':'Sheva (Tribal)', 'source_session_id':SID})
            atlas.sample(rid,at-20,{'player':{'pos':[10.,0.,10.]},'plan':{}},inputs=['lup'])
            atlas.finish(rid,at,outcome,observed)
        return runner.row(TITLE,rid)
    yield SimpleNamespace(store=store,root=tmp_path,atlas=atlas,notebook=notebook,stage=stage,
                          runner=runner,clock=clock,record=record,stats=stats)
    atlas.close(); store.db.close()


def test_exact_round_deduplicates_report_and_request_atomically(evidence):
    e=evidence;row=e.record()
    doc=e.runner.ingest(TITLE,row)
    first=e.runner.materialize(doc)
    assert e.runner.ingest(TITLE,row)['id']==first['id']
    assert e.runner.materialize(doc)['request_id']==first['request_id']
    requests=e.store.all('request')
    assert len(requests)==1
    assert requests[0]['context']['required_inference_node']=='sparkDeux'
    assert requests[0]['context']['read_only'] is True
    assert first['report']['atlas']['rounds'][0]['reviewer'].endswith('id='+RID)
    assert first['report']['metrics']['damage']['player_damage_events']==1
    assert first['analysis_policy_applied'] is False and first.get('job_id') is None
    assert e.store.db.execute("SELECT count(*) FROM audit WHERE action='mercs.round_analysis.queued'").fetchone()[0]==1
    changed={**row,'outcome':'completed'}
    with pytest.raises(ValueError,match='different Notebook evidence'):
        e.runner.ingest(TITLE,changed)


@pytest.mark.parametrize('extra,outcome,category,native',[
    ({},'completed','rank_not_verified',None),
    ({'result_rank_observed':'S','result_rank_verified':False},'completed','rank_not_verified',None),
    ({'result_rank':'A','result_rank_verified':True},'completed','failed_s_rank','A'),
    ({'result_rank':'S','result_rank_verified':True},'died','failed_s_rank','S'),
])
def test_estimated_or_unverified_rank_never_becomes_native_s(evidence,extra,outcome,category,native):
    e=evidence;row=e.record(outcome=outcome,extra=extra)
    doc=e.runner.materialize(e.runner.ingest(TITLE,row))
    assert doc['report']['category']==category
    assert doc['report']['rank']['native']==native
    assert doc['report']['rank']['completed_s_rank'] is False
    assert doc['state']=='queued_for_hermes'


def test_known_clean_s_is_recorded_without_manufacturing_a_failure_task(evidence):
    e=evidence;row=e.record(outcome='completed',extra={'result_rank':'S','result_rank_verified':True,
        'assistance':{'classification':'unmodified','verified':True,'effects':[]}})
    doc=e.runner.materialize(e.runner.ingest(TITLE,row))
    assert doc['state']=='recorded_no_dispatch' and e.store.all('request')==[]
    assert doc['report']['rank']['unmodified_s_rank'] is True


@pytest.mark.parametrize('extra',[{'team_role':None},{'team_role':'observe_human'},
                                  {'source_autoplay_job_id':'not-a-job'}])
def test_no_default_solo_or_guessed_start_job_can_dispatch(evidence,extra):
    e=evidence;row=e.record(extra=extra)
    doc=e.runner.materialize(e.runner.ingest(TITLE,row))
    assert doc['state']=='recorded_no_dispatch'
    assert not doc['report']['eligibility']['eligible'] and e.store.all('request')==[]


def test_mismatched_local_job_cannot_be_overridden_by_import_claim(evidence):
    e=evidence;row=e.record(extra={'source_evidence_sha256':'d'*64})
    e.store.put('job','1'*16,{'tool':'autoplay','worker_id':'other','input':{'op':'start','session_id':SID}})
    doc=e.runner.materialize(e.runner.ingest(TITLE,row))
    assert doc['state']=='recorded_no_dispatch'
    assert doc['report']['source']['provenance']['source']=='owning_local_autoplay_job'


def test_accepted_cross_pc_evidence_has_explicit_remote_job_limit(evidence):
    e=evidence;digest='d'*64
    e.store.delete('job','1'*16)
    e.store.put('session',SID,{'session_id':SID,'game_id':R.TITLES[TITLE][0],
        'federation':{'authority':'desktop'}})
    e.store.put('mercs_evidence',digest,{'authority':'desktop','source_session_id':SID,
        'title':TITLE,'round_id':RID,'ack':{'imported':True}})
    doc=e.runner.materialize(e.runner.ingest(TITLE,e.record(extra={'source_evidence_sha256':digest})))
    assert doc['state']=='queued_for_hermes'
    provenance=doc['report']['source']['provenance']
    assert provenance['verified'] and provenance['source']=='accepted_federated_round'
    assert provenance['source_job_verified_locally'] is False


def test_import_manifest_ack_race_remains_pending_then_retries_same_round(evidence):
    e=evidence;digest='d'*64;e.store.delete('job','1'*16)
    e.store.put('session',SID,{'session_id':SID,'game_id':R.TITLES[TITLE][0],
        'federation':{'authority':'desktop'}})
    doc=e.runner.ingest(TITLE,e.record(extra={'source_evidence_sha256':digest}))
    pending=e.runner.materialize(doc)
    assert pending['state']=='pending_provenance' and not e.store.all('request')
    e.store.put('mercs_evidence',digest,{'authority':'desktop','source_session_id':SID,
        'title':TITLE,'round_id':RID,'ack':{'imported':True}})
    assert e.runner.materialize(pending)['state']=='queued_for_hermes'
    assert len(e.store.all('request'))==1


def test_incident_refs_link_existing_ram_and_save_receipts_without_blob_copy(evidence):
    e=evidence;e.record()
    e.store.put('player_damage','damage',{'event_id':'hit','session_id':SID,'observed_at':980.,
        'loss':196,'run_id':'run','receipt':'b'*64,'save_state':{'state':'skipped_disruptive'},
        'attachments':[{'sha256':'c'*64,'name':'ram-witness.json'}]})
    doc=e.runner.materialize(e.runner.ingest(TITLE,e.runner.row(TITLE,RID)))
    incident=doc['report']['incidents']['events'][0]
    assert incident['receipt_artifact']=='b'*64 and incident['artifacts'][0]['sha256']=='c'*64
    assert incident['save_state']=='skipped_disruptive' and incident['cause']=='unknown'
    assert doc['report']['incidents']['ram_save_blobs_embedded'] is False


def test_missing_atlas_offline_retry_survives_service_recreation(evidence,monkeypatch):
    e=evidence;row=e.record(with_atlas=False)
    e.runner.ingest(TITLE,row)
    monkeypatch.setattr(e.runner,'scan',lambda:0)
    e.runner.poll()
    pending=e.store.get(R.KIND,R.identity(TITLE,RID))
    assert pending['attempts']==1 and pending['next_attempt']>e.clock[0]
    assert e.store.all('request')==[]
    e.record(with_atlas=True)
    e.clock[0]=pending['next_attempt']+1
    fresh=R.Reports(e.store,e.root,now=lambda:e.clock[0])
    monkeypatch.setattr(fresh,'scan',lambda:0)
    fresh.poll();fresh.poll()
    assert len(e.store.all('request'))==1
    assert e.store.get(R.KIND,pending['id'])['request_id']


def test_late_cross_pc_import_with_old_timestamp_is_not_lost_by_time_cursor(evidence):
    e=evidence;e.record(at=1)
    assert e.runner.scan()==1  # bounded recent seed; time 1 is within this fixture's hour
    e.record(rid='b'*32,at=0)
    assert e.runner.scan()==1
    assert e.store.get(R.KIND,R.identity(TITLE,'b'*32))
    assert e.runner.scan()==0


def test_request_identity_collision_rolls_back_without_overwriting_other_work(evidence):
    e=evidence;doc=e.runner.ingest(TITLE,e.record())
    report=R.report_for(TITLE,e.runner.row(TITLE,RID),R.atlas_evidence(e.root,TITLE,e.runner.row(TITLE,RID)),e.store.get('session',SID))
    rid=R.request_document(report,1,1000)['id']
    original={'id':rid,'context':{'mercs_round_report_id':'different'},'body':'operator work'}
    e.store.put('request',rid,original)
    with pytest.raises(ValueError,match='collision'):
        e.runner.materialize(doc)
    assert e.store.get('request',rid)==original
    assert e.store.get(R.KIND,doc['id'])['request_id'] is None


def test_advisory_output_rejects_wrong_round_and_arbitrary_routes(evidence):
    e=evidence;doc=e.runner.materialize(e.runner.ingest(TITLE,e.record()));report=doc['report']
    value={'schema':'gbox.mercs.analysis/1','report_id':doc['id'],'round_id':RID,
           'summary':'Measured stalls require a route review.','findings':['Two recorded stalls.'],
           'proposals':[{'kind':'checkpoint_patience_s','value':16,'reason':'measured stalls'}]}
    assert R.analysis_response(json.dumps(value),report)==value
    assert R.analysis_response(json.dumps(value|{'round_id':'b'*32}),report) is None
    assert R.analysis_response(json.dumps(value|{'route':[[1,2,3]]}),report) is None
    assert R.analysis_response(json.dumps(value|{'proposals':[{'kind':'checkpoint_patience_s','value':100,'reason':'guess'}]}),report) is None


def test_real_execution_ack_and_exact_response_close_analysis_only(evidence):
    e=evidence;doc=e.runner.materialize(e.runner.ingest(TITLE,e.record()))
    home=e.root/'hermes/cron';home.mkdir(parents=True)
    execution='e'*32;job='f'*12
    with sqlite3.connect(home/'executions.db') as db:
        db.execute('CREATE TABLE executions(id,job_id,status,started_at,finished_at,error)')
        db.execute('INSERT INTO executions VALUES(?,?,?,?,?,?)',(execution,job,'completed',
                   '1970-01-01T00:16:40+00:00','1970-01-01T00:16:41+00:00',None))
    response=json.dumps({'schema':'gbox.mercs.analysis/1','report_id':doc['id'],'round_id':RID,
        'summary':'The run had two measured stalls.','findings':['Three time bonuses remained.'],'proposals':[]})
    item={'job_id':job,'dispatch_state':'finished','inference_node':'sparkDeux','last_dispatched':1000.,
          'report_run':execution,'final_report':response,'route':{'provider':'gbox-sparkDeux','model':'configured'}}
    queue={'items':{'inbox:'+doc['request_id']:item}}
    updated=e.runner.reconcile(doc,queue)
    assert updated['job_id']==job and updated['execution']['id']==execution
    assert updated['state']=='analysis_received' and updated['analysis_validated'] is True
    assert e.store.get('request',doc['request_id'])['status']=='done'
    assert updated['analysis_policy_applied'] is False
    assert updated['learning_evaluation']['state']=='evaluation_pending'
    assert updated['auxiliary_execution_verified'] is False and updated['inference_completion_verified'] is False


def test_analysis_response_from_previous_execution_cannot_complete_new_attempt(evidence):
    e=evidence;doc=e.runner.materialize(e.runner.ingest(TITLE,e.record()))
    item={'job_id':'f'*12,'dispatch_state':'queued','inference_node':'sparkDeux','last_dispatched':2000.,
          'report_run':'old','final_report':'Earlier response'}
    updated=e.runner.reconcile(doc,{'items':{'inbox:'+doc['request_id']:item}})
    assert not updated.get('analysis_validated') and e.store.get('request',doc['request_id'])['status']=='open'


def test_only_exact_consumed_review_and_same_geometry_mode_support_followup(evidence):
    e=evidence;doc=e.runner.materialize(e.runner.ingest(TITLE,e.record()))
    e.record(rid='b'*32,at=995,extra={'stuck':0,'bonuses_taken':4})
    e.runner.evaluate(doc)
    assert doc['learning_evaluation']['state']=='evaluation_pending'
    # A real consumer acknowledgment is explicit; proximity/same stage alone never counts.
    with e.notebook.connect() as db:
        data=json.loads(db.execute('SELECT data FROM rounds WHERE id=?',('b'*32,)).fetchone()[0])
        data.update(round_policy_source_ids=[RID],bonus_commitment_patience_s=16.,
                    round_policy_applied='held time checkpoint; measured crossing penalties; verified floor only')
        db.execute('UPDATE rounds SET data=? WHERE id=?',(json.dumps(data),'b'*32))
    e.runner.evaluate(doc)
    evaluation=doc['learning_evaluation']
    assert evaluation['existing_policy_consumed'] is True and evaluation['followup_round_id']=='b'*32
    assert evaluation['metrics']['bonuses_taken']['delta']==2
    assert evaluation['analysis_proposals_applied'] is False and evaluation['improvement_verified'] is False


def test_report_routes_are_authenticated_and_send_no_job(evidence):
    e=evidence;e.runner.materialize(e.runner.ingest(TITLE,e.record()))
    app=FastAPI()
    def auth(request:Request):
        if request.headers.get('authorization')!='Bearer fixture':raise HTTPException(401)
    R.install(app,e.store,SimpleNamespace(data_dir=e.root),auth)
    client=TestClient(app)
    before=e.store.all('job')
    assert client.get('/api/mercs/round-reports').status_code==401
    result=client.get('/api/mercs/round-reports',headers={'authorization':'Bearer fixture'}).json()
    assert result['target']=='sparkDeux' and len(result['reports'])==1
    assert e.store.all('job')==before
