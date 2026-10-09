import time
from types import SimpleNamespace

from fastapi.testclient import TestClient

from gbox.server import create_app
from gbox import tasks_tool


def test_tasks_snapshot_queues_one_inventory_and_returns_cached_result(cfg):
    app = create_app(cfg)
    client = TestClient(app, headers={"authorization": f"Bearer {cfg.token()}"})
    store = app.state.store
    store.put("worker", "worker-1", {"id": "worker-1", "name": "fixture", "os": "linux", "tools": ["tasks"],
                                     "unavailable": {}, "last_seen": time.time()})

    started = time.monotonic()
    first = client.get("/api/tasks").json()
    assert time.monotonic() - started < 2
    assert first["machines"][0]["collecting"] is True
    jobs = [j for j in store.all("job") if j["tool"] == "tasks"]
    assert len(jobs) == 1
    client.get("/api/tasks")
    assert len([j for j in store.all("job") if j["tool"] == "tasks"]) == 1

    job = jobs[0] | {"state": "succeeded", "finished": time.time(),
                     "output": {"result": {"totals": {"cpu_pct": 7}, "tasks": [{"pid": 123, "name": "game"}]}}}
    store.put("job", job["id"], job)
    cached = client.get("/api/tasks").json()["machines"][0]
    assert cached["tasks"][0]["pid"] == 123
    assert cached["totals"]["cpu_pct"] == 7
    assert cached["collecting"] is False
    assert len([j for j in store.all("job") if j["tool"] == "tasks"]) == 1


def test_job_console_log_is_available_for_task_details(cfg):
    app = create_app(cfg)
    client = TestClient(app, headers={"authorization": f"Bearer {cfg.token()}"})
    store = app.state.store
    ref = store.put_artifact(b"started\nfinished", "worker.log", "text/plain", {"job": "job-1"})
    store.put("job", "job-1", {"id": "job-1", "tool": "scan_library", "state": "succeeded",
                                "created": time.time(), "log_sha": ref.sha256})
    assert client.get("/api/jobs/job-1/log").json() == {"log": "started\nfinished"}
    assert client.get("/api/jobs/missing/log").status_code == 404


def test_worker_subprocess_is_listed_even_without_gbox_in_command(monkeypatch):
    import re
    import psutil

    class Child:
        pid = 424242
        info = {"pid": pid, "ppid": 1, "name": "ffmpeg", "cmdline": ["ffmpeg", "-i", "video"], "create_time": 1}
        def cpu_percent(self, interval=None): return 0
        def ppid(self): return 1
        def children(self, recursive=False): return []
        def cmdline(self): return self.info["cmdline"]
        def memory_info(self): return SimpleNamespace(rss=1024)
        def is_running(self): return True
        def name(self): return "ffmpeg"
        def create_time(self): return 1

    child = Child()
    monkeypatch.setattr(tasks_tool, "GBOX", re.compile("^$"))
    monkeypatch.setattr(tasks_tool, "_gpu_windows", lambda: {})
    monkeypatch.setattr(tasks_tool, "_gpu_linux", lambda: {})
    monkeypatch.setattr(tasks_tool, "_gpu_totals", lambda: {})
    monkeypatch.setattr(psutil, "Process", lambda: SimpleNamespace(children=lambda recursive: [child]))
    monkeypatch.setattr(psutil, "process_iter", lambda attrs: [child])
    monkeypatch.setattr(psutil, "virtual_memory", lambda: SimpleNamespace(total=2**30, available=2**29))
    monkeypatch.setattr(psutil, "cpu_percent", lambda interval: 0)
    tasks = tasks_tool.list_tasks()["tasks"]
    assert len(tasks) == 1 and tasks[0]["pid"] == child.pid
