import json
import uuid
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from gbox import game_build_requests as R
from test_build_quarantine import Memory


def setup(tmp_path):
    store=Memory();store.catalog_get=lambda gid:{'game_id':gid,'title':'Game '+gid} if gid in ('game', 'other','49b6a2f65aca26a2','b7aecee966090bfa') else None
    calls=[];cfg=SimpleNamespace(cache=tmp_path/'cache',data_dir=tmp_path/'data')
    def create(body):
        r=dict(body,id=uuid.uuid4().hex,number=len(store.all('request'))+1,status='open')
        store.put('request',r['id'],r);return r
    def investigate(*args,**kw):calls.append(('agent',args,kw));return {'mode':'queue'}
    def submit(body,actor):
        calls.append(('native',body));j=dict(body,id='job',state='queued');store.put('job','job',j);return j
    app=FastAPI();R.routes(app,store,cfg,lambda:'operator',create,investigate,submit)
    return TestClient(app),store,cfg,calls


def payload(**kw):return {'client_id':str(uuid.uuid4()),'description':'Replace the player with a requested donor',**kw}


def test_generic_request_is_pinned_durable_dispatched_once_and_not_a_fake_build(tmp_path):
    client,store,cfg,calls=setup(tmp_path);store.put('session','sid',{'game_id':'game','mod':'base'})
    body=payload(session_id='sid');a=client.post('/api/games/game/build-requests',json=body)
    assert a.status_code==200,a.text
    r=a.json();assert r['base_mod']=='base' and 'build' not in r and calls[0][0]=='agent'
    assert 'never' in calls[0][1][2].lower() or 'without automatically' in calls[0][1][2].lower()
    assert client.post('/api/games/game/build-requests',json=body).json()['id']==r['id']
    assert len(calls)==1 and len(store.all('request'))==1
    assert client.post('/api/games/game/build-requests',json=body|{'description':'Changed'}).status_code==409
    assert client.post('/api/games/other/build-requests',json=payload(session_id='sid')).status_code==409
    assert client.get('/api/games/game/build-requests').json()['items'][0]['id']==r['id']


def test_free_text_never_guesses_a_native_recipe(tmp_path):
    client,store,cfg,calls=setup(tmp_path)
    client.post('/api/games/49b6a2f65aca26a2/build-requests',json=payload(description='Do not replace Mario with Sonic 2'))
    assert calls[0][0]=='agent'
    client.post('/api/games/49b6a2f65aca26a2/build-requests',json=payload(recipe='sonic2_player'))
    assert calls[1][0]=='native' and calls[1][1]['input']['game_id']=='49b6a2f65aca26a2'
    assert calls[1][1]['input'].get('launch') is None
    assert client.post('/api/games/other/build-requests',json=payload(recipe='sonic2_player')).status_code==422


def test_publish_requires_real_same_game_image_and_never_accepts_path_escape(tmp_path):
    client,store,cfg,calls=setup(tmp_path);r=client.post('/api/games/game/build-requests',json=payload()).json()
    path=f'/api/games/game/build-requests/{r["id"]}/result'
    assert client.post(path,json={'name':'missing'}).status_code==409
    folder=cfg.cache/'mods/game/built';folder.mkdir(parents=True);(folder/'game.nes').write_bytes(b'rom')
    marker=folder/'.gbox-mod.json';marker.write_text(json.dumps({'game_id':'other','image':'game.nes'}))
    assert client.post(path,json={'name':'built'}).status_code==409
    marker.write_text(json.dumps({'game_id':'game','image':'../../private.nes'}))
    assert client.post(path,json={'name':'built'}).status_code==409
    marker.write_text(json.dumps({'game_id':'game','image':'game.nes'}))
    out=client.post(path,json={'name':'built'}).json();assert out['build']['name']=='built' and not out['build']['verified']
    (folder/'game.nes').unlink()
    assert 'build' not in client.get('/api/games/game/build-requests').json()['items'][0]


def test_photo_recipe_requires_its_own_preview_and_original_image(tmp_path):
    client,store,cfg,calls=setup(tmp_path);photo='a'*64;cid='b'*32
    body=payload(photo=photo,recipe='photo_face',mapping={'candidate':cid})
    assert client.post('/api/games/game/build-requests',json=body).status_code==422
    store.put('artifact',photo,{'provenance':{'photo_skin_source':True}})
    folder=cfg.data_dir/'sprite-face-candidates'/cid;folder.mkdir(parents=True)
    (folder/'candidate.json').write_text(json.dumps({'game_id':'other','photo':photo}))
    assert client.post('/api/games/game/build-requests',json=body).status_code==409
    (folder/'candidate.json').write_text(json.dumps({'game_id':'game','photo':photo}))
    response=client.post('/api/games/game/build-requests',json=body);assert response.status_code==200,response.text
    r=store.get('request',response.json()['id']);assert r['attachments'][0]['sha256']==photo
    assert calls[-1][1]['tool']=='photo_sprite_build'


def test_n64_boot_scope_cannot_be_published_as_a_gameplay_only_recipe(tmp_path):
    client,store,cfg,calls=setup(tmp_path)
    body=payload(recipe='photo_face',projection_scope='both')
    response=client.post('/api/games/b7aecee966090bfa/build-requests',json=body)
    assert response.status_code==422 and 'Goddard' in response.text
    body=payload(recipe='agent',projection_scope='both',description='Project the photo onto gameplay Mario and the boot head')
    result=client.post('/api/games/b7aecee966090bfa/build-requests',json=body)
    assert result.status_code==200
    report=store.get('request',result.json()['id'])
    assert report['context']['projection_scope']=='both' and 'both' in calls[-1][1][2]


def test_real_server_registers_dialog_routes_and_native_build_job(cfg):
    from gbox.server import create_app
    from gbox.registry import REGISTRY
    app=create_app(cfg);store=app.state.store
    store.upsert_catalog([{'game_id':'49b6a2f65aca26a2','title':'Mario','system':'NES','platform':'nes','library_id':'test','relative_path':'mario.nes'}])
    client=TestClient(app,headers={'Authorization':'Bearer '+cfg.token()})
    assert 'smb1_sprite_build' in REGISTRY and 'photo_sprite_build' in REGISTRY
    result=client.post('/api/games/49b6a2f65aca26a2/build-requests',json=payload(recipe='sonic2_player'))
    assert result.status_code==200,result.text
    assert not result.json().get('dispatch_error'),result.text
    assert result.json()['jobs'][0]['tool']=='smb1_sprite_build'
