"""The report must export its completed checkpoint once, using native slot evidence."""
import base64
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from gbox.agent import ChatHub
from gbox.server import _checkpoint_slot, create_app


@pytest.mark.parametrize("route", ["/api/requests/issue", "/api/requests/auto-mod-failure"])
@pytest.mark.parametrize("actual", [0, 89, -1])
def test_report_exports_existing_actual_slot_and_keeps_requested_slot(cfg, monkeypatch, route, actual):
    import gbox.server as server
    monkeypatch.setattr(ChatHub, "post", lambda *args: None)
    app = create_app(cfg)
    store = app.state.store
    sid = "testworker-native"
    store.put("session", sid, {"session_id": sid, "state": "running", "adapter": "retroarch",
                                "game_id": "owned", "title": "Owned game"})
    endpoint = next(r.endpoint for r in app.routes if getattr(r, "path", None) == "/api/requests/issue")
    closure = dict(zip(endpoint.__code__.co_freevars, endpoint.__closure__))
    closure["_issue_log"].cell_contents = lambda *args: ("", "offline test")
    closure["_issue_chat"].cell_contents = lambda *args: []
    original_submit = closure["submit"].cell_contents
    submitted = []
    captured = b"the native checkpoint bytes"
    filename = "owned.state" + (str(actual) if actual else "")

    def complete(job_request, actor):
        submitted.append(job_request)
        job = original_submit(job_request, actor)
        output = {"slot": actual, "verified": True, "path": filename}
        if job_request.tool == "session_op":
            frame = store.put_artifact(b"captured game frame", "saved.png", "image/png", {"job": job.id})
            output["frame"] = frame.sha256
        elif job_request.tool == "state_transfer":
            artifact = store.put_artifact(captured, filename, "application/octet-stream", {"job": job.id})
            output.update(artifact=artifact.sha256, file=filename, bytes=len(captured))
        else:
            pytest.fail(f"unexpected job: {job_request.tool}")
        stored = store.get("job", job.id)
        store.put("job", job.id, stored | {"state": "succeeded", "started": 1_700_000_001,
                                          "output": {"result": output}})
        return job

    closure["submit"].cell_contents = complete

    class InlineThread:
        def __init__(self, *, target, name, **kwargs):
            assert name.startswith(("issue-state-", "auto-failure-"))
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(server, "threading", SimpleNamespace(Thread=InlineThread))
    client = TestClient(app, headers={"Authorization": f"Bearer {cfg.token()}"})
    payload = {"session_id": sid, "what": "Capture this moment"} if route.endswith("/issue") else {
        "session_id": sid, "model": "Amy", "detail": "writer failed"}
    payload["image_b64"] = base64.b64encode(b"desktop frame").decode()
    response = client.post(route, json=payload)
    assert response.status_code == 200, response.text
    report = store.get("request", response.json()["id"])
    save, export = submitted
    assert save.tool == "session_op" and save.input["op"] == "save_state"
    assert export.tool == "state_transfer"
    assert export.input == {"session_id": sid, "op": "export_saved", "slot": actual,
                            "not_before": 1_700_000_001}
    assert export.parent_request_id == save.parent_request_id == report["id"]
    assert report["context"]["state_slot"] == actual
    assert report["context"]["state_requested_slot"] == save.input["args"]["slot"]
    if route.endswith("/auto-mod-failure"):
        assert report["context"]["state_artifact"]
        attached = next(a for m in report["messages"] for a in m.get("attachments", []) if a["name"] == filename)
        assert client.get("/api/artifacts/" + attached["sha256"]).content == captured


@pytest.mark.parametrize("result", [
    {}, {"slot": None}, {"slot": True}, {"slot": "89"}, {"slot": 89, "path": "owned.state90"},
    {"slot": 89, "verified": False},
])
def test_unproved_or_conflicting_saved_slot_never_falls_back_to_requested_slot(result):
    with pytest.raises(RuntimeError):
        _checkpoint_slot(result, "retroarch")


@pytest.mark.parametrize("result,expected", [
    ({"slot": 0}, 0), ({"file": "owned.state"}, 0), ({"file": "owned.state-1"}, -1),
    ({"file": "owned.state89"}, 89),
])
def test_zero_negative_and_filename_checkpoint_evidence(result, expected):
    assert _checkpoint_slot(result, "retroarch") == expected


@pytest.mark.parametrize("result", [{}, {"saved": True}, {"slot": 2}, {"file": "owned.state1"}])
def test_dolphin_requires_actual_native_evidence(result):
    with pytest.raises(RuntimeError):
        _checkpoint_slot(result, "dolphin")


@pytest.mark.parametrize("result", [{"slot": 1}, {"file": "owned.s01"}])
def test_dolphin_accepts_explicit_native_slot_or_supported_checkpoint_filename(result):
    assert _checkpoint_slot(result, "dolphin") == 1
