import json

from fastapi.testclient import TestClient

from gbox import hermes_task_mode as mode
from gbox.server import create_app


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
        job = mode._job() or {"id": "hermes-job", "name": mode.NAME, "model": "qwen3.6:35b"}
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
    assert calls[0][1] == "every 30m"
    assert calls[0][calls[0].index('--reasoning-effort') + 1] == 'max'
    assert "--skill" not in calls[0]
    assert "--workdir" in calls[0]
    assert client.post("/api/hermes/task-mode", json={"enabled": True}).status_code == 200
    assert [c[0] for c in calls] == ["create", "create"]
    assert calls[1][1] == '1m' and '--repeat' in calls[1]
    assert client.post("/api/hermes/task-mode", json={"enabled": False}).json()["enabled"] is False
    assert calls[-1] == ("pause", "hermes-job")
    assert client.post("/api/hermes/task-mode", json={"enabled": True}).json()["enabled"] is True
    assert [c[0] for c in calls[-3:]] == ["edit", "resume", "create"]
    assert calls[-3][1:3] == ("hermes-job", "--clear-skills")


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


def test_task_mode_reports_effective_cloud_model_and_investigation_uses_max_effort(monkeypatch, tmp_path):
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
    assert calls[0][calls[0].index('--reasoning-effort') + 1] == 'max'
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
