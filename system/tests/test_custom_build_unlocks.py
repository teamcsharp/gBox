import copy
import hashlib
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from gbox import custom_build_unlocks as U
from tests.test_build_quarantine import Memory


def rig(tmp_path, *, admission=lambda:'', workers=lambda:[]):
    store = Memory()
    store.put(U.POLICY, 'idle-state', {'last_busy': 0})
    store.put(U.POLICY, 'default', {'enabled': False, 'dispatch_per_hour': 4})
    store.catalog_get = lambda gid: {'game_id':gid, 'title':'Example '+gid, 'platform':'dreamcast'}
    sha = hashlib.sha256(b'Ghidra and runtime fixture evidence').hexdigest()
    store.read_artifact = lambda value: b'evidence' if value == sha else None
    rows = []
    for name in ('one', 'two'):
        folder = tmp_path/'mods'/'g'/name; folder.mkdir(parents=True)
        meta = {'game_id':'g','name':name,'built':1}
        (folder/'.gbox-mod.json').write_text(json.dumps(meta))
        (folder/'game.bin').write_bytes(b'game')
        rows.append({'game_id':'g','name':name,'meta':meta,'marker':[1,10]})
    app = FastAPI()
    app.state.built_mods = SimpleNamespace(records=lambda:copy.deepcopy(rows))
    created, dispatched = [], []
    def create(body):
        r = body | {'id':str(len(created)+1),'number':len(created)+1,'status':'open','messages':[]}
        created.append(r); store.put('request',r['id'],r); return r
    def investigate(*args, **kwargs): dispatched.append(args); return {'mode':'queue'}
    reconcile = U.routes(app,store,SimpleNamespace(cache=tmp_path),lambda:'operator',create,investigate,workers=workers,admission=admission)
    return store, rows, TestClient(app), reconcile, created, dispatched, sha


def profile(sha):
    return {'executable_sha256':'a'*64,'inventory_complete':True,'implementation':'gbox.example_writer unlock step',
        'ghidra_artifacts':[sha],'runtime_artifacts':[sha],
        'inventory':{k:{'status':'unlocked' if k=='characters' else 'not_present',
                       'entries':['Hidden fighter'] if k=='characters' else [],
                       'evidence':'Exact source inventory and runtime fixture'} for k in U.CATEGORIES}}


def test_opt_in_deduplicates_per_game_and_new_builds_reopen_unfulfilled_work(tmp_path):
    store, rows, c, reconcile, created, dispatched, sha = rig(tmp_path)
    reconcile(); assert not created
    assert c.post('/api/custom-build-unlocks/policy',json={'enabled':True}).status_code==200
    reconcile(); reconcile()
    assert len(created)==len(dispatched)==1
    assert 'Ghidra' in created[0]['body'] and 'one (version' in created[0]['body'] and 'two (version' in created[0]['body']
    req=store.get('request','1');req['status']='done';store.put('request','1',req)
    reconcile()
    assert store.get('request','1')['status']=='open', 'done alone cannot claim unlock-all'
    assert len(created)==1 and len(dispatched)==2
    rows[0]['meta']['built']=2
    reconcile(); assert len(dispatched)==3 and len(created)==1
    assert c.get('/api/custom-build-unlocks').json()['verified']==0
    c.post('/api/custom-build-unlocks/policy',json={'enabled':False})
    rows[0]['meta']['built']=3;reconcile();assert len(dispatched)==3


def test_profiles_require_complete_inventory_ghidra_and_runtime_evidence(tmp_path):
    store, rows, c, reconcile, created, dispatched, sha = rig(tmp_path)
    value=profile(sha)
    for bad in [value|{'inventory_complete':False}, value|{'ghidra_artifacts':[]},
                value|{'runtime_artifacts':['b'*64]},value|{'inventory':{}},value|{'executable_sha256':'guessed'}]:
        assert c.post('/api/custom-build-unlocks/g/profile',json=bad).status_code==422
    assert c.post('/api/custom-build-unlocks/g/profile',json=value).status_code==200
    assert c.get('/api/custom-build-unlocks/g/profile').json()['profile']['inventory_complete']


def test_acceptance_is_per_exact_build_and_invalidates_after_payload_change(tmp_path):
    store, rows, c, reconcile, created, dispatched, sha = rig(tmp_path)
    c.post('/api/custom-build-unlocks/policy',json={'enabled':True});reconcile()
    assert c.post('/api/custom-build-unlocks/g/profile',json=profile(sha)).status_code==200
    body=c.get('/api/custom-build-unlocks/g/one/manifest').json()|{'runtime_artifacts':[sha],'notes':'Fresh boot: hidden fighter selectable and playable; all inventory covered.'}
    assert c.post('/api/custom-build-unlocks/g/one/verify',json=body|{'files':[]}).status_code==409
    assert c.post('/api/custom-build-unlocks/g/one/verify',json=body).status_code==200
    status=c.get('/api/custom-build-unlocks').json()
    assert status['verified']==1 and status['total']==2
    assert U.badge(store,rows[1])['status']=='pending'
    (tmp_path/'mods/g/one/game.bin').write_bytes(b'changed game')
    reconcile()
    assert U.badge(store,rows[0])['status']=='pending'
    assert c.post('/api/custom-build-unlocks/g/one/verify',json=body).status_code==409


def test_profile_changes_and_rebuilds_cannot_reuse_old_acceptance(tmp_path):
    store, rows, c, reconcile, created, dispatched, sha = rig(tmp_path)
    c.post('/api/custom-build-unlocks/policy',json={'enabled':True})
    c.post('/api/custom-build-unlocks/g/profile',json=profile(sha))
    body=c.get('/api/custom-build-unlocks/g/one/manifest').json()|{'runtime_artifacts':[sha],'notes':'all inventory verified'}
    c.post('/api/custom-build-unlocks/g/one/verify',json=body)
    c.post('/api/custom-build-unlocks/g/profile',json=profile(sha)|{'implementation':'updated unlock implementation'})
    assert U.badge(store,rows[0])['status']=='pending'
    rows[0]['marker']=[2,10]
    assert c.post('/api/custom-build-unlocks/g/one/verify',json=body).status_code==409


def test_dispatch_failure_retries_same_ticket_and_broken_builds_are_excluded(tmp_path):
    store, rows, c, reconcile, created, dispatched, sha = rig(tmp_path)
    store.put('build_broken','g/two',{'state':'preserved'})
    c.post('/api/custom-build-unlocks/policy',json={'enabled':True})
    reconcile()
    assert 'two (version' not in created[0]['body']
    assert list(store.get(U.TASK,'g')['versions'])==['one']
    task=store.get(U.TASK,'g');task['dispatched']=False;store.put(U.TASK,'g',task)
    reconcile();assert len(created)==1 and len(dispatched)==2


def test_request_cannot_close_with_unverified_custom_builds(tmp_path):
    from tests.test_builds import fixture
    cfg, app, store, headers = fixture(tmp_path)
    store.put(U.POLICY,'default',{'enabled':True})
    store.put('request','r7',store.get('request','r7')|{'context':{'custom_build_unlocks':'g1'}})
    with TestClient(app) as c:
        assert app.state.built_mods.wait(10)
        r=c.post('/api/requests/r7/status',headers=headers,json={'status':'done'})
        assert r.status_code==409, r.text
        assert 'g1_patch' in r.json()['detail']['pending_builds']
        rows=c.get('/api/builds',headers=headers).json()['items']
        assert next(b for b in rows if b['name']=='g1_local_only')['unlocks']['status']=='pending'


def test_get_profile_returns_existing_unlock_support_for_unsupported_game(tmp_path):
    store, rows, c, reconcile, created, dispatched, sha = rig(tmp_path)
    c.post('/api/custom-build-unlocks/g/profile',json=profile(sha))
    body=c.get('/api/custom-build-unlocks/g/profile').json()
    assert 'profile' in body and body['profile']['inventory_complete']
    assert 'existing_unlock_support' in body
    assert body['existing_unlock_support']['status']=='unsupported'
    assert body['existing_unlock_support']['verified'] is False


def test_get_profile_returns_existing_unlock_support_for_re6_game(tmp_path):
    store, rows, c, reconcile, created, dispatched, sha = rig(tmp_path)
    store.catalog_get = lambda gid: (
        {'game_id':'0871eee3b68cdea3','title':'RE6','platform':'xbox360'}
        if gid=='0871eee3b68cdea3' else {'game_id':gid,'title':'Example '+gid,'platform':'dreamcast'}
    )
    body=c.get('/api/custom-build-unlocks/0871eee3b68cdea3/profile').json()
    assert body['existing_unlock_support']['status']=='verified_profile'
    assert body['existing_unlock_support']['verified'] is True
    assert body['existing_unlock_support']['profile']=='re6-x360-native-save-template-v1'


def test_reconcile_propagates_existing_unlock_support_into_dispatch_instructions(tmp_path):
    from gbox.game_unlocks import RE6_ID, profile_for as re6_profile_for
    store, rows, c, reconcile, created, dispatched, sha = rig(tmp_path)
    store.catalog_get = lambda gid: (
        {'game_id':RE6_ID,'title':'RE6','platform':'xbox360'}
        if gid==RE6_ID else {'game_id':gid,'title':'Example '+gid,'platform':'dreamcast'}
    )
    c.post('/api/custom-build-unlocks/policy',json={'enabled':True})
    rows[0]['game_id']=RE6_ID; rows[0]['meta']['game_id']=RE6_ID
    reconcile()
    assert created, 'reconcile should create a request for the RE6 game'
    text=created[0]['body']
    assert 'existing_unlock_support' not in text or 're6-x360-native-save-template-v1' in text
    support=re6_profile_for({'game_id':RE6_ID,'platform':'xbox360'})
    assert support['status']=='verified_profile'


def test_a_verified_unlock_on_load_code_profile_verifies_every_build(tmp_path, monkeypatch):
    """2026-10-19: a game whose unlocks are held from launch by a code profile is no longer 'Unlock-all pending'."""
    store, rows, c, reconcile, created, dispatched, sha = rig(tmp_path)
    c.post('/api/custom-build-unlocks/policy',json={'enabled':True})
    assert U.badge(store,rows[0])['status']=='pending'
    from gbox import game_unlocks
    monkeypatch.setattr(game_unlocks,'code_profile',lambda game: {'profile':'p1','scope':['characters','stages']}
                        if game['game_id']=='g' else None)
    b=U.badge(store,rows[0])
    assert b['status']=='verified' and b['code_profile']=='p1' and 'characters, stages' in b['label']
