"""Selected-PC deletion must never remove the collection or affect unselected PCs."""
import time
import pytest
from fastapi.testclient import TestClient
from tests.test_builds import fixture, GID


def setup(tmp_path):
    cfg, app, store, headers = fixture(tmp_path)
    for wid, name in [('w3', 'JAYBUILTFINALE'), ('w4', 'OTHER-PC')]:
        store.put('worker', wid, {'id':wid,'name':name,'os':'windows','last_seen':time.time(),
            'tools':['file_mod'],'local_builds':[{'game_id':GID,'name':'g1_patch','built':2000}]})
    return cfg, app, store, headers


def delete(client, headers, nodes):
    return client.post(f'/api/builds/{GID}/g1_patch/delete',headers=headers,json={'scope':'pcs','nodes':nodes})


@pytest.mark.parametrize('nodes,expected', [
    (['i9-NUC'], ['w1']), (['JAYBUILTFINALE'], ['w3']),
    (['i9-NUC','JAYBUILTFINALE','i9-NUC'], ['w1','w3']),
])
def test_deletes_only_selected_attached_copies_and_keeps_spark(tmp_path,nodes,expected):
    cfg, app, store, h = setup(tmp_path)
    store.put('build_favorite',f'{GID}/g1_patch',{'favorite':True})
    with TestClient(app) as c:
        assert app.state.built_mods.wait(10)
        response=delete(c,h,nodes)
        assert response.status_code==200,response.text
        out=response.json()
        assert out['nodes']==list(dict.fromkeys(nodes))
        assert out['scope']=='pcs' and out['spark']['removed']==[] and out['cleared']==[]
        jobs=[store.get('job',j['job_id']) for j in out['jobs']]
        assert [j['require_worker'] for j in jobs]==expected
        assert all(j['tool']=='file_mod' and j['input']['op']=='delete_build' and j['input']['name']=='g1_patch' for j in jobs)
        assert store.all('build_deleted')[0]['nodes']==out['nodes']
        assert store.get('build_favorite',f'{GID}/g1_patch')
        assert store.get('mod','card1')
    assert (cfg.cache/'mods'/GID/'g1_patch'/'game.z64').read_bytes()==b'z'*100
    assert (cfg.cache/'mods'/GID/'g1_patch~abc123').is_dir()


@pytest.mark.parametrize('nodes', [[],None,'i9-NUC',[1],['nobody'],['spark'],['i9-NUC','spark'],['x']*65])
def test_invalid_targets_do_not_delete_anything(tmp_path,nodes):
    cfg, app, store, h=setup(tmp_path)
    with TestClient(app) as c:
        assert app.state.built_mods.wait(10)
        response=delete(c,h,nodes)
        assert response.status_code==422,response.text
        assert not store.all('job') and not store.all('build_deleted')
    assert (cfg.cache/'mods'/GID/'g1_patch').is_dir()


def test_busy_second_pc_blocks_all_jobs_but_unselected_busy_pc_does_not(tmp_path):
    cfg, app, store, h=setup(tmp_path)
    store.put('session','w3-active',{'session_id':'w3-active','game_id':GID,'state':'running','mod':'g1_patch~abc'})
    with TestClient(app) as c:
        assert app.state.built_mods.wait(10)
        response=delete(c,h,['i9-NUC','JAYBUILTFINALE'])
        assert response.status_code==409,response.text
        assert not store.all('job') and not store.all('build_deleted')
        response=delete(c,h,['i9-NUC'])
        assert response.status_code==200,response.text
        assert [j['node'] for j in response.json()['jobs']]==['i9-NUC']
    assert (cfg.cache/'mods'/GID/'g1_patch').is_dir()


def test_offline_and_stale_inventory_are_explicit_without_touching_spark(tmp_path):
    cfg, app, store, h=setup(tmp_path)
    store.put('worker','w3',store.get('worker','w3')|{'last_seen':time.time()-3600})
    with TestClient(app) as c:
        assert app.state.built_mods.wait(10)
        response=delete(c,h,['JAYBUILTFINALE'])
        assert response.status_code==200,response.text
        assert response.json()['jobs']==[]
        assert 'offline' in response.json()['skipped'][0]['reason']
        store.put('worker','w3',store.get('worker','w3')|{'local_builds':[]})
        response=delete(c,h,['i9-NUC','JAYBUILTFINALE'])
        assert response.status_code==409,response.text
        assert not store.all('job')
    assert (cfg.cache/'mods'/GID/'g1_patch').is_dir()
