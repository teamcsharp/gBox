"""Recovery control remains bounded, authenticated and independent of game jobs."""
import time

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from gbox.desktop_admin import AdminPoll, AdminQueue, AdminRequest, AdminResult, authorized_rebuild
from gbox.federation import Federation
from gbox.store import Store, canon, sha256

AUTH, KEY, WID, RID, CONTROL, EPOCH = 'a'*64, 'b'*64, 'c'*16, 'd'*32, 'e'*32, 'f'*32


@pytest.fixture
def admin(tmp_path):
    store = Store(tmp_path/'admin')
    now = [1000.]
    fed = Federation(store, claim=lambda *a: None, accept_result=lambda *a: None, clock=lambda: now[0])
    store.put('federation', AUTH, {'authority': AUTH, 'key_hash': fed.key_hash(KEY),
                                'worker_id': WID, 'epoch': EPOCH, 'last_seen': now[0]})
    store.put('worker', WID, {'id': WID, 'name': 'exact-i9', 'os': 'windows',
                            'tools': ['rebuild_node'], 'last_seen': now[0], 'federation': {'authority': AUTH}})
    queue = AdminQueue(fed)
    queue.now = now
    yield queue
    store.db.close()


def request(**changes):
    return AdminRequest(installation=AUTH, request_id=RID, op='relaunch', force=True, **changes)


def poll(**changes):
    return AdminPoll(**({'controller_id': CONTROL, 'epoch': EPOCH,
                        'worker_id': WID, 'worker_state': 'running'} | changes))


def enqueue(queue):
    queue.poll(AUTH, KEY, poll())
    return queue.request(WID, request(), 'agent')


def record(queue):
    return queue.status(WID, AUTH, RID)


def test_force_request_is_exactly_bound_and_keeps_agent_identity(admin):
    row = enqueue(admin)
    assert row['actor'] == 'agent' and row['state'] == 'queued'
    assert row['worker_id'] == WID and row['authority'] == AUTH
    assert admin.store.all('job') == []
    assert admin.request(WID, request(), 'agent') == row
    with pytest.raises(HTTPException) as error:
        admin.request('0'*16, request(), 'agent')
    assert error.value.status_code == 409
    with pytest.raises(HTTPException):
        admin.request(WID, request(), 'operator')


def test_only_paired_windows_host_and_explicit_force_can_request(admin):
    with pytest.raises(HTTPException):
        admin.request(WID, request(), 'agent')  # supervisor is not installed/online
    admin.poll(AUTH, KEY, poll())
    for body, wid in ((AdminRequest(installation=AUTH, request_id=RID, op='relaunch'), WID),
                      (AdminRequest(installation='1'*64, request_id=RID, op='relaunch', force=True), WID),
                      (request(), '1'*16)):
        with pytest.raises(HTTPException):
            admin.request(wid, body, 'agent')
    worker = admin.store.get('worker', WID)
    admin.store.put('worker', WID, worker | {'os': 'linux'})
    with pytest.raises(HTTPException):
        admin.request(WID, request(), 'agent')
    assert admin.store.all('desktop_admin') == []


def test_worker_outage_does_not_stop_admin_delivery_or_forge_heartbeat(admin):
    enqueue(admin)
    owner = admin.store.get('federation', AUTH)
    worker = admin.store.get('worker', WID)
    admin.store.put('worker', WID, worker | {'last_seen': 0})
    admin.now[0] += 10
    result = admin.poll(AUTH, KEY, poll(worker_id=None, worker_state='unavailable'))
    assert len(result['commands']) == 1
    command = result['commands'][0]
    assert command['controller_id'] == CONTROL and command['worker_id'] == WID
    assert admin.store.get('worker', WID)['last_seen'] == 0
    assert admin.store.get('federation', AUTH) == owner
    assert admin.poll(AUTH, KEY, poll())['commands'] == [command]
    assert admin.request(WID, request(), 'agent')['state'] == 'offered'


def test_bad_pairing_key_and_competing_supervisor_cannot_take_command(admin):
    enqueue(admin)
    for authority, key, body in ((AUTH, '1'*64, poll()), ('1'*64, KEY, poll()),
                                 (AUTH, KEY, poll(controller_id='1'*32))):
        with pytest.raises(HTTPException):
            admin.poll(authority, key, body)
    assert record(admin)['state'] == 'queued'


def test_offered_request_never_moves_to_a_restarted_supervisor(admin):
    enqueue(admin)
    assert admin.poll(AUTH, KEY, poll())['commands']
    admin.now[0] += 31
    assert admin.poll(AUTH, KEY, poll(controller_id='1'*32))['commands'] == []
    assert record(admin)['state'] == 'unknown'
    assert admin.request(WID, request(), 'agent')['state'] == 'unknown'


def test_request_expiry_and_desktop_epoch_change_prevent_late_effect(admin):
    enqueue(admin)
    admin.now[0] += 121
    assert admin.poll(AUTH, KEY, poll())['commands'] == []
    assert record(admin)['state'] == 'expired'


def test_delayed_result_of_offered_effect_is_accepted_without_reexecution(admin):
    enqueue(admin)
    admin.poll(AUTH, KEY, poll())
    admin.now[0] += 121
    assert record(admin)['state'] == 'unknown'
    assert admin.poll(AUTH, KEY, poll())['commands'] == []
    result = AdminResult(controller_id=CONTROL, status='requested')
    assert admin.result(AUTH, KEY, RID, result)['accepted']
    admin.now[0] += 181
    assert record(admin)['state'] == 'unknown'


def test_queued_request_for_previous_desktop_instance_is_not_executed(admin):
    enqueue(admin)
    assert admin.poll(AUTH, KEY, poll(epoch='1'*32))['commands'] == []
    assert record(admin)['state'] == 'expired'


def test_second_request_cannot_overlap_pending_recovery(admin):
    enqueue(admin)
    with pytest.raises(HTTPException):
        admin.request(WID, AdminRequest(installation=AUTH, request_id='1'*32, op='relaunch', force=True), 'agent')
    assert len(admin.store.all('desktop_admin')) == 1


def test_result_is_once_only_and_requested_is_not_a_recovery_claim(admin):
    enqueue(admin)
    result = AdminResult(controller_id=CONTROL, status='requested', detail='relaunch_requested')
    with pytest.raises(HTTPException):
        admin.result(AUTH, KEY, RID, result)  # not offered
    admin.poll(AUTH, KEY, poll())
    with pytest.raises(HTTPException):
        admin.result(AUTH, KEY, RID, result.model_copy(update={'controller_id': '1'*32}))
    assert admin.result(AUTH, KEY, RID, result)['state'] == 'requested'
    assert admin.result(AUTH, KEY, RID, result)['accepted']
    with pytest.raises(HTTPException):
        admin.result(AUTH, KEY, RID, result.model_copy(update={'status': 'failed'}))
    assert admin.poll(AUTH, KEY, poll())['commands'] == []
    assert record(admin)['state'] == 'requested'
    admin.poll(AUTH, KEY, poll(epoch='1'*32, worker_id=None, worker_state='unavailable'))
    assert record(admin)['state'] == 'service_returned'
    # A new UI/service alone does not prove that a worker registered successfully.
    admin.poll(AUTH, KEY, poll(epoch='1'*32, worker_id='2'*16))
    assert record(admin)['state'] == 'service_returned'
    owner = admin.store.get('federation', AUTH)
    admin.store.put('federation', AUTH, owner | {'epoch': '1'*32, 'worker_id': '2'*16})
    admin.poll(AUTH, KEY, poll(epoch='1'*32, worker_id='2'*16))
    assert record(admin)['state'] == 'recovered'


def test_rebuild_admission_requires_server_record_or_exact_bridge_mapping(admin):
    stamp = {'key': AUTH+':'+RID, 'authority': AUTH, 'worker_id': WID, 'job_id': '1'*32}
    job = {'id': '1'*32, 'tool': 'rebuild_node', 'require_worker': WID, 'actor': 'agent',
           'input': {'force': True}, 'origin': {'desktop_admin': stamp}}
    assert not authorized_rebuild(admin.store, job)
    admin.store.put('desktop_admin', stamp['key'], {'job_id': job['id'], 'op': 'rebuild', 'actor': 'agent',
        'worker_id': WID, 'job_input_sha256': sha256(canon(job['input']))})
    assert authorized_rebuild(admin.store, job)
    assert not authorized_rebuild(admin.store, job | {'input': {'force': True, 'delay_s': 1}})
    assert not authorized_rebuild(admin.store, job | {'require_worker': '2'*16})
    local = job | {'id': '2'*32, 'origin': {'desktop_admin': stamp, 'desktop_federation_key': 'mapping',
        'desktop_federation_authority': AUTH, 'central_origin': {'desktop_admin': stamp}}}
    assert not authorized_rebuild(admin.store, local)
    admin.store.put('desktop_bridge_job', 'mapping', {'local_job_id': local['id'], 'id': job['id'],
        'authority': AUTH, 'tool': 'rebuild_node', 'execution_input_sha256': sha256(canon(local['input']))})
    assert authorized_rebuild(admin.store, local)
    assert not authorized_rebuild(admin.store, local | {'id': '3'*32})


def test_successful_rebuild_requires_and_records_fresh_worker_return(admin):
    def submit(wid, enable, actor, stamp):
        job = {'id': '1'*32, 'tool': 'rebuild_node', 'require_worker': wid, 'actor': actor,
               'input': {'force': True, 'enable_remote_admin': enable}, 'state': 'queued',
               'origin': {'desktop_admin': stamp}}
        admin.store.put('job', job['id'], job)
        return job
    admin.submit = submit
    admin.poll(AUTH, KEY, poll(epoch=None, worker_id=None, worker_state='unavailable'))
    body = AdminRequest(installation=AUTH, request_id=RID, op='rebuild', force=True, enable_remote_admin=True)
    row = admin.request(WID, body, 'agent')
    job = admin.store.get('job', row['job_id'])
    assert row['state'] == 'rebuilding' and authorized_rebuild(admin.store, job)
    admin.store.put('job', job['id'], job | {'state': 'succeeded', 'output': {'restart': 'scheduled'}})
    assert record(admin)['state'] == 'requested'
    admin.poll(AUTH, KEY, poll(epoch=EPOCH, worker_id=WID))
    assert record(admin)['state'] == 'requested'  # old worker answering is not a verified restart
    admin.poll(AUTH, KEY, poll(epoch='1'*32, worker_state='unavailable', worker_id=None))
    assert record(admin)['state'] == 'service_returned'
    owner = admin.store.get('federation', AUTH)
    admin.store.put('federation', AUTH, owner | {'epoch': '1'*32, 'worker_id': '2'*16})
    admin.poll(AUTH, KEY, poll(epoch='1'*32, worker_id='2'*16))
    assert record(admin)['state'] == 'recovered'


@pytest.mark.parametrize('missing', ['', 'epoch', 'fresh_owner', 'fresh_worker', 'old_offline', 'authority', 'timeout'])
def test_replaced_worker_cannot_reserve_rebuild_forever(admin, missing):
    jid, replacement = '1'*32, '2'*16
    row={'id': RID, 'authority': AUTH, 'worker_id': WID, 'op': 'rebuild', 'state': 'rebuilding',
         'job_id': jid, 'created': 1000., 'epoch': EPOCH, 'actor': 'agent'}
    job={'id': jid, 'tool': 'rebuild_node', 'require_worker': WID, 'state': 'running'}
    admin.store.put('desktop_admin', AUTH+':'+RID, row)
    admin.store.put('job', jid, job)
    admin.now[0]=5000.
    current={'id':replacement,'os':'windows','last_seen':5000.,'federation':{'authority':AUTH}}
    owner=admin.store.get('federation',AUTH)|{'worker_id':replacement,'epoch':'3'*32,'last_seen':5000.}
    if missing=='epoch':owner['epoch']=EPOCH
    if missing=='fresh_owner':owner['last_seen']=4000.
    if missing=='fresh_worker':current['last_seen']=4000.
    if missing=='authority':current['federation']['authority']='4'*64
    if missing=='old_offline':admin.store.put('worker',WID,admin.store.get('worker',WID)|{'last_seen':5000.})
    if missing=='timeout':admin.now[0]=4700.;owner['last_seen']=4700.;current['last_seen']=4700.
    admin.store.put('federation',AUTH,owner)
    admin.store.put('worker',replacement,current)
    result=record(admin)
    assert result['state']==('rebuilding' if missing else 'unknown')
    assert admin.store.get('job',jid)==job  # no invented terminal receipt or replay
    if not missing:
        assert result['detail']=='rebuild_worker_replaced_without_result'
        assert record(admin)==result


def test_real_bridge_submission_keeps_exact_rebuild_admission(admin):
    from gbox.desktop_bridge import Submissions
    stamp = {'key': AUTH+':'+RID, 'authority': AUTH, 'worker_id': WID, 'job_id': '1'*32}
    command = {'id': '1'*32, 'tool': 'rebuild_node', 'actor': 'agent', 'input': {'force': True},
               'origin': {'desktop_admin': stamp}}
    command['input_sha256'] = sha256(canon(command['input']))
    command['command_sha256'] = sha256(canon({k: command[k] for k in ('tool', 'input')}))
    def submit(command, worker, provenance):
        row = {'id': '2'*32, 'tool': command['tool'], 'input': command['input'], 'actor': command['actor'],
               'require_worker': worker['id'], 'origin': provenance, 'state': 'queued'}
        admin.store.put('job', row['id'], row)
        return row
    bridge = Submissions(admin.store, submit, AUTH, 'http://central.example')
    local = bridge.accept(command, {'id': WID, 'tools': ['rebuild_node']})
    assert authorized_rebuild(admin.store, local)
    assert bridge.accept(command, {'id': WID, 'tools': ['rebuild_node']})['id'] == local['id']


def test_http_agent_rebuild_keeps_actor_and_existing_permissions(cfg):
    from gbox.server import create_app
    cfg.granted_permissions.append('install')
    app = create_app(cfg)
    store = app.state.store
    now = time.time()
    store.put('federation', AUTH, {'authority': AUTH, 'key_hash': Federation.key_hash(KEY),
                                 'worker_id': WID, 'epoch': EPOCH, 'last_seen': now})
    store.put('worker', WID, {'id': WID, 'name': 'exact-i9', 'os': 'windows', 'tools': ['rebuild_node'],
                            'last_seen': now, 'federation': {'authority': AUTH}, 'unavailable': {}})
    client = TestClient(app, headers={'authorization': 'Bearer '+cfg.token(), 'x-gbox-actor': 'agent'})
    # Existing route remains operator-only; no actor impersonation or blanket bypass.
    assert client.post('/api/workers/'+WID+'/rebuild', json={'force': True}).status_code == 403
    body = {'installation': AUTH, 'request_id': RID, 'op': 'rebuild', 'force': True, 'enable_remote_admin': True}
    response = client.post('/api/workers/'+WID+'/admin', json=body)
    assert response.status_code == 200, response.text
    row = response.json()
    job = store.get('job', row['job_id'])
    assert job['actor'] == 'agent' and job['agent_use'] is True
    assert job['require_worker'] == WID and authorized_rebuild(store, job)
    assert client.post('/api/workers/'+WID+'/admin', json=body).json()['job_id'] == job['id']
    # A modified command identity cannot target another PC or become a shell command.
    assert client.post('/api/workers/'+WID+'/admin', json=body | {'op': 'shell'}).status_code == 422
    assert client.post('/api/workers/'+'2'*16+'/admin', json=body).status_code == 409
    # An explicit admin rebuild remains claimable without idle/GPU evidence.
    # A generic agent job with the same tool/force retains background admission.
    generic = client.post('/api/jobs', json={'tool': 'rebuild_node', 'require_worker': WID,
                                           'input': {'force': True}})
    assert generic.status_code == 200, generic.text
    assert not authorized_rebuild(store, generic.json())
    claimed = client.post('/api/workers/'+WID+'/claim', json={})
    assert claimed.status_code == 200, claimed.text
    assert claimed.json()['id'] == job['id']
    assert store.get('job', generic.json()['id'])['state'] == 'queued'
    cfg.granted_permissions.remove('install')
    assert client.post('/api/workers/'+WID+'/admin', json=body | {'request_id': '2'*32}).status_code == 403


@pytest.mark.parametrize('launch_status', ['requested', 'unknown', 'failed'])
def test_verified_closed_sessions_only_retire_exact_original_worker_rows(admin, launch_status):
    sid = WID+'-'+'1'*32
    other = '2'*16+'-'+'2'*32
    for identity, pid in ((sid, 123), (other, 456)):
        admin.store.put('session', identity, {'session_id': identity, 'state': 'running',
            'detail': {'pid': pid, 'process_created': 99.}, 'federation': {'authority': AUTH}})
    enqueue(admin)
    command = admin.poll(AUTH, KEY, poll())['commands'][0]
    assert command['sessions'] == [{'session_id': sid, 'pid': 123, 'created': 99.}]
    for evidence in ({'session_id': other, 'pid': 456, 'created': 99.},
                     {'session_id': sid, 'pid': 124, 'created': 99.},
                     {'session_id': sid, 'pid': 123, 'created': 100.}):
        with pytest.raises(HTTPException):
            admin.result(AUTH, KEY, RID, AdminResult(controller_id=CONTROL, status=launch_status,
                                                   closed_sessions=[evidence]))
        assert admin.store.get('session', sid)['state'] == 'running'
    result = AdminResult(controller_id=CONTROL, status=launch_status,
                         closed_sessions=[{'session_id': sid, 'pid': 123, 'created': 99.}])
    assert admin.result(AUTH, KEY, RID, result)['accepted']
    assert admin.store.get('session', sid)['exit']['via'] == 'desktop_admin_recovery'
    assert admin.store.get('session', other)['state'] == 'running'
    assert admin.result(AUTH, KEY, RID, result)['accepted']


def test_changed_pid_after_request_cannot_be_retired_by_old_evidence(admin):
    sid = WID+'-'+'1'*32
    row = {'session_id': sid, 'state': 'running', 'detail': {'pid': 123, 'process_created': 99.},
           'federation': {'authority': AUTH}}
    admin.store.put('session', sid, row)
    enqueue(admin)
    admin.poll(AUTH, KEY, poll())
    admin.store.put('session', sid, row | {'detail': {'pid': 124, 'process_created': 100.}})
    with pytest.raises(HTTPException):
        admin.result(AUTH, KEY, RID, AdminResult(controller_id=CONTROL, status='requested',
            closed_sessions=[{'session_id': sid, 'pid': 123, 'created': 99.}]))
    assert admin.store.get('session', sid)['state'] == 'running'


def test_pid_only_sessions_are_not_force_close_candidates(admin):
    sid = WID+'-'+'1'*32
    admin.store.put('session', sid, {'session_id': sid, 'state': 'running', 'detail': {'pid': 123},
                                    'federation': {'authority': AUTH}})
    enqueue(admin)
    assert admin.poll(AUTH, KEY, poll())['commands'][0]['sessions'] == []
    with pytest.raises(HTTPException):
        admin.result(AUTH, KEY, RID, AdminResult(controller_id=CONTROL, status='requested',
            closed_sessions=[{'session_id': sid, 'pid': 123, 'created': 99.}]))


def test_federation_snapshot_keeps_native_creation_time(admin):
    from gbox.models import WorkerInfo
    sid = WID+'-'+'1'*32
    body = {'epoch': EPOCH, 'worker': WorkerInfo(id=WID, name='exact-i9', os='windows', tools=[]).model_dump(),
            'sessions': [{'session_id': sid, 'game_id': 'fixture', 'adapter': 'retroarch', 'state': 'running',
                          'detail': {'pid': 123, 'process_created': 99.25}}]}
    admin.fed.snapshot(AUTH, KEY, body)
    assert admin.store.get('session', sid)['detail']['process_created'] == 99.25


def test_no_app_or_worker_recovery_requires_closed_witness_before_new_snapshot(admin):
    from gbox.models import WorkerInfo
    sid = WID+'-'+'1'*32
    admin.store.put('session', sid, {'session_id': sid, 'game_id': 'fixture', 'adapter': 'retroarch',
        'state': 'running', 'detail': {'pid': 123, 'process_created': 99.}, 'federation': {'authority': AUTH}})
    unavailable = poll(epoch=None, worker_id=None, worker_state='unavailable')
    admin.poll(AUTH, KEY, unavailable)
    assert admin.request(WID, request(), 'agent')['epoch'] is None
    command = admin.poll(AUTH, KEY, unavailable)['commands'][0]
    assert command['epoch'] is None and command['worker_id'] == WID
    replacement = {'epoch': '2'*32,
        'worker': WorkerInfo(id='3'*16, name='exact-i9', os='windows', tools=[]).model_dump(), 'sessions': []}
    with pytest.raises(HTTPException):
        admin.fed.snapshot(AUTH, KEY, replacement)
    assert admin.store.get('session', sid)['state'] == 'running'
    result = AdminResult(controller_id=CONTROL, status='requested', detail='fixed gbox relaunch requested',
                         closed_sessions=command['sessions'])
    assert admin.result(AUTH, KEY, RID, result)['accepted']
    assert admin.fed.snapshot(AUTH, KEY, replacement)['worker_id'] == '3'*16
    admin.poll(AUTH, KEY, poll(epoch='2'*32, worker_id='3'*16))
    assert record(admin)['state'] == 'recovered'


def test_reused_pid_with_changed_creation_time_does_not_retire_replacement(admin):
    sid = WID+'-'+'1'*32
    row = {'session_id': sid, 'state': 'running', 'detail': {'pid': 123, 'process_created': 99.},
           'federation': {'authority': AUTH}}
    admin.store.put('session', sid, row)
    enqueue(admin)
    admin.poll(AUTH, KEY, poll())
    admin.store.put('session', sid, row | {'detail': {'pid': 123, 'process_created': 100.}})
    with pytest.raises(HTTPException):
        admin.result(AUTH, KEY, RID, AdminResult(controller_id=CONTROL, status='requested',
            closed_sessions=[{'session_id': sid, 'pid': 123, 'created': 99.}]))
    assert admin.store.get('session', sid)['state'] == 'running'
