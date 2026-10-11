import base64
import time
from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image

from gbox.agent import ChatHub
from gbox.server import create_app


def test_auto_mod_failure_files_evidence_dispatches_and_deduplicates(cfg, monkeypatch):
    dispatched = []
    monkeypatch.setattr(ChatHub, "post", lambda self, cid, text, context, *args: dispatched.append((cid, text, context)))
    app = create_app(cfg)
    client = TestClient(app, headers={"Authorization": f"Bearer {cfg.token()}"})
    image = b"\x89PNG\r\n\x1a\nfixture"
    body = {"game": "Metal Gear Solid", "model": "Cyborg Ninja", "action": "pick whip model replacement",
            "target": "Snake", "moment": "48% across, 52% down", "detail": "writer unsupported",
            "job_id": "failed-job", "image_b64": base64.b64encode(image).decode()}
    first = client.post("/api/requests/auto-mod-failure", json=body)
    assert first.status_code == 200, first.text
    report = first.json()
    assert report["status"] == "in_progress" and report["automated"]
    assert report["source"] == "automation" and report["context"]["auto_report"]
    listed = next(x for x in client.get("/api/requests").json() if x["id"] == report["id"])
    assert listed["parent_request_id"] is None
    assert "Cyborg Ninja" in report["body"] and "48% across" in report["body"]
    assert client.get(f"/api/artifacts/{report['image']}").content == image
    assert len(dispatched) == 1 and dispatched[0][2]["request_id"] == report["id"]
    cid = report["context"]["resolution_chat_id"]
    app.state.store.put("chat", cid, {"id": cid, "busy": True, "events": [
        {"type": "tool_call", "name": "characters", "args": {"op": "use", "character": "Ninja"}},
        {"type": "tool_result", "name": "characters", "text": '{"status": "unsupported_live_swap", "message": "writer unsupported"}'}]})
    rows = client.get("/api/tasks").json()["resolutions"]
    assert rows[0]["id"] == report["id"] and rows[0]["state"] == "running"
    detail = client.get(f"/api/tasks/resolutions/{report['id']}").json()
    assert detail["steps"][0]["action"] == "characters"
    assert "writer unsupported" in detail["steps"][0]["result"]
    assert detail["steps"][0]["status"] == "failed"
    second = client.post("/api/requests/auto-mod-failure", json=body)
    assert second.status_code == 200 and second.json()["id"] == report["id"]
    assert len(dispatched) == 1
    response = client.post(f"/api/requests/{report['id']}/messages", json={"author": "agent", "text": "Retried",
        "task_step": {"action": "rebuild writer", "attempt": "2", "result": "model loaded", "status": "finished"}})
    assert response.status_code == 200
    assert response.json()["messages"][-1]["task_step"]["attempt"] == "2"


def test_auto_mod_failure_offers_saved_state_job_for_live_game(cfg, monkeypatch):
    monkeypatch.setattr(ChatHub, "post", lambda *args: None)
    app = create_app(cfg)
    app.state.store.put("session", "worker-session", {"session_id": "worker-session", "state": "running",
                                                       "title": "Metal Gear Solid", "game_id": "mgs"})
    client = TestClient(app, headers={"Authorization": f"Bearer {cfg.token()}"})
    client.post("/api/requests", json={"title": "Try model swap", "context": {"session": "worker-session"}})
    image = base64.b64encode(b"\x89PNG\r\n\x1a\nfixture").decode()
    response = client.post("/api/requests/auto-mod-failure", json={"session_id": "worker-session",
        "model": "Ninja", "detail": "unsupported writer", "image_b64": image})
    assert response.status_code == 200, response.text
    report = response.json()
    assert next(x for x in client.get("/api/requests").json() if x["id"] == report["id"])["parent_request_id"] is None
    state_job = client.get(f"/api/jobs/{report['context']['state_job_id']}").json()
    assert state_job["tool"] == "session_op"
    assert state_job["input"]["op"] == "save_state"
    assert state_job["input"]["args"]["slot"] == 40
    assert state_job["parent_request_id"] == report["id"]


def test_auto_failure_keeps_game_frame_even_with_desktop_screenshot(cfg, monkeypatch):
    monkeypatch.setattr(ChatHub, "post", lambda *args: None)
    app = create_app(cfg)
    store = app.state.store
    store.put("session", "worker-session", {"session_id": "worker-session", "state": "running",
        "title": "Metal Gear Solid", "game_id": "mgs", "adapter": "unsupported"})
    client = TestClient(app, headers={"Authorization": f"Bearer {cfg.token()}"})
    desktop = base64.b64encode(b"\x89PNG\r\n\x1a\ndesktop").decode()
    report = client.post("/api/requests/auto-mod-failure", json={"session_id": "worker-session",
        "model": "Ninja", "image_b64": desktop}).json()
    jid = report["context"]["state_job_id"]
    frame = b"\x89PNG\r\n\x1a\ngame-frame"
    ref = store.put_artifact(frame, "state.png", "image/png", {"job": jid})
    job = store.get("job", jid)
    store.put("job", jid, job | {"state": "succeeded", "started": time.time(), "output": {"result": {"slot": 40}}})
    for _ in range(60):
        latest = store.get("request", report["id"])
        if any(m.get("attachments") and m["attachments"][0]["sha256"] == ref.sha256
               for m in latest["messages"]):
            break
        time.sleep(.05)
    else:
        raise AssertionError("game frame was not attached to auto report")
    assert latest["image"]  # original desktop screenshot is kept too


def test_capture_request_screenshot_attaches_live_frame_with_step(cfg):
    app = create_app(cfg)
    app.state.store.put("session", "worker-session", {"session_id": "worker-session", "state": "running"})
    client = TestClient(app, headers={"Authorization": f"Bearer {cfg.token()}"})
    report = client.post("/api/requests", json={"title": "Swap attempt"}).json()
    frame = BytesIO()
    Image.new('RGB', (8, 6), 'orange').save(frame, format='PNG')
    png = frame.getvalue()
    assert client.post("/api/sessions/worker-session/frame", content=png).status_code == 200
    response = client.post(f"/api/requests/{report['id']}/capture", json={"session_id": "worker-session",
        "text": "Ninja is visible", "task_step": {"action": "verify model", "attempt": "2",
                                                    "result": "visible", "status": "finished"}})
    assert response.status_code == 200, response.text
    entry = response.json()
    assert entry["task_step"]["attempt"] == "2"
    assert client.get(f"/api/artifacts/{entry['attachments'][0]['sha256']}").content == png


def test_completed_request_can_be_disputed_with_evidence_and_new_resolution(cfg, monkeypatch):
    dispatched = []
    monkeypatch.setattr(ChatHub, "post", lambda self, cid, text, context, *args: dispatched.append((cid, text, context)))
    app = create_app(cfg)
    app.state.store.put("session", "worker-session", {"session_id": "worker-session", "state": "running",
                                                       "title": "Metal Gear Solid - VR Missions"})
    client = TestClient(app, headers={"Authorization": f"Bearer {cfg.token()}"})
    report = client.post("/api/requests", json={"title": "VR Missions model swap", "body": "Replace Snake with HUcast"}).json()
    rid = report["id"]
    assert client.post(f"/api/requests/{rid}/status", json={"status": "done", "note": "Previously claimed complete"}).status_code == 200
    png = b"\x89PNG\r\n\x1a\nfailed-frame"
    complaint = {"explanation": "The game glitches and HUcast is not visible", "session_id": "worker-session", "attachments": [{
        "name": "glitch.png", "type": "image/png", "b64": base64.b64encode(png).decode()}]}
    reopened = client.post(f"/api/requests/{rid}/report-incomplete", json=complaint)
    assert reopened.status_code == 200, reopened.text
    item = reopened.json()
    assert item["status"] == "in_progress" and item["completed"] is None
    assert item["context"]["disputed_completions"][0]["completed"] is not None
    assert item["context"]["resolution_chat_id"] == dispatched[0][0]
    assert client.get(f"/api/jobs/{item['context']['state_job_id']}").json()["input"]["op"] == "save_state"
    assert dispatched[0][2]["request_id"] == rid and dispatched[0][2]["resolve_auto_report"]
    evidence = next(m for m in item["messages"] if m["author"] == "operator" and "Completion disputed" in m["text"])
    assert client.get(f"/api/artifacts/{evidence['attachments'][0]['sha256']}").content == png
    assert client.post(f"/api/requests/{rid}/report-incomplete", json=complaint).status_code == 409
    assert client.post(f"/api/requests/{rid}/report-incomplete", json={"explanation": " "}).status_code == 422
