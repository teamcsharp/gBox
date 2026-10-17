import base64
from io import BytesIO

import pytest
from PIL import Image
from fastapi.testclient import TestClient
from gbox.build_report_images import evidence_images, annotation_frame
from tests.test_builds import fixture, GID


def png(color='red', size=(8, 8)):
    out = BytesIO()
    Image.new('RGB', size, color).save(out, 'PNG')
    return out.getvalue()


def b64(color='red'):
    return base64.b64encode(png(color)).decode()


def evidence():
    return {'image_b64': b64(), 'original_image_b64': b64('blue'),
            'reference_images': [{'name': '../unsafe.jpg', 'b64': b64('green')}]}


@pytest.mark.parametrize('change', [
    {'image_b64': 'invalid'}, {'original_image_b64': b64()[:12]},
    {'reference_images': [{}]}, {'reference_images': [None]},
    {'reference_images': [{}] * 4}, {'reference_images': 'not a list'},
    {'image_b64': 'a' * (6 << 20)},
])
def test_invalid_evidence_refused(change):
    with pytest.raises(ValueError):
        evidence_images(evidence() | change)


def test_images_are_validated_and_references_labelled():
    image, attachments = evidence_images(evidence())
    assert image == b64()
    assert [a['name'] for a in attachments] == ['original-game-frame.png', 'annotated-game-frame.png', 'character-reference-1.png']
    assert base64.b64decode(attachments[-1]['b64']) == png('green')
    assert annotation_frame(png()) == png()
    with Image.open(BytesIO(annotation_frame(png(size=(4000, 3000))))) as frame:
        assert frame.size == (1600, 1200)


def test_capture_is_authenticated_nonmutating_and_accepts_only_live_sessions(tmp_path):
    cfg, app, store, headers = fixture(tmp_path)
    sid = 'live-annotation'
    session = {'session_id': sid, 'state': 'running', 'game_id': GID, 'mod': 'g1_patch'}
    store.put('session', sid, session)
    with TestClient(app) as client:
        assert app.state.built_mods.wait(10)
        route = f'/api/sessions/{sid}/report-frame'
        assert client.post(route).status_code == 401
        assert client.post(f'/api/sessions/{sid}/frame', headers=headers, content=png()).status_code == 200
        mods_before = store.all('mod')
        requests_before = store.all('request')
        shot = client.post(route, headers=headers)
        assert shot.status_code == 200, shot.text
        assert base64.b64decode(shot.json()['image_b64']) == png()
        assert store.get('session', sid) == session
        assert store.all('mod') == mods_before
        assert store.all('request') == requests_before
        assert not store.all('job')
        store.put('session', sid, session | {'state': 'ended'})
        assert client.post(route, headers=headers).status_code == 409
        assert client.post('/api/sessions/missing/report-frame', headers=headers).status_code == 404


def test_marked_frame_reaches_ticket_with_reference_and_exact_build(tmp_path, monkeypatch):
    from gbox import hermes_task_mode
    monkeypatch.setenv('GBOX_HERMES_DISPATCH_STATE', str(tmp_path / 'dispatch'))
    monkeypatch.setenv('GBOX_HERMES_HOME', str(tmp_path / 'hermes'))
    monkeypatch.setattr(hermes_task_mode, '_job', lambda: {'no_agent': True, 'enabled': True})
    cfg, app, store, h = fixture(tmp_path)
    sid = 'annotated-running'
    store.put('session', sid, {'session_id': sid, 'game_id': GID, 'title': 'Game One', 'state': 'running',
                              'mod': 'g1_patch~abc123', 'detail': {'worker_name': 'MYPC'}})
    body = {'reason': 'broken', 'note': '1. Black splotches on the hat.', 'session_id': sid, 'evidence': evidence()}
    with TestClient(app) as client:
        assert app.state.built_mods.wait(10)
        route = f'/api/builds/{GID}/g1_patch/report'
        requests_before = store.all('request')
        invalid = client.post(route, headers=h, json=body | {'evidence': {'image_b64': 'bad'}})
        assert invalid.status_code == 422
        assert store.all('request') == requests_before
        wrong = client.post(f'/api/builds/{GID}/cast_g1_wrestlers/report', headers=h, json=body)
        assert wrong.status_code == 409
        response = client.post(route, headers=h, json=body)
        assert response.status_code == 200, response.text
        report = store.get('request', response.json()['id'])
        assert store.read_artifact(report['image']) == png()
        assert report['context']['annotated_build_report']
        assert report['context']['runtime_mod'] == 'g1_patch~abc123'
        assert report['context']['build'] == f'{GID}/g1_patch'
        assert body['note'] in report['body']
        assert 'comparison references, not proof of in-game output' in report['body']
        atts = {a['name']: a for m in report['messages'] for a in m.get('attachments', [])}
        assert store.read_artifact(atts['original-game-frame.png']['sha256']) == png('blue')
        assert store.read_artifact(atts['character-reference-1.png']['sha256']) == png('green')
        assert response.json()['dispatch'] == 'hermes_queue'
        assert not store.all('job'), 'a supplied still must not trigger a recapture, save, pause or launch'
