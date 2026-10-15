"""Owned-disc identities, source provenance, unique plans and pinned drop dispatch."""
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from gbox import pso_api, psoitems, pso_loadouts as L
from gbox.config import Config
from gbox.models import Permission


def weapon(code, name, atp=100, grind=10, classes=('HUmar',), **kwargs):
    return L.enrich({'code': code, 'name': name, 'cat': 'Weapons', 'stars': 12,
        'atp_max': atp, 'max_grind': grind, 'ata': 30, 'classes': list(classes), **kwargs}, 'gc')


def test_s_rank_names_are_special_variants_not_seventeen_unrelated_axes():
    axes = [weapon(f'00a9{i:02x}', 'AXE', 200, 250) for i in range(17)]
    assert len({r['family_key'] for r in axes}) == 1
    assert axes[0]['family_name'] == 'S-Rank Axe'
    assert axes[10]['display_name'] == 'S-Rank Axe — Hell'
    assert axes[14]['variant_name'] == 'Gush'
    assert axes[0]['max_grind_atp'] == 700
    assert axes[0]['thumbnail_url'] == 'https://wiki.pioneer2.net/images/b/b2/ES_Axe.png'
    assert axes[0]['reference_url'] == 'https://wiki.pioneer2.net/w/ES_Axe'
    assert axes[0]['code'] == '00a900' and axes[0]['name'] == 'AXE'
    result=L.plan(axes,'gc',names=['ES Axe', 'S-Rank Axe — Hell'])
    assert result['codes']==['00a900','00a90a']


def test_atp_ranking_deduplicates_families_and_uses_native_grind_not_stars():
    rows=[weapon(f'00a9{i:02x}', 'AXE',200,250) for i in range(17)]
    rows += [weapon('003200','TSUMIKIRI J-SWORD',756,50),
             weapon('000100','Saber',40,35), weapon('005600','Ranger gun',900,0,classes=['RAmar'])]
    result=L.plan(rows,'gc',preset='atp',character_class='HUmar',count=10)
    assert result['codes']==['003200','00a900','000100']
    assert 'not DPS' in result['note']
    assert len(result['warnings'])==1 and 'no unavailable' in result['warnings'][0]


def test_researched_names_only_resolve_this_disc_and_class_and_never_invent_items():
    rows=[weapon('003200','TSUMIKIRI J-SWORD'),weapon('001d00','SPREAD NEEDLE',classes=['RAmar']),
          weapon('004d00','PSYCHO WAND',classes=['FOnewearl'])]
    result=L.plan(rows,'gc',character_class='HUmar',count=10)
    assert result['codes']==['003200']
    assert 'Spread Needle' in result['incompatible'] and 'Guld Milla' in result['missing']
    assert L.GUIDE in result['sources']
    explicit=L.plan(rows,'gc',names=['TSUMIKIRI J-SWORD','003200','Excalibur'],sources=['https://example.org/my-pso-list'])
    assert explicit['codes']==['003200'] and explicit['missing']==['Excalibur']
    assert explicit['sources']==['https://example.org/my-pso-list']


def test_ambiguous_same_name_does_not_choose_an_unrelated_code():
    rows=[{'code':'001001','name':'AGITO','cat':'Weapons','classes':['HUmar']},
          {'code':'001002','name':'AGITO','cat':'Weapons','classes':['HUmar']}]
    assert L.plan(rows,'gc',names=['AGITO'])['codes']==['001001']
    rows[1]['code']='001101'
    assert L.plan(rows,'gc',names=['AGITO'])['ambiguous']==['AGITO']


@pytest.mark.parametrize('kwargs', [dict(count=21), dict(version='bb'),dict(version='dcv2',character_class='HUcaseal'),
    dict(names=['']),dict(names=['x'*161]),dict(sources=['javascript:alert(1)']),dict(sources=['https://user:password@example.com/'])])
def test_invalid_requests_rejected_without_any_native_action(kwargs):
    args=dict(rows=[],version='gc');args.update(kwargs)
    with pytest.raises(ValueError):L.plan(**args)


def test_preview_routes_use_new_owned_cache_and_do_not_execute_drops(tmp_path):
    folder=tmp_path/'pso';folder.mkdir()
    rows=[weapon('003200','TSUMIKIRI J-SWORD')]
    (folder/f'items-gc-v{psoitems.CATALOG_SCHEMA}.json').write_text(json.dumps(rows))
    app=FastAPI();pso_api.routes(app,Config(data_dir=tmp_path),lambda:'operator');client=TestClient(app)
    assert len(client.get('/api/pso/loadouts').json()['presets'])==5
    result=client.post('/api/pso/loadouts/plan',json={'version':'gc','names':['003200']})
    assert result.status_code==200 and result.json()['codes']==['003200']
    assert client.post('/api/pso/loadouts/plan',json={'op':'drop','version':'gc'}).status_code==422
    assert client.post('/api/pso/loadouts/plan',json={'version':'../../secret'}).status_code==422


def test_llm_drop_uses_actual_session_version_single_acknowledged_rpc_no_retry(monkeypatch):
    requests=[]
    def handle(req):
        requests.append(req)
        if req.url.path=='/api/sessions':return httpx.Response(200,json=[{'session_id':'worker-session','game_id':'pso','state':'running'}])
        if req.url.path=='/api/catalog/pso':return httpx.Response(200,json={'title':'Phantasy Star Online Ver. 2','platform':'dreamcast'})
        if req.url.path=='/api/pso/items':
            assert req.url.params['version']=='dcv2'
            return httpx.Response(200,json=[weapon('003200','TSUMIKIRI J-SWORD')])
        if req.url.path.endswith('/rpc'):
            body=json.loads(req.content)
            assert body['op']=='pso_controls' and body['args']['input']['op']=='floor_spawn'
            assert body['args']['input']['codes']==['003200']
            assert body['args']['input']['session_id']=='worker-session'
            return httpx.Response(200,json={'verified':True,'spawned':1,'codes':['003200']})
        raise AssertionError(req.url)
    real=httpx.Client
    monkeypatch.setattr(httpx,'Client',lambda **kw:real(transport=httpx.MockTransport(handle),**kw))
    ctx=SimpleNamespace(server='http://spark',headers={'Authorization':'Bearer test'},config=Config(granted_permissions=[Permission.MEMORY_WRITE]))
    result=L.pso_loadout(L.LoadoutIn(session_id='worker-session',op='drop',version='gc',names=['003200']),ctx)['result']
    assert result['version']=='dcv2' and result['verified']
    assert len([r for r in requests if r.url.path.endswith('/rpc')])==1
    ctx.config.granted_permissions=[]
    with pytest.raises(PermissionError):L.pso_loadout(L.LoadoutIn(session_id='worker-session',op='drop',names=['003200']),ctx)
    assert len([r for r in requests if r.url.path.endswith('/rpc')])==1


def test_llm_timeout_does_not_resubmit_spawn(monkeypatch):
    writes=[]
    def handle(req):
        if req.url.path=='/api/pso/items':return httpx.Response(200,json=[weapon('003200','TSUMIKIRI J-SWORD')])
        if req.url.path=='/api/sessions':return httpx.Response(200,json=[{'id':'s','game_id':'pso','state':'running'}])
        if req.url.path=='/api/catalog/pso':return httpx.Response(200,json={'title':'Phantasy Star Online Episode I & II','platform':'gamecube'})
        writes.append(req);raise httpx.ReadTimeout('late',request=req)
    real=httpx.Client;monkeypatch.setattr(httpx,'Client',lambda **kw:real(transport=httpx.MockTransport(handle),**kw))
    ctx=SimpleNamespace(server='http://spark',headers={},config=Config(granted_permissions=['memory_write']))
    with pytest.raises(TimeoutError,match='not retried'):L.pso_loadout(L.LoadoutIn(session_id='s',op='drop',names=['003200']),ctx)
    assert len(writes)==1
