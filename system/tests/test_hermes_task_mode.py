import json
import sqlite3
import datetime as dt
import pytest

from fastapi.testclient import TestClient

from gbox import hermes_task_mode as mode
from gbox.server import create_app


@pytest.fixture(autouse=True)
def isolate_delivery_repository(monkeypatch, tmp_path):
    monkeypatch.setenv('GBOX_HERMES_REPO', str(tmp_path / 'unprovisioned-repo'))
    monkeypatch.setenv('GBOX_HERMES_DISPATCH_STATE', str(tmp_path / 'dispatch-state'))


def test_task_mode_toggle_controls_one_hermes_job(cfg, monkeypatch, tmp_path):
    home = tmp_path / ".hermes"
    (home / "cron").mkdir(parents=True)
    cli = tmp_path / "hermes"
    cli.write_text("#!/bin/sh\n")
    monkeypatch.setattr(mode, "_home", lambda: home)
    monkeypatch.setattr(mode, "_cli", lambda: cli)
    monkeypatch.setattr(mode, "_model", lambda: ("qwen3.6:35b", "installed and fits"))
    calls = []

    def fake_run(*args):
        calls.append(args)
        job = mode._job() or {"id": "hermes-job", "name": mode.NAME, "model": "qwen3.6:35b", "no_agent": True}
        job["enabled"] = args[0] != "pause"
        (home / "cron" / "jobs.json").write_text(json.dumps({"jobs": [job]}))

    monkeypatch.setattr(mode, "_run", fake_run)
    client = TestClient(create_app(cfg), headers={"Authorization": f"Bearer {cfg.token()}"})
    assert client.get("/api/hermes/task-mode").json()["enabled"] is False
    enabled = client.post("/api/hermes/task-mode", json={"enabled": True})
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()["enabled"] is True
    assert enabled.json()["model"] == "qwen3.6:35b"
    assert calls[0][0] == "create"
    assert calls[0][1] == "every 1m"
    assert '--no-agent' in calls[0] and '--script' in calls[0]
    assert calls[0][calls[0].index('--script') + 1] == 'gbox-work-queue.py'
    assert calls[0][calls[0].index('--reasoning-effort') + 1] == 'high'
    assert "--skill" not in calls[0]
    assert "--workdir" in calls[0]
    assert client.post("/api/hermes/task-mode", json={"enabled": True}).status_code == 200
    assert [c[0] for c in calls] == ["create"]
    assert client.post("/api/hermes/task-mode", json={"enabled": False}).json()["enabled"] is False
    assert calls[-1] == ("pause", "hermes-job")
    assert client.post("/api/hermes/task-mode", json={"enabled": True}).json()["enabled"] is True
    assert calls[-1] == ('resume', 'hermes-job')


def test_task_mode_follows_connected_provider_and_releases_its_legacy_local_pin(monkeypatch, tmp_path):
    assert mode._model()[0] is None
    home = tmp_path / ".hermes"
    (home / "cron").mkdir(parents=True)
    cli = tmp_path / "hermes"
    cli.write_text("#!/bin/sh\n")
    job = {"id": "job-1", "name": mode.NAME, "enabled": True,
           "model": "gemma4:e4b-it-qat", "provider": "custom"}
    path = home / "cron" / "jobs.json"
    path.write_text(json.dumps({"jobs": [job]}))
    monkeypatch.setattr(mode, "_home", lambda: home)
    monkeypatch.setattr(mode, "_cli", lambda: cli)
    calls = []

    def fake_run(*args):
        calls.append(args)
        if args[0] == "edit" and args[-1] == "--unpin":
            job.update(model=None, provider=None)
            path.write_text(json.dumps({"jobs": [job]}))

    monkeypatch.setattr(mode, "_run", fake_run)
    assert mode.set_enabled(True)["model"] is None
    assert calls == [("edit", "job-1", "--unpin")]


def test_task_mode_surfaces_agent_reported_cron_failure(monkeypatch, tmp_path):
    home = tmp_path / ".hermes"
    output = home / "cron" / "output" / "job-1"
    output.mkdir(parents=True)
    (home / "cron" / "jobs.json").write_text(json.dumps({"jobs": [{"id": "job-1", "name": mode.NAME,
        "enabled": True, "last_status": "ok"}]}))
    (output / "run.md").write_text("# Cron Job\n## Response\n[CRON_FAILURE] No source patch was made.\n")
    monkeypatch.setattr(mode, "_home", lambda: home)
    monkeypatch.setattr(mode, "_cli", lambda: tmp_path / "hermes")
    state = mode.status()
    assert state["last_status"] == "failed"
    assert "No source patch" in state["last_error"]


def test_task_mode_does_not_call_a_plain_cron_exit_success(monkeypatch, tmp_path):
    home = tmp_path / ".hermes"
    output = home / "cron" / "output" / "job-1"
    output.mkdir(parents=True)
    (home / "cron" / "jobs.json").write_text(json.dumps({"jobs": [{"id": "job-1", "name": mode.NAME,
        "enabled": True, "last_status": "ok"}]}))
    (output / "run.md").write_text("# Cron Job\n## Response\nI plan to patch this later.\n")
    monkeypatch.setattr(mode, "_home", lambda: home)
    monkeypatch.setattr(mode, "_cli", lambda: tmp_path / "hermes")
    state = mode.status()
    assert state["last_status"] == "unverified"
    assert "independently verified" in state["last_error"]


def test_investigation_limits_reasoning_without_changing_interactive_effort(monkeypatch, tmp_path):
    home = tmp_path / '.hermes'
    (home / 'cron').mkdir(parents=True)
    (home / 'config.yaml').write_text('model:\n  provider: nous\n  default: anthropic/claude-opus-5.5\n'
                                    'agent:\n  reasoning_effort: max\n  max_turns: 150\n')
    (home / 'cron/jobs.json').write_text(json.dumps({'jobs': []}))
    monkeypatch.setattr(mode, '_home', lambda: home)
    calls = []
    def fake_run(*args):
        calls.append(args)
        (home / 'cron/jobs.json').write_text(json.dumps({'jobs': [
            {'id': 'incident-job', 'name': 'gBox emulation investigation #1051'}]}))
    monkeypatch.setattr(mode, '_run', fake_run)
    state = mode.status()
    assert state['model'] == 'anthropic/claude-opus-5.5' and state['reasoning_effort'] == 'max'
    assert state['max_turns'] == 150
    assert mode.dispatch_request('request-id', 1051) == 'incident-job'
    assert calls[0][calls[0].index('--reasoning-effort') + 1] == 'high'
    assert 'request-id' in calls[0][2] and '--repeat' in calls[0]
    assert mode.dispatch_request('request-id', 1051) == 'incident-job'
    assert len(calls) == 1


def test_incident_inherits_inbox_cloud_pin_instead_of_interactive_local_model(monkeypatch, tmp_path):
    home = tmp_path / '.hermes'
    (home / 'cron').mkdir(parents=True)
    inbox = {'id': 'inbox', 'name': mode.NAME, 'model': 'anthropic/claude-opus-5.5', 'provider': 'nous'}
    path = home / 'cron/jobs.json'
    path.write_text(json.dumps({'jobs': [inbox]}))
    monkeypatch.setattr(mode, '_home', lambda: home)
    calls = []
    def fake_run(*args):
        calls.append(args)
        path.write_text(json.dumps({'jobs': [inbox, {'id': 'incident', 'name': 'gBox emulation investigation #7'}]}))
    monkeypatch.setattr(mode, '_run', fake_run)
    assert mode.dispatch_request('request', 7) == 'incident'
    assert calls[0][calls[0].index('--provider') + 1] == 'nous'
    assert calls[0][calls[0].index('--model') + 1] == 'anthropic/claude-opus-5.5'
    assert not any(c[0] == 'run' for c in calls)


def test_cloud_cron_defaults_allow_fallbacks_without_copying_the_inbox_pin(monkeypatch, tmp_path):
    home = tmp_path / '.hermes'
    (home / 'cron').mkdir(parents=True)
    (home / 'config.yaml').write_text('model:\n  provider: local\n  default: local-model\n'
        'cron:\n  model_provider: cloud\n  model: cloud-model\n  max_parallel_jobs: 2\n'
        'fallback_providers:\n  - provider: backup\n    model: backup-model\n')
    inbox = {'id': 'inbox', 'name': mode.NAME, 'enabled': True}
    path = home / 'cron/jobs.json'
    path.write_text(json.dumps({'jobs': [inbox]}))
    monkeypatch.setattr(mode, '_home', lambda: home)
    calls = []
    def fake_run(*args):
        calls.append(args)
        path.write_text(json.dumps({'jobs': [inbox,
            {'id': 'incident', 'name': 'gBox emulation investigation #7', 'enabled': True}]}))
    monkeypatch.setattr(mode, '_run', fake_run)
    state = mode.status()
    assert (state['provider'], state['model']) == ('cloud', 'cloud-model')
    assert state['fallback_enabled'] and state['max_parallel_jobs'] == 2
    assert mode.dispatch_request('request', 7) == 'incident'
    assert '--model' not in calls[0] and '--provider' not in calls[0]


def test_failed_one_shot_is_rearmed_once_but_a_disabled_live_run_is_preserved(monkeypatch, tmp_path):
    home = tmp_path / '.hermes'
    (home / 'cron').mkdir(parents=True)
    (home / 'config.yaml').write_text('cron:\n  model_provider: cloud\n  model: cloud-model\n')
    job = {'id': 'incident', 'name': 'gBox emulation investigation #7', 'enabled': False,
           'last_status': 'error', 'schedule': {'kind': 'once'}}
    path = home / 'cron/jobs.json'
    path.write_text(json.dumps({'jobs': [job]}))
    dbpath = home / 'cron/executions.db'
    with sqlite3.connect(dbpath) as db:
        db.execute('CREATE TABLE executions (job_id TEXT, status TEXT)')
        db.execute('INSERT INTO executions VALUES (?,?)', ('incident', 'running'))
    monkeypatch.setattr(mode, '_home', lambda: home)
    calls = []
    def fake_run(*args):
        calls.append(args)
        if args[0] == 'resume':
            job['enabled'] = True
            path.write_text(json.dumps({'jobs': [job]}))
    monkeypatch.setattr(mode, '_run', fake_run)
    assert mode.dispatch_request('request', 7) == 'incident'
    assert calls == []
    with sqlite3.connect(dbpath) as db:
        # Hermes marks a dead owner as unknown when prior side effects cannot be
        # established. It is terminal history, not a live execution to preserve.
        db.execute("UPDATE executions SET status='unknown'")
    assert mode.dispatch_request('request', 7) == 'incident'
    assert calls[0][:2] == ('edit', 'incident') and '--unpin' in calls[0] and '--continuity' in calls[0]
    assert calls[1] == ('resume', 'incident', '--run-now')
    assert mode.dispatch_request('request', 7) == 'incident'
    assert len(calls) == 2


def test_exhausted_legacy_interval_gets_one_trackable_replacement(monkeypatch, tmp_path):
    home = tmp_path / '.hermes'
    (home / 'cron').mkdir(parents=True)
    jobs = [{'id': 'old', 'name': 'gBox emulation investigation #7', 'enabled': False,
             'last_status': 'error', 'schedule': {'kind': 'interval'}, 'repeat': {'times': 1, 'completed': 1}}]
    path = home / 'cron/jobs.json'
    path.write_text(json.dumps({'jobs': jobs}))
    monkeypatch.setattr(mode, '_home', lambda: home)
    calls = []
    def fake_run(*args):
        calls.append(args)
        assert args[0] == 'create'
        assert dt.datetime.fromisoformat(args[1]) > dt.datetime.now(dt.timezone.utc)
        jobs.append({'id': 'retry', 'name': args[args.index('--name') + 1], 'enabled': True,
                     'schedule': {'kind': 'once'}})
        path.write_text(json.dumps({'jobs': jobs}))
    monkeypatch.setattr(mode, '_run', fake_run)
    assert mode.dispatch_request('request', 7) == 'retry'
    assert 'resumes failed Hermes job old' in calls[0][2]
    assert jobs[0]['last_status'] == 'error'
    assert mode.dispatch_request('request', 7) == 'retry'
    assert len(calls) == 1


def test_activation_does_not_duplicate_pending_or_running_work(monkeypatch, tmp_path):
    home = tmp_path / '.hermes'
    (home / 'cron').mkdir(parents=True)
    path = home / 'cron/jobs.json'
    activation = {'id': 'activation', 'name': mode.NAME + ' activation 1', 'enabled': True}
    path.write_text(json.dumps({'jobs': [activation]}))
    monkeypatch.setattr(mode, '_home', lambda: home)
    calls = []
    monkeypatch.setattr(mode, '_run', lambda *args: calls.append(args))
    mode._kickoff({'id': 'inbox'})
    assert calls == []
    activation['enabled'] = False
    path.write_text(json.dumps({'jobs': [activation]}))
    with sqlite3.connect(home / 'cron/executions.db') as db:
        db.execute('CREATE TABLE executions (job_id TEXT, status TEXT)')
        db.execute('INSERT INTO executions VALUES (?,?)', ('activation', 'running'))
    mode._kickoff({'id': 'inbox'})
    assert calls == []
