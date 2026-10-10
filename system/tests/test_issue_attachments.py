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
