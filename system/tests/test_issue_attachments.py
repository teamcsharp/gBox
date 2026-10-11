import base64

from fastapi.testclient import TestClient

from gbox.server import create_app


def test_issue_captures_running_game_state_by_default(cfg):
    app = create_app(cfg)
    route = next(r for r in app.routes if getattr(r, "path", "") == "/api/requests/issue")
    closure = dict(zip(route.endpoint.__code__.co_freevars, route.endpoint.__closure__))
    closure["_issue_log"].cell_contents = lambda sid, session: ("", "not available in test")
    closure["_issue_chat"].cell_contents = lambda sid: []
    sid = "testworker-123"
    app.state.store.put("session", sid, {"session_id": sid, "game_id": "mgs-vr", "title": "VR Missions",
                                          "state": "running", "adapter": "unsupported-for-transfer"})
    client = TestClient(app, headers={"Authorization": f"Bearer {cfg.token()}"})
    response = client.post("/api/requests/issue", json={"session_id": sid, "what": "Model swap failed",
        "image_b64": base64.b64encode(b"image").decode()})
    assert response.status_code == 200, response.text
    report = response.json()
    job_id = report["context"]["state_job_id"]
    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["tool"] == "session_op"
    assert job["input"]["op"] == "save_state"
    assert job["input"]["args"]["slot"] == report["context"]["state_slot"]
    assert job["parent_request_id"] == report["id"]

    opted_out = client.post("/api/requests/issue", json={"session_id": sid, "what": "Another issue",
        "save_state": False, "image_b64": base64.b64encode(b"image").decode()})
    assert opted_out.status_code == 200, opted_out.text
    assert opted_out.json()["context"]["save_state_requested"] is False
    assert "state_job_id" not in opted_out.json()["context"]


def test_issue_keeps_subject_details_and_arbitrary_attachment_bytes(cfg):
    client = TestClient(create_app(cfg), headers={"Authorization": f"Bearer {cfg.token()}"})
    files = [
        ("steps.md", "text/markdown", "# Reproduction\nMove the stick up.\n".encode()),
        ("capture.png", "image/png", b"\x89PNG\r\n\x1a\n"),
        ("save.bin", "application/octet-stream", bytes([0, 255, 1, 128, 0])),
    ]
    response = client.post("/api/requests/issue", json={
        "title": "Movement is reversed", "what": "Report issue (Capture icon)",
        "note": "Moving up makes the character run down.",
        "attachments": [{"name": name, "type": kind, "b64": base64.b64encode(data).decode()}
                        for name, kind, data in files],
    })
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["title"] == "Movement is reversed"
    assert "Moving up makes the character run down." in report["body"]
    attachments = report["messages"][0]["attachments"]
    assert len(attachments) == len(files)
    for attachment, (name, kind, original) in zip(attachments, files):
        assert (attachment["name"], attachment["type"]) == (name, kind)
        downloaded = client.get(f"/api/artifacts/{attachment['sha256']}")
        assert downloaded.status_code == 200
        assert downloaded.content == original


def test_issue_keeps_game_context_when_launch_never_created_a_session(cfg):
    client = TestClient(create_app(cfg), headers={"Authorization": f"Bearer {cfg.token()}"})
    response = client.post("/api/requests/issue", json={
        "what": "Launch stuck on Preparing", "title": "Issue report: Ocarina of Time",
        "note": "No launch job submitted after 35 seconds",
        "context": {"game_id": "ocarina", "game": "Ocarina of Time",
                    "launch": {"job_id": None, "node": "JAY", "core": "parallel_n64"}},
        "attachments": [{"name": "launch-diagnostics.json", "type": "application/json",
                         "b64": base64.b64encode(b'{"job": null}').decode()}],
    })
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["context"]["game_id"] == "ocarina"
    assert report["context"]["game"] == "Ocarina of Time"
    assert report["context"]["session_id"] == ""
    assert "Ocarina of Time (game_id ocarina" in report["body"]
    assert "No launch job submitted after 35 seconds" in report["body"]
    assert report["messages"][0]["attachments"][0]["name"] == "launch-diagnostics.json"


def test_issue_reuses_in_flight_capture_report(cfg):
    app = create_app(cfg)
    route = next(r for r in app.routes if getattr(r, "path", "") == "/api/requests/issue")
    closure = dict(zip(route.endpoint.__code__.co_freevars, route.endpoint.__closure__))
    closure["_issue_log"].cell_contents = lambda sid, session: ("", "not available in test")
    closure["_issue_chat"].cell_contents = lambda sid: []
    sid = "testworker-123"
    app.state.store.put("session", sid, {"session_id": sid, "game_id": "mgs-vr", "title": "VR Missions",
                                          "state": "running", "adapter": "unsupported-for-transfer"})
    client = TestClient(app, headers={"Authorization": f"Bearer {cfg.token()}"})

    first = client.post("/api/requests/issue", json={"session_id": sid, "what": "Report issue (Capture icon)",
        "image_b64": base64.b64encode(b"image").decode()})
    assert first.status_code == 200, first.text
    report = first.json()
    jid = report["context"]["state_job_id"]

    # A second click while the save-state capture is still queued reuses the same report
    # instead of stacking another report and job (the "failing endlessly" pileup).
    second = client.post("/api/requests/issue", json={"session_id": sid, "what": "Report issue (Capture icon)",
        "image_b64": base64.b64encode(b"image").decode()})
    assert second.status_code == 200, second.text
    assert second.json()["id"] == report["id"]

    # Once the capture job has settled, a fresh report is allowed again.
    job = client.get(f"/api/jobs/{jid}").json()
    app.state.store.put("job", jid, job | {"state": "succeeded"})
    third = client.post("/api/requests/issue", json={"session_id": sid, "what": "Report issue (Capture icon)",
        "image_b64": base64.b64encode(b"image").decode()})
    assert third.status_code == 200, third.text
    assert third.json()["id"] != report["id"]


def test_reused_issue_preserves_new_screenshot_diagnostics_and_context(cfg):
    app = create_app(cfg)
    route = next(r for r in app.routes if getattr(r, "path", "") == "/api/requests/issue")
    closure = dict(zip(route.endpoint.__code__.co_freevars, route.endpoint.__closure__))
    closure["_issue_log"].cell_contents = lambda sid, session: ("", "offline in test")
    closure["_issue_chat"].cell_contents = lambda sid: []
    sid = "testworker-456"
    app.state.store.put("session", sid, {"session_id": sid, "title": "VR Missions",
                                          "state": "running", "adapter": "unsupported-for-transfer"})
    client = TestClient(app, headers={"Authorization": f"Bearer {cfg.token()}"})
    payload = {"session_id": sid, "what": "Report issue (Capture icon)",
               "image_b64": base64.b64encode(b"first image").decode(),
               "attachments": [{"name": "original-diagnostics.json", "type": "application/json",
                                "b64": base64.b64encode(b'{"attempt": 1}').decode()}]}
    first = client.post("/api/requests/issue", json=payload).json()
    second = client.post("/api/requests/issue", json=payload | {
        "image_b64": base64.b64encode(b"latest image").decode(),
        "context": {"renderer": "vulkan", "attempt": 2},
        "attachments": [{"name": "latest-console.txt", "type": "text/plain",
                         "b64": base64.b64encode(b"latest error").decode()}]}).json()
    assert second["id"] == first["id"]
    assert second["context"]["state_job_id"] == first["context"]["state_job_id"]
    assert second["messages"][:-1] == first["messages"]
    original = next(a for a in second["messages"][0]["attachments"] if a["name"] == "original-diagnostics.json")
    assert client.get("/api/artifacts/" + original["sha256"]).json() == {"attempt": 1}
    saves = [j for j in app.state.store.all("job") if j.get("tool") == "session_op"
             and (j.get("input") or {}).get("op") == "save_state"]
    assert len(saves) == 1  # diagnostics appended without a second checkpoint or report
    attachments = {a["name"]: a for a in second["messages"][-1]["attachments"]}
    assert client.get("/api/artifacts/" + attachments["repeat-capture.png"]["sha256"]).content == b"latest image"
    assert client.get("/api/artifacts/" + attachments["latest-console.txt"]["sha256"]).content == b"latest error"
    context = client.get("/api/artifacts/" + attachments["repeat-capture-context.json"]["sha256"]).json()
    assert context["context"] == {"renderer": "vulkan", "attempt": 2}
    assert context["session"]["title"] == "VR Missions"


def test_distinct_issue_is_not_hidden_by_pending_capture(cfg):
    app = create_app(cfg)
    route = next(r for r in app.routes if getattr(r, "path", "") == "/api/requests/issue")
    closure = dict(zip(route.endpoint.__code__.co_freevars, route.endpoint.__closure__))
    closure["_issue_log"].cell_contents = lambda sid, session: ("", "offline in test")
    closure["_issue_chat"].cell_contents = lambda sid: []
    sid = "testworker-789"
    app.state.store.put("session", sid, {"session_id": sid, "title": "VR Missions",
                                          "state": "running", "adapter": "unsupported-for-transfer"})
    client = TestClient(app, headers={"Authorization": f"Bearer {cfg.token()}"})
    payload = {"session_id": sid, "what": "Report issue (Capture icon)",
               "note": "game is frozen", "image_b64": base64.b64encode(b"image").decode()}
    first = client.post("/api/requests/issue", json=payload).json()
    second = client.post("/api/requests/issue", json=payload | {"note": "model swap is wrong"}).json()
    assert second["id"] != first["id"]
    assert "model swap is wrong" in second["body"]
    assert "game is frozen" in first["body"]
    assert second["context"]["state_job_id"] != first["context"]["state_job_id"]


def _real_issue_log(app):
    route = next(r for r in app.routes if getattr(r, "path", "") == "/api/requests/issue")
    closure = dict(zip(route.endpoint.__code__.co_freevars, route.endpoint.__closure__))
    return closure, closure["_issue_log"].cell_contents


def _log_tail_jobs(store, sid):
    return [j for j in store.all("job") if j.get("tool") == "session_op"
            and (j.get("input") or {}).get("op") == "log_tail" and j["input"].get("session_id") == sid]


def test_issue_log_skips_offline_worker_without_queuing_a_failed_job(cfg):
    import time as real_time
    app = create_app(cfg)
    _, issue_log = _real_issue_log(app)
    store = app.state.store
    sid = "offlineworker-1"
    store.put("worker", "offlineworker", {"id": "offlineworker", "name": "i9-NUC", "os": "windows",
                                          "tools": ["session_op"], "last_seen": real_time.time() - 600})
    t0 = real_time.time()
    log, why = issue_log(sid, {})
    assert log == ""
    assert "offline" in why and "i9-NUC" in why and "no log job queued" in why
    assert real_time.time() - t0 < 2                      # no 15 s stall per capture-icon click
    assert _log_tail_jobs(store, sid) == []                # nothing queued, nothing "cancelled by the operator"
    _, why_unknown = issue_log("neverseen-2", {})
    assert "offline" in why_unknown and _log_tail_jobs(store, "neverseen-2") == []


def test_issue_log_timeout_is_not_recorded_as_operator_cancel(cfg, monkeypatch):
    import time as real_time
    import gbox.server as server

    class FakeTime:
        def __init__(self):
            self.now = real_time.time()

        def time(self):
            return self.now

        def sleep(self, d):
            self.now += d

        def __getattr__(self, name):
            return getattr(real_time, name)

    fake = FakeTime()
    app = create_app(cfg)
    _, issue_log = _real_issue_log(app)
    store = app.state.store
    sid = "busyworker-1"
    store.put("worker", "busyworker", {"id": "busyworker", "name": "JAYBUILTFINALE", "os": "windows",
                                       "tools": ["session_op"], "last_seen": fake.now})
    monkeypatch.setattr(server, "time", fake)
    log, why = issue_log(sid, {})
    assert log == "" and "did not answer within 15 s" in why
    jobs = _log_tail_jobs(store, sid)
    assert len(jobs) == 1
    assert jobs[0]["state"] == "failed" and jobs[0]["issue_internal"] is True
    assert not jobs[0].get("cancel")
    assert "cancelled by the operator" not in jobs[0]["error"]
    assert "not an operator cancel" in jobs[0]["error"]


def test_report_lists_manual_log_jobs_but_not_marked_historical_internal_log_fetches(cfg):
    import time as real_time
    app = create_app(cfg)
    closure, _ = _real_issue_log(app)
    closure["_issue_chat"].cell_contents = lambda sid: []
    store = app.state.store
    sid = "offlineworker-9"
    store.put("worker", "offlineworker", {"id": "offlineworker", "name": "i9-NUC", "os": "windows",
                                          "tools": ["session_op"], "last_seen": real_time.time() - 600})
    store.put("session", sid, {"session_id": sid, "title": "Ocarina of Time", "state": "running",
                               "adapter": "unsupported-for-transfer", "started": real_time.time() - 60})
    jobs = [("internal", "log_tail", True, "historical-report-log-cancel"),
            ("manual", "log_tail", False, "operator-requested-debug-log-failed"),
            ("resume", "resume", False, None)]
    for i, (jid, op, internal, error) in enumerate(jobs):
        store.put("job", jid, {"id": jid, "tool": "session_op", "state": "failed" if error else "queued",
                               "input": {"session_id": sid, "op": op, "args": {}},
                               "issue_internal": internal, "created": real_time.time() - 30 + i,
                               "error": error})
    client = TestClient(app, headers={"Authorization": f"Bearer {cfg.token()}"})
    report = client.post("/api/requests/issue", json={"session_id": sid, "what": "Report issue (Capture icon)",
                                                      "image_b64": base64.b64encode(b"image").decode()}).json()
    body = report["body"]
    recent = body.split("## Recent gBox jobs for this game", 1)[1].split("## ", 1)[0]
    assert '"op": "resume"' in recent
    assert recent.count('"op": "log_tail"') == 1
    assert "operator-requested-debug-log-failed" in recent
    assert "historical-report-log-cancel" not in recent
    assert "log_tail skipped: worker i9-NUC is offline" in body
    assert {j["id"] for j in _log_tail_jobs(store, sid)} == {"internal", "manual"}


class _Clock:
    """Advance only the server's clock while delivering a worker response deterministically."""
    def __init__(self, on_sleep=None):
        import time
        self.real_time = time
        self.now = time.time()
        self.on_sleep = on_sleep

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds
        if self.on_sleep:
            self.on_sleep()

    def __getattr__(self, name):
        return getattr(self.real_time, name)


def test_running_issue_log_timeout_leaves_the_read_uncancelled_and_accepts_its_late_result(cfg, monkeypatch):
    import gbox.server as server
    app = create_app(cfg)
    _, issue_log = _real_issue_log(app)
    store = app.state.store
    clock = _Clock()
    sid = "busyworker-1"
    store.put("worker", "busyworker", {"id": "busyworker", "name": "JAYBUILTFINALE", "os": "windows",
                                       "tools": ["session_op"], "last_seen": clock.now})
    client = TestClient(app, headers={"Authorization": f"Bearer {cfg.token()}"})
    claimed = []
    def claim_once():
        if not claimed:
            response = client.post("/api/workers/busyworker/claim")
            assert response.status_code == 200, response.text
            claimed.append(response.json())
    clock.on_sleep = claim_once
    monkeypatch.setattr(server, "time", clock)

    log, why = issue_log(sid, {})
    assert log == "" and "did not answer within 15 s" in why
    assert len(claimed) == 1 and claimed[0]["issue_internal"] is True
    jid = claimed[0]["id"]
    job = store.get("job", jid)
    assert job["state"] == "running" and job["issue_log_wait_expired"] is True
    assert not job.get("cancel") and not job.get("error") and not job.get("finished")

    # The ordinary result endpoint must still accept the running job after capture stopped waiting.
    response = client.post("/api/workers/busyworker/result", json={"job_id": jid, "ok": True,
        "output": {"result": {"log": "late emulator diagnostic", "path": "emulator.log"}, "session_id": sid}})
    assert response.status_code == 200, response.text
    assert response.json()["state"] == "succeeded"
    finished = store.get("job", jid)
    assert finished["issue_internal"] is True and not finished.get("cancel")
    assert finished["output"]["result"]["log"] == "late emulator diagnostic"


def test_live_issue_log_result_is_attached_and_marked_internal_without_changing_its_success(cfg, monkeypatch):
    import gbox.server as server
    app = create_app(cfg)
    store = app.state.store
    clock = _Clock()
    sid = "liveworker-1"
    store.put("worker", "liveworker", {"id": "liveworker", "name": "JAYBUILTFINALE", "os": "windows",
                                       "tools": ["session_op"], "last_seen": clock.now})
    store.put("session", sid, {"session_id": sid, "title": "VR Missions", "state": "running"})
    client = TestClient(app, headers={"Authorization": f"Bearer {cfg.token()}"})
    completed = []
    log = "Renderer initialized\nCurrent game diagnostics"
    def finish_once():
        if completed:
            return
        claimed = client.post("/api/workers/liveworker/claim")
        assert claimed.status_code == 200, claimed.text
        jid = claimed.json()["id"]
        response = client.post("/api/workers/liveworker/result", json={"job_id": jid, "ok": True,
            "output": {"result": {"log": log, "path": "emulator.log"}, "session_id": sid}})
        assert response.status_code == 200, response.text
        completed.append(jid)
    clock.on_sleep = finish_once
    monkeypatch.setattr(server, "time", clock)
    response = client.post("/api/requests/issue", json={"session_id": sid, "what": "Renderer issue",
        "save_state": False, "image_b64": base64.b64encode(b"capture").decode()})
    assert response.status_code == 200, response.text
    report = response.json()
    attachment = next(a for a in report["messages"][0]["attachments"] if a["name"] == "emulator-log.txt")
    assert client.get("/api/artifacts/" + attachment["sha256"]).text == log
    assert log in report["body"] and "emulator.log" in report["body"]
    job = store.get("job", completed[0])
    assert job["state"] == "succeeded" and job["issue_internal"] is True
    assert not job.get("issue_log_wait_expired") and not job.get("cancel")
    assert len(_log_tail_jobs(store, sid)) == 1


def test_internal_job_flood_cannot_displace_operator_diagnostics_from_the_recent_twenty(cfg):
    import time
    app = create_app(cfg)
    closure, _ = _real_issue_log(app)
    closure["_issue_chat"].cell_contents = lambda sid: []
    store = app.state.store
    sid = "offlineworker-flood"
    now = time.time()
    store.put("worker", "offlineworker", {"id": "offlineworker", "name": "i9-NUC", "os": "windows",
                                          "tools": ["session_op"], "last_seen": now - 600})
    store.put("session", sid, {"session_id": sid, "title": "VR Missions", "state": "running", "started": now - 120})
    store.put("job", "manual-log", {"id": "manual-log", "tool": "session_op", "state": "succeeded",
        "input": {"session_id": sid, "op": "log_tail"}, "created": now - 60,
        "output": {"result": {"log": "operator-requested diagnostic retained"}}})
    for i in range(25):
        store.put("job", f"internal-{i}", {"id": f"internal-{i}", "tool": "session_op", "state": "failed",
            "input": {"session_id": sid, "op": "log_tail"}, "created": now - 30 + i, "issue_internal": True,
            "error": "internal-report diagnostic timeout"})
    client = TestClient(app, headers={"Authorization": f"Bearer {cfg.token()}"})
    response = client.post("/api/requests/issue", json={"session_id": sid, "what": "Renderer issue",
        "save_state": False, "image_b64": base64.b64encode(b"capture").decode()})
    assert response.status_code == 200, response.text
    body = response.json()["body"]
    assert "operator-requested diagnostic retained" in body
    assert "internal-report diagnostic timeout" not in body
