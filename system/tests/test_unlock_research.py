import copy
from types import SimpleNamespace

import pytest
from gbox import unlock_research as U, game_unlocks as G, hermes_work_queue as Q


def rig():
    state={'enabled': True, 'enabled_at': 100, 'parent_request_id': 'a'*16}
    requests=[{'id': 'a'*16, 'context': {}, 'status': 'open'}]
    games=[{'game_id': '1'*16, 'title': 'Another game', 'in_catalog': True},
           {'game_id': '2'*16, 'title': 'Dead or Alive 3', 'in_catalog': True}]
    sessions=[{'game_id': '3'*16, 'title': 'Resident Evil', 'started': 101, 'state': 'ended'},
              {'game_id': '4'*16, 'title': 'Old unstarred game', 'started': 1, 'state': 'ended'}]
    saved=[]; posts=[]
    def api(path,body=None):
        if body is not None:
            assert path=='/api/requests'
            posts.append(body)
            row=body|{'id': f'{len(posts)+20:016x}', 'number':len(posts), 'status':'open', 'created': 100}
            requests.append(row);return row
        return {'/api/hermes/task-mode': {'enabled':True}, '/api/requests':requests,
                '/api/favorites':{'count':len(games),'items':games}, '/api/sessions':sessions}[path]
    return state,api,lambda v:saved.append(copy.deepcopy(v)),requests,games,posts,saved


def test_every_favorite_and_new_launch_deduplicated_and_accepted_by_hermes_queue():
    state,api,save,requests,games,posts,_=rig()
    result=U.reconcile(state,api,save,now=200)
    assert result['targets']==result['tracked']==3
    assert [p['context'][U.KEY] for p in posts]==['2'*16,'3'*16,'1'*16]
    assert not U.reconcile(state,api,save,now=201)['created']
    data={'items':{}}
    Q.sync(data,{'count':len(games),'items':games},requests,now=201)
    assert all('inbox:'+r['id'] in data['items'] for r in requests[1:])
    assert all('REA' in p['body'] and 'Ghidra' in p['body'] and 'pre_launch' in p['body'] for p in posts)


def test_lost_create_response_is_reconciled_without_duplicate():
    state,api,save,requests,games,posts,saved=rig()
    def timeout_after_post(path,body=None):
        result=api(path,body)
        if body is not None:raise TimeoutError('response lost')
        return result
    with pytest.raises(TimeoutError):U.reconcile(state,timeout_after_post,save,now=200)
    assert saved[-1]['games']['2'*16]['uncertain']==200
    U.reconcile(state,api,save,now=201)
    assert len(posts)==3 and 'uncertain' not in state['games']['2'*16]


def test_pause_incomplete_snapshot_and_bounded_scan():
    state,api,save,_,_,posts,_=rig()
    def paused(path,body=None):
        assert path=='/api/hermes/task-mode' and body is None
        return {'enabled':False}
    assert U.reconcile(state,paused,save)['status']=='paused_with_hermes'
    assert not posts
    with pytest.raises(ValueError):U.targets({'count':2,'items':[]},[],0)
    U.reconcile(state,api,save,now=200,limit=1);assert len(posts)==1
    U.reconcile(state,api,save,now=201);assert len(posts)==3


def test_unknown_revision_never_calls_unlock_writer(monkeypatch):
    from gbox import re6_tool
    monkeypatch.setattr(re6_tool,'pre_launch',lambda *a:pytest.fail('Unexpected write'))
    for game in ({'game_id':'doa3','platform':'xbox'}, {'game_id':G.RE6_ID,'platform':'ps3'}):
        assert G.pre_launch(game,SimpleNamespace())['applied'] is False


@pytest.mark.parametrize('native,state', [({'everything_unlocked':False},'disabled'),
    ({'everything_unlocked':True,'unlock':{'error':'No save yet'}},'pending_save'),
    ({'everything_unlocked':True,'unlock':{'bytes_changed':12}},'applied')])
def test_known_hook_reports_actual_save_result(monkeypatch,native,state):
    from gbox import re6_tool
    monkeypatch.setattr(re6_tool,'pre_launch',lambda ctx,mod:native)
    result=G.pre_launch({'game_id':G.RE6_ID,'platform':'xbox360'},SimpleNamespace())
    assert result['state']==state and result['applied']==(state=='applied')


DOAPP_INVENTORY={'schema':1,'source':'/srv/gbox/doapp.zip','generated':100,
  'games':{'1'*16:{'title':'Dead or Alive 3','title_source':'library','platform':'xbox',
    'files':3,'entries':4,'entry_kinds':{'CHAR':2,'TEXT':1,'MODEL':1},
    'entries_detail':{},
    'categories':{'costumes':['a','b','c'],'stages':['s1']},
    'warnings':[],'files_detail':[]}}}


def _doapp_inventory():
    inv=copy.deepcopy(DOAPP_INVENTORY)
    game=inv['games']['1'*16]
    game['entries']={'a':{'kind':'CHAR','hidden_costume':False},
                     'b':{'kind':'CHAR','hidden_costume':True},
                     'c':{'kind':'TEXT','hidden_costume':False},
                     's1':{'kind':'MODEL','hidden_costume':True}}
    return inv


def test_doapp_inventory_report_summarizes_evidence_without_mutation():
    inv=_doapp_inventory()
    before=copy.deepcopy(inv)
    report=U.doapp_inventory_report(inv,'1'*16)
    assert inv==before  # evidence only, never mutates the inventory
    assert report['kind']=='doapp_inventory_report'
    assert report['title']=='Dead or Alive 3' and report['title_source']=='library'
    assert report['files']==3 and report['entries']==4
    assert report['entry_kinds']=={'CHAR':2,'MODEL':1,'TEXT':1}
    assert report['categories']=={'costumes':3,'stages':1}
    assert report['category_samples']['costumes']==['a','b','c']
    assert report['hidden_costumes']==['b','s1'] and report['hidden_costume_count']==2
    assert report['source']=='/srv/gbox/doapp.zip' and report['inventory_generated']==100
    assert 'game_unlocks' in report['runtime_hooks']


def test_doapp_inventory_report_requires_game_presence():
    for inv in ({}, {'games':{}}, _doapp_inventory()):
        with pytest.raises(ValueError):U.doapp_inventory_report(inv,'9'*16)


def test_doapp_inventory_report_tolerates_missing_fields():
    report=U.doapp_inventory_report({'games':{'5'*16:{}}},'5'*16)
    assert report['title']=='5'*16 and report['title_source']=='unresolved'
    assert report['entries']==0 and report['hidden_costumes']==[]
    assert report['categories']=={} and report['warnings']==[]
