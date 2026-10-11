"""#1146 — pickwhip onto a writerless game: the gap report must carry the game moment (checkpoint slot,
portable export, frame capture), and preservation failures must never block the gap report/overlay answer."""
from types import SimpleNamespace

import gbox.char_coverage as cc

GAME = {"game_id": "g1", "title": "Dead or Alive 2", "platform": "dreamcast"}
META = {"slug": "sa2_amy_rose", "name": "Amy Rose", "source": {"game_title": "Sonic Adventure 2 (USA)"}}
NEED = {"target": "the game's player model", "have": "nothing for this game yet"}
SID = "w1-s1"


class API:
    """Minimal /api stand-in recording calls; jobs and requests behave per script."""

    def __init__(self, requests=None, sessions=None, jobs=None, capture_ok=True):
        self.calls = []
        self.requests = requests or {}
        self.sessions = sessions if sessions is not None else [{"session_id": SID, "state": "running"}]
        self.jobs = jobs or {}
        self.capture_ok = capture_ok

    def __call__(self, ctx, method, path, **kw):
        self.calls.append((method, path, kw.get("json")))
        if method == "GET" and path == "/api/requests":
            return list(self.requests.values())
        if method == "GET" and path == f"/api/requests/{kw.get('json', {}).get('id', 'r1')}" or \
           (method == "GET" and path == "/api/requests/r1"):
            return self.requests.get("r1", {})
        if method == "GET" and path == "/api/sessions":
            return self.sessions
        if method == "POST" and path == "/api/requests":
            rid = f"r{len(self.requests) + 1}"
            self.requests[rid] = {"id": rid, "number": len(self.requests) + 1, "title": kw["json"]["title"],
                                  "messages": []}
            return self.requests[rid]
        if method == "GET" and path.startswith("/api/jobs/"):
            return self.jobs.get(path.rsplit("/", 1)[-1], {"id": path.rsplit("/", 1)[-1], "state": "succeeded",
                                                           "output": {"result": {}}})
        if method == "POST" and path == "/api/jobs":
            jid = f"j{len(self.jobs) + 1}"
            self.jobs[jid] = {"id": jid, "state": "succeeded", "output": {"result": {}}}
            return self.jobs[jid]
        if method == "POST" and path == "/api/requests/r1/capture":
            if not self.capture_ok:
                raise RuntimeError("session has ended")
            self.requests["r1"]["messages"].append({"author": "agent", "text": kw["json"]["text"],
                                                    "attachments": [{"name": "task-r1.png", "type": "image/png"}],
                                                    "task_step": kw["json"].get("task_step")})
            return {}
        if method == "POST" and path == "/api/requests/r1/messages":
            self.requests["r1"]["messages"].append({"author": "agent", "text": kw["json"]["text"],
                                                    "task_step": kw["json"].get("task_step")})
            return {}
        raise AssertionError(f"unexpected api call {method} {path}")


def inp(sid=SID, x=0.47, y=0.57):
    return SimpleNamespace(session_id=sid, slot="player", x=x, y=y)


CTX = SimpleNamespace(job_id="job1", parent_request_id=None)


def existing_gap(api):
    """Pre-file the gap request (r1) the way gap() dedupes, so preserve paths can target it."""
    api.requests["r1"] = {"id": "r1", "number": 1, "title": f"GAP: character writer for {GAME['title']}",
                          "messages": []}
    return {"id": "r1", "number": 1, "existing": True}


def test_running_session_preserves_moment(monkeypatch):
    api = API(requests={})
    existing_gap(api)
    api.jobs = {}  # default job replies come from POST handler; script the two tool jobs below
    dispatched = []

    def run_job(ctx, a, tool, i, rid, limit=180):
        dispatched.append((tool, i, rid))
        if tool == "session_op":                                  # the emulator wrote slot 71, not the requested 70
            return {"state": "succeeded", "output": {"result": {"slot": 71, "frame": "png1"}}}
        return {"state": "succeeded", "output": {"result": {"artifact": "abc", "bytes": 9717672,
                                                            "file": "Dead or Alive 2.state71"}}}

    monkeypatch.setattr(cc, "_run_job", run_job)
    import gbox.overlay_swap as os_
    monkeypatch.setattr(os_, "start", lambda ctx, a, m, sid, x=None, y=None: {"status": "overlay"})

    res = cc.no_writer(CTX, api, META, GAME, NEED, inp())
    assert res["status"] == "overlay"
    p = res["preserved"]
    assert p["saved"] and p["slot"] == 71 and p["captured"] is True and p["artifact"] == "abc"
    (t1, save, r1), (t2, export, r2) = dispatched
    assert (t1, save["op"], save["args"]["slot"], r1) == ("session_op", "save_state", 70, "r1")
    # the exact checkpoint is uploaded (no second save): the ACTUAL slot, guarded against stale files
    assert (t2, export["op"], export["slot"], r2) == ("state_transfer", "export_saved", 71, "r1")
    assert export["not_before"] > 0
    msgs = api.requests["r1"]["messages"]
    assert any("Checkpoint of this moment saved in slot 71" in m["text"] for m in msgs)
    assert any("Portable export 9717672 bytes" in m["text"] for m in msgs)
    assert any(m.get("attachments") for m in msgs), "the captured frame must be attached to the request"


def test_dead_session_skips_preservation_but_still_overlays(monkeypatch):
    api = API(requests={}, sessions=[{"session_id": SID, "state": "ended"}])
    existing_gap(api)
    import gbox.overlay_swap as os_
    monkeypatch.setattr(os_, "start", lambda ctx, a, m, sid, x=None, y=None: {"status": "overlay"})

    def fail(*a, **k):
        raise AssertionError("no preservation on a dead session")

    monkeypatch.setattr(cc, "preserve_moment", fail)
    res = cc.no_writer(CTX, api, META, GAME, NEED, inp())
    assert res["status"] == "overlay"
    assert "preserved" not in res


def test_failed_save_posts_note_and_still_overlays(monkeypatch):
    api = API(requests={})
    existing_gap(api)
    monkeypatch.setattr(cc, "_run_job", lambda *a, **k: {"state": "failed", "error": "no reply from emulator"})
    import gbox.overlay_swap as os_
    monkeypatch.setattr(os_, "start", lambda ctx, a, m, sid, x=None, y=None: {"status": "overlay"})

    res = cc.no_writer(CTX, api, META, GAME, NEED, inp())
    assert res["status"] == "overlay"
    p = res["preserved"]
    assert p["saved"] is False and "no reply" in p["error"]
    assert any("Save state unavailable" in m["text"] for m in api.requests["r1"]["messages"])


def test_capture_failure_degrades_to_partial_note(monkeypatch):
    api = API(requests={}, capture_ok=False)
    existing_gap(api)
    monkeypatch.setattr(cc, "_run_job", lambda ctx, a, tool, i, rid, limit=180: (
        {"state": "succeeded", "output": {"result": {"slot": 70, "frame": "png1"}}} if tool == "session_op" else
        {"state": "succeeded", "output": {"result": {"artifact": "abc", "bytes": 9717672,
                                                     "file": "x.state70"}}}))
    import gbox.overlay_swap as os_
    monkeypatch.setattr(os_, "start", lambda ctx, a, m, sid, x=None, y=None: {"status": "overlay"})

    res = cc.no_writer(CTX, api, META, GAME, NEED, inp())
    assert res["status"] == "overlay"
    p = res["preserved"]
    assert p["saved"] is True and p["captured"] is False and p["artifact"] == "abc"
    partial = [m for m in api.requests["r1"]["messages"]
               if (m.get("task_step") or {}).get("status") == "partial"]
    assert partial and "Frame capture unavailable" in partial[0]["text"]


def test_no_session_unchanged_gap_only():
    api = API(requests={}, sessions=[])
    res = cc.no_writer(CTX, api, META, GAME, NEED, inp(sid=""))
    assert res["status"] == "missing"
    assert "preserved" not in res
    assert res["request"]["number"] == 1


def test_moment_slot_increments_per_preserved_message():
    api = API(requests={})
    existing_gap(api)
    api.requests["r1"]["messages"] = [
        {"task_step": {"action": "preserve pickwhip moment", "status": "succeeded"}},
        {"task_step": {"action": "preserve pickwhip moment", "status": "failed"}},
        {"task_step": {"action": "capture pickwhip frame", "status": "succeeded"}},
    ]
    assert cc._moment_slot(CTX, api, "r1") == 72
    assert cc._moment_slot(CTX, API(requests={}), "r1") == 70
