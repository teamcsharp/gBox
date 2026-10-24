import json
import sqlite3
from types import SimpleNamespace

import pytest

from gbox.mercs.legacy_trace import LegacyRecorder
from gbox.mercs.reviewer import Reviewer,_load_mesh


RID='e'*32


def snap(x):
    return {'room':0x400,'player':{'ptr':0x80310000,'pos':[x,0,0]},'hp':73,'timer':100.,'combo':2,
            'enemies':[{'slot':1,'pos':[x,0,3000],'hp':1000,'hp_max':1000,'r':[1,2,3,4]}]}


def test_measured_re4_path_round_guide_and_vector_outbox_join_in_reviewer(tmp_path):
    stats={};recorder=LegacyRecorder(tmp_path,stats)
    for at,x in ((100.,0.),(100.5,1000.),(101.,2000.)):
        recorder.observe(snap(x),None,{'up'},at,RID,'Ada')
    recorder.finish(101.5,'completed',stats)
    assert not stats.get('legacy_trace_error') and stats['legacy_trace_pending'] is False
    reviewer=Reviewer(tmp_path)
    rows=reviewer.runs('G4BE08',paths=True)['runs']
    assert len(rows)==1 and rows[0]['notebook_source_id']=='gbox:mercs:G4BE08:'+RID
    assert rows[0]['paths'][0]['control']=='bot'
    assert not any(p.get('break') for p in rows[0]['paths'][0]['path'])
    detail=reviewer.round('G4BE08',rows[0]['id'])
    assert detail['geometry']['geometry_available'] is False
    assert detail['geometry']['points']==[] and detail['geometry']['boundaries']==[]
    assert detail['samples'][1]['frame']['player']['pos']==[1000.,0.,0.]
    assert detail['samples'][1]['frame']['enemies'][0]['hp']==1000
    assert detail['samples'][1]['frame']['clock']['score'] is None
    assert rows[0]['review']['distance_m']==2. and rows[0]['review']['units_per_m']==1000
    assert detail['notebook']['observed']['reflection']['acceptance']['completed_s_rank'] is False
    assert (tmp_path/'mercs/curriculum/G4BE08/guide.json').is_file()
    with sqlite3.connect(tmp_path/'mercs/curriculum/G4BE08/rounds.sqlite') as db:
        row=db.execute('select id,delivered from knowledge_outbox').fetchone()
        assert row==(RID,0)                        # durable pending; never claim semantic delivery
    assert 'travel' in open(stats['re4_round_map']).read()
    with pytest.raises(ValueError,match='collision geometry is unavailable'):
        _load_mesh(detail['geometry'],rows[0]['geometry'])


def test_invalid_or_missing_native_coordinates_do_not_fabricate_a_map(tmp_path):
    recorder=LegacyRecorder(tmp_path,{})
    for value in ({},snap(float('nan')),snap(1)|{'room':0x120}):
        recorder.observe(value,None,set(),1,RID)
    recorder.finish(2,'interrupted',{})
    assert not list(tmp_path.iterdir())


def test_legacy_play_records_before_its_native_boundary_callback(tmp_path):
    from gbox import re4_merc_bot as B
    from tests.test_re4_merc_bot import world
    game=world([]);now=[0.];stats={};observed=[]
    def sleep(dt):
        now[0]+=dt
        if now[0]>.6:game.put(B.MERC_TIMER,'>I',0)
    def boundary(body,live):
        observed.append(Reviewer(tmp_path).summaries('G4BE08'))
        live['mercmode_rotate_requested']=True
    B.play(None,lambda rows:None,lambda:now[0]>5,m=game,clock=lambda:now[0],sleep=sleep,
        stats=stats,learn_dir=tmp_path/'private-bot',record_dir=tmp_path,hooks=lambda:[],
        ram_prompt=False,round_boundary=boundary,session_id='owned-worker-exact-session',source_job_id='exact-autoplay')
    assert len(observed)==1 and len(observed[0])==1
    assert observed[0][0]['outcome']=='completed'
    with sqlite3.connect(tmp_path/'mercs/navigation/G4BE08/atlas.sqlite') as db:
        metadata=json.loads(db.execute('select metadata from rounds').fetchone()[0])
    assert metadata['source_session_id']=='owned-worker-exact-session'
    assert metadata['source_autoplay_job_id']=='exact-autoplay'
    note=Reviewer(tmp_path).notebook('G4BE08',observed[0][0]['round_id'])
    assert note['observed']['source_session_id']=='owned-worker-exact-session'


def test_round_changes_close_prior_evidence_and_counters_are_round_deltas(tmp_path):
    stats={'shots':10,'hits':7,'hits_taken':2};recorder=LegacyRecorder(tmp_path,stats)
    recorder.observe(snap(0),None,{'up'},100,RID,'Ada')
    stats.update(shots=12,hits=8,hits_taken=3)
    second='f'*32
    recorder.observe(snap(2000),None,{'up'},101,second,'HUNK')
    stats.update(shots=15,hits=10,hits_taken=3)
    recorder.finish(102,'completed',stats)
    rows=Reviewer(tmp_path).summaries('G4BE08')
    assert len(rows)==2
    outcomes={row['round_id']:row['outcome'] for row in rows}
    assert outcomes=={RID:'interrupted',second:'completed'}
    note=Reviewer(tmp_path).notebook('G4BE08',second)
    assert note['observed']['shots']==3 and note['observed']['hits']==2
    assert note['observed']['hits_taken']==0 and note['observed']['accuracy']==pytest.approx(2/3)


def test_dead_writer_restarts_as_explicit_partial_fragment(tmp_path):
    stats={};recorder=LegacyRecorder(tmp_path,stats)
    recorder.observe(snap(0),None,set(),100,RID)
    old=recorder.active;old.finish(100.1,'interrupted',stats)
    recorder.observe(snap(1000),None,set(),101,RID)
    assert recorder.active.round_id!=RID and recorder.active.fragment is True
    recorder.finish(102,'completed',stats)
    rows=Reviewer(tmp_path).summaries('G4BE08')
    assert len(rows)==2 and all(row['outcome']=='interrupted' for row in rows)
