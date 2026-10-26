"""A Stop after restart validation still fences queued automatic autoplay."""
import pytest
from fastapi.testclient import TestClient

from gbox import autoplay_resume as A
from gbox.models import Job
from tests.test_autoplay_resume import control
from tests.test_session_reset import reset_route, enclosed


def replacement(reset_route):
    cfg, app, store, _ = reset_route
    control(store, continuous=True)
    capture = A.snapshot(store, 'w-live', {})
    old = store.get('session', 'w-live')
    store.put('session', 'w-live', old | {'replaced_by': 'w-new', 'state': 'ended'})
    store.put('session', 'w-new', {'session_id': 'w-new', 'game_id': old['game_id'], 'state': 'running'})
    store.put('worker', 'w', store.get('worker', 'w') | {'tools': ['autoplay']})
    resume = A.replacement_input(store, 'w-live', 'w-new', capture)
    assert resume
    job = Job(tool='autoplay', input=resume, require_worker='w', created=30,
              origin={'via': 'autoplay_resume', 'from_session': 'w-live', 'source_job_id': 'start'})
    return store, TestClient(app, headers={'Authorization': 'Bearer ' + cfg.token()}), job


@pytest.mark.parametrize('sid', ['w-live', 'w-new'])
@pytest.mark.parametrize('when', ['before-submit', 'after-submit'])
def test_stop_after_validation_prevents_automatic_start_at_claim(reset_route, sid, when):
    store, client, job = replacement(reset_route)
    if when == 'before-submit':
        control(store, sid=sid, op='stop', ident='stop', at=20)
    store.put('job', job.id, job.model_dump())
    if when == 'after-submit':
        control(store, sid=sid, op='stop', ident='stop', at=40)
    assert client.post('/api/workers/w/claim').status_code == 204
    rejected = store.get('job', job.id)
    assert rejected['state'] == 'failed' and rejected['worker_id'] is None
    assert 'Automatic autoplay resume cancelled' in rejected['error']


@pytest.mark.parametrize('changed', ['handoff', 'source-start', 'new-start', 'different-game', 'ended'])
def test_queued_resume_rechecks_identity_and_human_control(reset_route, changed):
    store, client, job = replacement(reset_route)
    store.put('job', job.id, job.model_dump())
    if changed == 'handoff':
        assert A.note_handoff(store, 'w-live', 'start')
    elif changed in ('source-start', 'new-start'):
        control(store, sid='w-live' if changed == 'source-start' else 'w-new', ident='fresh', at=40)
    else:
        new = store.get('session', 'w-new')
        store.put('session', 'w-new', new | ({'game_id': 'other'} if changed == 'different-game' else {'state': 'ended'}))
    assert client.post('/api/workers/w/claim').status_code == 204
    assert store.get('job', job.id)['state'] == 'failed'


@pytest.mark.parametrize('automatic', [True, False])
def test_current_resume_and_ordinary_start_are_claimed(reset_route, automatic):
    store, client, job = replacement(reset_route)
    if not automatic:
        job.origin = {'via': 'internal'}
        control(store, op='stop', ident='stop', at=40)
    store.put('job', job.id, job.model_dump())
    response = client.post('/api/workers/w/claim')
    assert response.status_code == 200, response.text
    assert response.json()['id'] == job.id and response.json()['state'] == 'running'
    assert client.post('/api/workers/w/claim').status_code == 204


def test_resume_provenance_is_submitted_before_job_becomes_claimable(reset_route):
    store, _, job = replacement(reset_route)
    run_job = enclosed(reset_route[3], '_run_job').cell_contents
    def submit(req, actor, origin=None):
        assert origin == job.origin, 'no unfenced queued interval before origin is attached'
        finished = Job(tool=req.tool, input=req.input, state='succeeded', origin=origin,
                       output={'result': {'started': 'playbook'}})
        store.put('job', finished.id, finished.model_dump())
        return finished
    enclosed(run_job, 'submit').cell_contents = submit
    assert run_job('autoplay', job.input, 'operator', worker='w', origin=job.origin)['result']['started']
