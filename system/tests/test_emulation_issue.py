import base64
import io
import json

from fastapi.testclient import TestClient
from PIL import Image
import pytest

from gbox import emulation_issue as issue
from gbox.models import Job, JobState
from gbox.server import create_app


def setup_session(store):
    game = {'game_id': 'test-rom', 'title': 'VR Missions', 'platform': 'psx',
            'source_paths': ['/roms/VR Missions.7z'], 'core': 'pcsx_rearmed'}
    store.upsert_catalog([game])
    session = {'session_id': 'worker-session', 'state': 'running', 'game_id': game['game_id'],
               'title': game['title'], 'adapter': 'retroarch', 'detail': {'pid': 123, 'core': '/cores/pcsx.dll'}}
    worker = {'id': 'worker', 'name': 'idle-PC', 'os': 'windows', 'gpu': {'driver': 'test-driver'}}
    store.put('session', session['session_id'], session)
    store.put('worker', 'worker', worker)
    return game, session, worker


def test_report_immediately_keeps_markdown_screenshot_and_deduplicates(cfg, monkeypatch):
    targets = []
    class Thread:
        def __init__(self, target, **kwargs):
            targets.append(target)
        def start(self):
            pass
    monkeypatch.setattr(issue.threading, 'Thread', Thread)
    app = create_app(cfg)
    setup_session(app.state.store)
    client = TestClient(app, headers={'Authorization': f'Bearer {cfg.token()}'})
    png = b'\x89PNG\r\n\x1a\nfixture'
    payload = {'image_b64': base64.b64encode(png).decode(), 'context': {'access_token': 'private'},
               'attachments': [{'name': 'desktop-console.txt', 'type': 'text/plain',
                                'b64': base64.b64encode(b'Authorization: Bearer private-token').decode()}]}
    response = client.post('/api/sessions/worker-session/emulation-issue', json=payload)
    assert response.status_code == 200, response.text
    report, job = response.json()['request'], response.json()['job']
    assert report['status'] == 'in_progress' and report['context']['auto_report']
    assert report['context']['save_state_requested'] and report['context']['recovery_requested']
    assert report['context']['access_token'] == '[redacted]'
    assert client.get('/api/artifacts/' + report['image']).content == png
    attachments = report['messages'][0]['attachments']
    md = client.get('/api/artifacts/' + attachments[-1]['sha256']).text
    assert '/roms/VR Missions.7z' in md and '/cores/pcsx.dll' in md and 'test-driver' in md
    assert 'private' not in md
    console = client.get('/api/artifacts/' + attachments[0]['sha256']).text
    assert 'private-token' not in console
    assert job['tool'] == 'emulation_recovery' and job['parent_request_id'] == report['id']
    assert client.post('/api/sessions/worker-session/emulation-issue', json={}).json()['job']['id'] == job['id']
    # one recovery thread (create_app's own character-library warm-up thread is not this report's)
    assert len([t for t in targets if getattr(t, "__name__", "") != "_refresh_list"]) == 1


def make_incident(cfg, frame_colors, state_failure=False, resume_failure=False, covered_points=None, frame_images=None):
    app = create_app(cfg)
    store = app.state.store
    game, session, worker = setup_session(store)
    client = TestClient(app, headers={'Authorization': f'Bearer {cfg.token()}'})
    report = client.post('/api/requests', json={'title': 'Emulation issue', 'body': 'Game frozen'}).json()
    job = Job(tool='emulation_recovery', state=JobState.RUNNING, started=1,
              input={'session_id': session['session_id']}, parent_request_id=report['id'])
    store.put('job', job.id, job.model_dump())
    calls = []
    colors = iter(frame_colors)
    images = iter(frame_images) if frame_images is not None else None
    coverage = iter(covered_points) if covered_points is not None else None
    def run(tool, data, wid, wait):
        calls.append((tool, data))
        if tool == 'get_frame':
            buf = io.BytesIO()
            if images is not None:
                next(images).save(buf, format='PNG')
            else:
                Image.new('RGB', (64, 48), next(colors, 'black')).save(buf, format='PNG')
            ref = store.put_artifact(buf.getvalue(), 'frame.png', 'image/png', {})
            out = {'sha256': ref.sha256}
            if coverage is not None:
                out['covered'] = next(coverage, 0)
            return out
        if tool == 'state_transfer' and data['op'] == 'export':
            if state_failure:
                raise RuntimeError('Emulator did not write a state')
            ref = store.put_artifact(b'preserved-state', 'Game.state81', 'application/octet-stream', {})
            return {'result': {'artifact': ref.sha256, 'file': 'Game.state81', 'bytes': ref.size}}
        if tool == 'session_op' and data['op'] == 'resume' and resume_failure:
            raise RuntimeError('Emulator did not answer')
        if tool == 'launch_game':
            return {'session_id': 'worker-replacement'}
        return {'result': {'state': 'PAUSED', 'running': True}}
    incident = issue.Incident(store, report, session, game, worker, run,
                              lambda rid, number: 'hermes-cloud-job', job, sleep=lambda _: None)
    return incident, calls


def test_capture_precedes_recovery_and_paused_game_resumes_without_restart(cfg):
    incident, calls = make_incident(cfg, ['black', 'red', 'green'])
    incident.run()
    ops = [data['op'] for tool, data in calls if tool == 'session_op']
    assert 'resume' in ops
    export = next(i for i, (tool, data) in enumerate(calls) if tool == 'state_transfer' and data['op'] == 'export')
    resume = next(i for i, (tool, data) in enumerate(calls) if tool == 'session_op' and data['op'] == 'resume')
    assert export < resume
    assert not any(tool == 'launch_game' for tool, _ in calls)
    job = incident.store.get('job', incident.job.id)
    assert job['state'] == 'succeeded' and job['output']['motion']
    report = incident.store.get('request', incident.rid)
    assert report['status'] == 'open'  # recovery is distinct from completing the root-cause report
    assert report['context']['hermes_job_id'] == 'hermes-cloud-job'
    names = [a['name'] for m in report['messages'] for a in m.get('attachments', [])]
    assert 'Game.state81' in names and 'emulation-diagnostics-complete.md' in names and 'emulation-recovery.md' in names


@pytest.mark.parametrize('mod', ['', 'active-mod'])
def test_failed_checkpoint_does_not_reset_or_relaunch_running_game(cfg, mod):
    incident, calls = make_incident(cfg, ['black'] * 8, state_failure=True)
    incident.session['mod'] = mod
    incident.run()
    assert not any(tool == 'launch_game' or data.get('op') == 'reset' for tool, data in calls)
    assert incident.store.get('job', incident.job.id)['state'] == 'failed'
    report = incident.store.get('request', incident.rid)
    assert any('no portable checkpoint' in m['text'] for m in report['messages'])
    assert report['context']['hermes_job_id'] == 'hermes-cloud-job'


def test_relaunch_keeps_rom_mod_and_attached_state_but_does_not_claim_exact_restore(cfg):
    incident, calls = make_incident(cfg, ['black'] * 5 + ['red', 'green'])
    incident.session['mod'] = 'original-mod'
    incident.run()
    launch = next(data for tool, data in calls if tool == 'launch_game')
    assert launch['game']['source_paths'] == ['/roms/VR Missions.7z'] and launch['mod'] == 'original-mod'
    imports = [data for tool, data in calls if tool == 'state_transfer' and data['op'] == 'import']
    assert len(imports) == 1 and imports[0]['session_id'] == 'worker-replacement'
    assert incident.store.read_artifact(imports[0]['artifact']) == b'preserved-state'
    output = incident.store.get('job', incident.job.id)['output']
    assert output['motion'] and output['checkpoint_load_requested'] and output['moment_restored'] is False
    assert incident.store.get('session', 'worker-session')['replaced_by'] == 'worker-replacement'


def test_black_rgb_frame_is_detected_and_static_menu_is_not_claimed_recovered(cfg):
    incident, _ = make_incident(cfg, ['black', 'white', 'white', 'white', 'white'])
    _, luma, covered = incident.frame('before')
    assert luma == 0 and covered == 0
    assert incident.observe() == {'visible': True, 'motion': False, 'errors': []}


@pytest.mark.parametrize('covered', [1, 9])
def test_covered_frame_pixels_are_retained_but_do_not_prove_recovery(cfg, covered):
    incident, _ = make_incident(cfg, ['black', 'red', 'green', 'white'], covered_points=[covered]*4)
    observed = incident.observe()
    assert observed['visible'] is False and observed['motion'] is False
    assert any('covered by another window' in e for e in observed['errors'])
    messages = incident.store.get('request', incident.rid)['messages']
    frames = [m for m in messages if m.get('task_step', {}).get('action') == 'verify recovery frame']
    assert len(frames) == 4 and all(m['attachments'] for m in frames)
    assert all(f'{covered}/9 capture points' in m['text'] for m in frames)


@pytest.mark.parametrize(('colors', 'coverage'), [
    (['red', 'white', 'white', 'white'], [9, 0, 0, 0]),
    (['white', 'red', 'white', 'white'], [0, 9, 0, 0]),
])
def test_clearing_an_occluder_is_not_moving_gameplay(cfg, colors, coverage):
    incident, _ = make_incident(cfg, colors, covered_points=coverage)
    assert incident.observe() == {'visible': True, 'motion': False, 'errors': []}


def test_two_clear_frames_can_prove_motion_after_occlusion(cfg):
    incident, _ = make_incident(cfg, ['white', 'white', 'red', 'green'], covered_points=[9, 1, 0, 0])
    assert incident.observe() == {'visible': True, 'motion': True}


def banded_frame(body, hud=None, size=(96, 72), band_rows=14):  # top ~20% HUD band of the probe frame
    from PIL import ImageDraw
    img = Image.new('RGB', size, body)
    if hud is not None:
        ImageDraw.Draw(img).rectangle((0, 0, size[0], band_rows - 1), fill=hud)  # PIL bottom edge is inclusive
    return img


def test_hud_timer_ticking_on_black_scene_is_not_recovery_motion(cfg):
    # MK4 with angrylion+HLE: every 3D layer is black while the CPU-drawn HUD
    # timer keeps counting down. That must not be accepted as restored gameplay.
    frames = [banded_frame('black', hud=c) for c in ('white', 'red', 'blue', 'green')]
    incident, _ = make_incident(cfg, [], frame_images=frames)
    observed = incident.observe()
    assert observed['visible'] is True and observed['motion'] is False


def test_playfield_change_with_static_hud_is_recovery_motion(cfg):
    frames = [banded_frame('black', hud='white'), banded_frame('green', hud='white'),
              banded_frame('red', hud='white'), banded_frame('blue', hud='white')]
    incident, _ = make_incident(cfg, [], frame_images=frames)
    assert incident.observe() == {'visible': True, 'motion': True}


def test_redaction_preserves_usage_and_paths():
    value = {'tokens_in': 4000, 'driver': 'vulkan', 'path': '/roms/game.iso',
             'authorization': 'private', 'url': '/api/frame?token=private&size=10',
             'log': 'OPENAI_API_KEY=sk-abcdefghijklmnop'}
    encoded = json.dumps(issue.redacted(value))
    assert 'private' not in encoded and 'sk-abcdefghijklmnop' not in encoded
    assert '4000' in encoded and '/roms/game.iso' in encoded


def test_diagnostics_recipe_captures_without_recovery_mutations(cfg):
    incident, calls = make_incident(cfg, ['black'])
    incident.action = 'diagnose'
    incident.run()
    assert not any(tool == 'launch_game' or (tool == 'session_op' and data['op'] == 'resume') for tool, data in calls)
    output = incident.store.get('job', incident.job.id)
    assert output['state'] == 'succeeded' and output['output']['diagnostics_only']
    assert incident.store.get('request', incident.rid)['context']['hermes_job_id']


def test_gpu_recipe_preserves_settings_and_checkpoint_before_applying(cfg):
    incident, calls = make_incident(cfg, ['black', 'red', 'green'])
    incident.action = 'best_graphics'
    incident.run()
    exported = next(i for i, (tool, data) in enumerate(calls) if tool == 'state_transfer' and data['op'] == 'export')
    applied = next(i for i, (tool, data) in enumerate(calls) if tool == 'graphics' and data['op'] == 'best')
    launched = next(i for i, (tool, _) in enumerate(calls) if tool == 'launch_game')
    assert exported < applied < launched
    assert 'Graphics preferences and GPU' in incident.data and 'Applied GPU preset' in incident.data


def test_troubleshooting_catalog_and_action_validation(cfg, monkeypatch):
    class Thread:
        def __init__(self, **kwargs):
            pass
        def start(self):
            pass
    monkeypatch.setattr(issue.threading, 'Thread', Thread)
    app = create_app(cfg)
    setup_session(app.state.store)
    client = TestClient(app, headers={'Authorization': f'Bearer {cfg.token()}'})
    catalog = client.get('/api/sessions/worker-session/troubleshooting').json()
    assert catalog['version'] == 1 and {r['id'] for r in catalog['recipes']} == {'auto', 'resume', 'diagnose', 'restart', 'best_graphics'}
    assert client.post('/api/sessions/worker-session/emulation-issue', json={'action': 'shell_command'}).status_code == 422
    response = client.post('/api/sessions/worker-session/emulation-issue', json={'action': 'diagnose'}).json()
    assert response['request']['context']['troubleshooting_action'] == 'diagnose'
    assert response['request']['context']['recovery_requested'] is False


def test_recovery_does_not_interrupt_newer_game(cfg):
    incident, calls = make_incident(cfg, ['black'] * 5)
    incident.store.put('session', 'worker-another', {'session_id': 'worker-another', 'state': 'running'})
    incident.run()
    assert not any(tool == 'launch_game' for tool, _ in calls)
    assert 'Another game' in incident.store.get('job', incident.job.id)['error']
