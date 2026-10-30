import concurrent.futures
import hashlib
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from gbox.mercs import interventions as I
from gbox.mercs.titles import re6_switch_native as N
from gbox.store import Store


@pytest.fixture
def queue(tmp_path):
    store = Store(tmp_path)
    now = [100.0]
    q = I.Queue(store, lambda: now[0])
    q.claim('sid', 'life-1', ['flash_now'])
    yield q, now
    store.db.close()


def post(q, rid=None):
    return q.post('sid', 'flash_now', rid or str(uuid.uuid4()), 'viewer')


def test_twenty_clicks_remain_distinct_and_complete_once(queue):
    q, now = queue
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        rows = list(pool.map(lambda _: post(q), range(20)))
    claimed = q.claim('sid', 'life-1', ['flash_now'])
    assert {r['id'] for r in claimed} == {r['id'] for r in rows}
    assert q.claim('sid', 'life-1', ['flash_now']) == []
    for r in claimed:
        q.finish('sid', r['id'], r['claim'], {'state':'confirmed', 'verified':True})
    assert all(r['state'] == 'confirmed' for r in q.status('sid')['requests'])


def test_weapon_requests_keep_arguments_and_cannot_reuse_an_id_for_another_weapon(queue):
    q, _ = queue
    options = {'weapons':[{'item':25,'weapon':'Hydra'}, {'item':27,'weapon':'S&W M500'}]}
    q.claim('sid','life-1',['flash_now','equip_primary'],options=options)
    rid = str(uuid.uuid4())
    row = q.post('sid','equip_primary',rid,'viewer',{'item':25})
    assert q.status('sid')['options'] == options and row['args'] == {'item':25}
    assert q.post('sid','equip_primary',rid,'viewer',{'item':25}) == row
    with pytest.raises(ValueError,match='another operation'):
        q.post('sid','equip_primary',rid,'viewer',{'item':27})
    for args in ({'item':True}, {'item':25,'extra':1}, {}, {'item':255}):
        with pytest.raises(ValueError): q.post('sid','equip_primary',str(uuid.uuid4()),'viewer',args)
    assert q.claim('sid','life-2',['flash_now','equip_primary'],options=options) == []
    assert q.status('sid')['requests'][0]['state'] == 'expired'


def test_crash_after_claim_never_reexecutes(queue):
    q, now = queue
    row = post(q)
    claim = q.claim('sid', 'life-1', ['flash_now'])[0]
    restarted = I.Queue(q.store, lambda: now[0])
    assert restarted.claim('sid', 'life-1', ['flash_now']) == []
    now[0] += 11
    assert restarted.claim('sid', 'life-1', ['flash_now']) == []
    assert restarted.status('sid')['requests'][0]['state'] == 'uncertain'
    assert post(restarted, row['id'])['state'] == 'uncertain'
    # A recovered receipt can settle uncertainty without repeating the effect.
    restarted.finish('sid', row['id'], claim['claim'], {'state':'confirmed', 'verified':True})
    assert restarted.status('sid')['requests'][0]['state'] == 'confirmed'


@pytest.mark.parametrize('change', ['life', 'resources', 'deadline'])
def test_stale_request_cannot_affect_another_life(queue, change):
    q, now = queue
    row = post(q)
    if change == 'deadline': now[0] += I.TTL + .1
    assert q.claim('sid', 'life-2' if change=='life' else 'life-1', [] if change=='resources' else ['flash_now']) == []
    assert q.status('sid')['requests'][0]['state'] == 'expired'
    assert post(q, row['id'])['state'] == 'expired'


def test_retry_id_is_durable_after_recent_history_is_trimmed(queue):
    q, _ = queue
    first = post(q)
    for _ in range(I.KEEP + 1):
        for row in q.claim('sid', 'life-1', ['flash_now']):
            q.finish('sid', row['id'], row['claim'], {'state':'confirmed', 'verified':True})
        post(q)
    assert first['id'] not in {r['id'] for r in q.status('sid')['requests']}
    assert post(q, first['id'])['state'] == 'confirmed'
    assert first['id'] not in {r['id'] for r in q.claim('sid', 'life-1', ['flash_now'])}


def test_capacity_rejects_without_losing_accepted_clicks(queue):
    q, _ = queue
    for _ in range(I.MAX_PENDING): post(q)
    with pytest.raises(ValueError, match='full'): post(q)
    assert len(q.status('sid')['requests']) == I.MAX_PENDING


def test_batch_receipts_are_atomic_and_retries_do_not_change_a_result(queue):
    q, _ = queue
    post(q);post(q)
    claims=q.claim('sid','life-1',['flash_now'])
    batch=[{'id':r['id'],'claim':r['claim'],'result':{'state':'confirmed','verified':True}} for r in claims]
    bad=[batch[0],dict(batch[1],claim='wrong')]
    with pytest.raises(ValueError,match='claim'):q.finish_many('sid',bad)
    assert all(r['state']=='claimed' for r in q.status('sid')['requests'])
    first=q.finish_many('sid',batch)
    assert q.finish_many('sid',batch)==first


def test_no_false_confirmation_or_stale_capability(queue):
    q, now = queue
    row = post(q); claim = q.claim('sid', 'life-1', ['flash_now'])[0]
    with pytest.raises(ValueError, match='verified'):
        q.finish('sid', row['id'], claim['claim'], {'state':'confirmed'})
    with pytest.raises(ValueError, match='claim'):
        q.finish('sid', row['id'], 'other', {'state':'failed'})
    now[0] += I.FRESH + .1
    with pytest.raises(ValueError): post(q)


def test_http_routes_require_auth_and_running_session(tmp_path):
    from fastapi import HTTPException, Header
    store=Store(tmp_path); app=FastAPI()
    def auth(authorization: str = Header(default='')):
        if authorization != 'Bearer test': raise HTTPException(401)
        return 'viewer'
    I.install(app, store, auth)
    with TestClient(app) as client:
        assert client.get('/api/sessions/sid/interventions').status_code == 401
        client.headers['Authorization']='Bearer test'
        assert client.post('/api/sessions/sid/interventions', json={'op':'flash_now','request_id':str(uuid.uuid4())}).status_code == 409
        store.put('session','sid',{'state':'running'})
        assert client.post('/api/sessions/sid/interventions/claim',json={'epoch':'life','capabilities':['flash_now']}).status_code == 200
        response=client.post('/api/sessions/sid/interventions',json={'op':'flash_now','request_id':str(uuid.uuid4())})
        assert response.json()['request']['state']=='queued'
    store.db.close()


def test_pinned_native_assets_and_mapping_guards():
    for _, name, size, digest in N.CODE:
        data=N.IMAGES[name]
        assert len(data)==size and hashlib.sha256(data).hexdigest()==digest
    row='1000-2000 r-xs 00003000 00:01 12 /memfd:HostMemory (deleted)'
    assert N.backing_region([row],0x1100,32)==(0x3100,12)
    for rows,at,n in [([row],0x1ff0,32),([row,row],0x1100,32),([row.replace('HostMemory','Other')],0x1100,32),([row],0x1100,0)]:
        with pytest.raises(N.Unavailable): N.backing_region(rows,at,n)


@pytest.mark.parametrize('state,restored,recoverable,allowed', [
    (3, True, True, True), (1, True, True, False), (2, True, True, False),
    (3, False, True, False), (3, True, False, False),
])
def test_only_completed_allocation_loss_can_recover_for_a_new_click(state, restored, recoverable, allowed):
    import threading
    ctl=N.Controller.__new__(N.Controller)
    ctl.lock=threading.Lock();ctl.failed=True;ctl.recoverable=recoverable
    ctl.heap=0x1000;ctl.manager=0x2000;ctl.base=0x100000000
    ctl.check=lambda:None
    ctl.validate_heap=lambda:None
    ctl.w=lambda at:state
    ctl.q=lambda at:ctl.base+N.VT if restored else ctl.heap
    ctl.call=lambda *a:pytest.fail('Recovery must never replay the native operation')
    assert ctl.recover_completed_call() is allowed
    assert ctl.failed is (not allowed)


def test_changed_player_cannot_clear_native_failure():
    import threading
    ctl=N.Controller.__new__(N.Controller)
    ctl.lock=threading.Lock();ctl.failed=True;ctl.recoverable=True
    def changed():raise N.Unavailable('player allocation changed')
    ctl.check=changed
    with pytest.raises(N.Unavailable,match='player allocation'):
        ctl.recover_completed_call()
    assert ctl.failed
