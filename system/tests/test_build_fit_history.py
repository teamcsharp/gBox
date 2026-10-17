from tests.test_fit_reviews import review,GID


def test_build_history_requires_exact_game_build_and_donor(review):
    client,store,folder,job,_=review
    job['output']={'result':{'mod':'amy_v1'}}
    store.put('job',job['id'],job)
    for key,gid,name in [('wrong-game','f'*16,'amy_v1'),('wrong-build',GID,'amy_v2')]:
        store.put('job',key,{**job,'id':key,'input':{'game_id':gid},'output':{'result':{'mod':name}}})
    data=client.get(f'/api/builds/{GID}/amy_v1/fitting?donor=amy').json()
    assert [j['job_id'] for j in data['jobs']]==['fit-job']
    assert data['jobs'][0]['models'][0]['comparison_available']
    assert data['jobs'][0]['models'][0]['triangles']['source_triangles']==1
    assert client.get(f'/api/builds/{GID}/amy_v1/fitting?donor=sonic').json()['jobs']==[]
    (folder/'before.glb').unlink()
    assert not client.get(f'/api/builds/{GID}/amy_v1/fitting').json()['jobs'][0]['models'][0]['comparison_available']


def test_unknown_build_does_not_reuse_the_latest_game_fit(review):
    client,*_=review
    assert client.get(f'/api/builds/{GID}/unknown/fitting').json()['jobs']==[]
