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
    assert "--skill" not in calls[0]
    assert "--workdir" in calls[0]
    assert client.post("/api/hermes/task-mode", json={"enabled": True}).status_code == 200
    assert [c[0] for c in calls] == ["create", "run"]
    assert client.post("/api/hermes/task-mode", json={"enabled": False}).json()["enabled"] is False
    assert calls[-1] == ("pause", "hermes-job")
    assert client.post("/api/hermes/task-mode", json={"enabled": True}).json()["enabled"] is True
    assert [c[0] for c in calls[-3:]] == ["edit", "resume", "run"]
    assert calls[-3][1:3] == ("hermes-job", "--clear-skills")


def test_task_mode_prefers_responsive_google_model_when_memory_allows(monkeypatch):
    class Response:
        def json(self):
            return {"models": [{"name": "gemma4:e4b-it-qat"}, {"name": "gemma4:12b-it-qat"}, {"name": "gemma4:12b"}, {"name": "gemma4:31b"}, {"name": "qwen3.6:35b"},
                               {"name": "qwen3.8:27b-mtp-q4_K_M"}]}

    monkeypatch.setattr(mode.httpx, "get", lambda *a, **kw: Response())
    monkeypatch.setattr(mode.psutil, "virtual_memory", lambda: type("Memory", (), {"available": 78 * 1024**3})())
    assert mode._model()[0] == "gemma4:12b-it-qat"
    monkeypatch.setattr(mode.psutil, "virtual_memory", lambda: type("Memory", (), {"available": 36 * 1024**3})())
    assert mode._model()[0] == "gemma4:12b-it-qat"
    monkeypatch.setattr(mode.psutil, "virtual_memory", lambda: type("Memory", (), {"available": 20 * 1024**3})())
    assert mode._model()[0] == "gemma4:12b-it-qat"
    monkeypatch.setattr(mode.psutil, "virtual_memory", lambda: type("Memory", (), {"available": 10 * 1024**3})())
    assert mode._model()[0] is None
