"""Moments gBox keeps without the operator pressing Save go through gBox's own save slot (state_transfer op=snapshot,
gbox/state_snapshot.py), never the operator's. 2026-10-20: an RE4 issue report pressed Dolphin's slot 1 save ("Saved
State to G4BE08.s01" over the operator's own save), the game froze and the follow-up export failed.

Each flow runs the REAL state_transfer tool on a fake Dolphin (slot 1 = the operator's Save / Load slot, slot 10 =
gBox's demo slot) and a fake RetroArch (the operator on slot 0, slot 9 = gBox's): the operator's slot files stay byte
for byte, RetroArch is switched back to their slot, the state file is attached, and the fields Hermes and the report
UI read are set. A failed snapshot (a PC still on a gBox from before op=snapshot, an emulator that refuses) never falls
back to a save into the operator's slot."""
import base64
import hashlib
import io
import os
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from PIL import Image

import gbox.server as server
from gbox import char_coverage as cc, emulation_issue, state_snapshot, tools
from gbox.agent import ChatHub
from gbox.models import Job, JobState
from gbox.server import create_app

GID, SID = "re4gc0000000001", "w1-moment"
SNAP = b"gbox-own-slot-moment"
DIGEST = hashlib.sha256(SNAP).hexdigest()
SNAP_FILE = {"dolphin": "G4BE08.s10", "retroarch": "Game.state9"}
T0 = 1_700_000_000
KINDS = ["dolphin", "retroarch"]


def png(color=(40, 90, 160)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (64, 48), color).save(out, "PNG")
    return out.getvalue()


def _keep(folder: Path, name: str, data: bytes):
    f = folder / name
    f.write_bytes(data)
    os.utime(f, (T0, T0))


class FakeDolphin:
    """Standalone Dolphin as gBox drives it: save_state presses the slot 1 hotkey whatever slot it is given (the
    operator's own Save state / Load state slot); jump_save saves through demo slot 10, copies it out and removes it."""
    name, JUMP_SLOT, gecko_id, proc = "dolphin", 10, "G4BE08", None

    def __init__(self, root: Path, ff_on=False):
        self.root, self.ff_on, self.saves, self.stopped = root, ff_on, [], False
        self.states = root / "User" / "StateSaves"
        self.states.mkdir(parents=True)
        _keep(self.states, "G4BE08.s01", b"the operator's own slot 1 save")
        _keep(self.states, "G4BE08.s08", b"the rewind ring's slot 8")

    def _exe(self):
        return self.root / "Dolphin.exe"

    def state_dir(self):
        return self.states

    def save_state(self, slot=None):
        self.saves.append(slot)
        f = self.states / "G4BE08.s01"
        f.write_bytes(b"gBox's save over the operator's slot 1")
        return {"slot": 1, "path": str(f), "bytes": f.stat().st_size, "verified": True}

    def jump_save(self, dest):
        if self.ff_on:
            raise RuntimeError("fast-forward is on: no jump state now")
        slot10 = self.states / "G4BE08.s10"
        slot10.write_bytes(SNAP)
        Path(dest).write_bytes(slot10.read_bytes())
        slot10.unlink()
        return len(SNAP)

    def get_frame(self):
        return png()

    def stop_game(self):
        self.stopped = True
        return {"returncode": 0}

    def slots(self):
        return {f.name: (f.read_bytes(), f.stat().st_mtime) for f in self.states.iterdir()}


class FakeRetroArch:
    """RetroArch: the operator plays on slot 0 (Save / Load use the current slot); SAVE_STATE writes the current slot's
    file (land: a dropped slot command, the save lands in that slot instead); gBox's slot is 9."""
    name, proc = "retroarch", None

    def __init__(self, root: Path, land=None, verified=True):
        self.slot, self.land, self.verified, self.saves, self.stopped = 0, land, verified, [], False
        self.states_override = root / "states"
        self.states_override.mkdir(parents=True)
        _keep(self.states_override, "Game.state", b"the operator's own slot 0 save")
        _keep(self.states_override, "Game.state9", b"an older transfer in slot 9")

    def state_dir(self):
        return self.states_override

    def _slot(self, slot):
        if slot is not None:
            self.slot = int(slot)
        return self.slot

    def save_state(self, slot=None):
        self._slot(slot)
        actual = self.slot if self.land is None else self.land
        self.saves.append(actual)
        f = self.states_override / f"Game.state{actual or ''}"
        f.write_bytes(SNAP)
        self.slot = actual
        return {"verified": self.verified, "path": str(f), "slot": actual, "bytes": f.stat().st_size}

    def load_state(self, slot=None):
        return {"slot": self._slot(slot)}

    def get_frame(self):
        return png()

    def stop_game(self):
        self.stopped = True
        return {"returncode": 0}

    def slots(self):
        return {f.name: (f.read_bytes(), f.stat().st_mtime) for f in self.states_override.iterdir()}


def emulator(kind: str, root: Path, **kw):
    """(adapter, the session's game) as the session's PC keeps them in tools.SESSIONS."""
    if kind == "dolphin":
        return FakeDolphin(root, **kw), {"game_id": GID, "title": "Resident Evil 4", "platform": "gamecube"}
    return FakeRetroArch(root, **kw), {"game_id": GID, "title": "Resident Evil 4", "_rom_path": "/roms/Game.chd"}


def untouched(ad, before: dict):
    """The operator's slots as they were: every file byte for byte, no save of theirs pressed, RetroArch on their slot."""
    assert ad.slots() == before
    if ad.name == "dolphin":
        assert ad.saves == []
    else:
        assert ad.slot == 0


def run_tool(tool: str, inp: dict, runtime: Path):
    """A job as the session's PC runs it: the real tool; its artifacts as (name, bytes, media type, provenance)."""
    fn, model = {"state_transfer": (tools.state_transfer, tools.StateXIn),
                 "session_op": (tools.session_op, tools.SessionIn)}[tool]
    arts = []
    ctx = SimpleNamespace(config=SimpleNamespace(runtime=runtime), server=None, headers={}, progress=lambda *a, **k: None,
                          artifact=lambda name, data, mt="application/octet-stream", **prov: arts.append((name, data, mt, prov)))
    return fn(model.model_validate(inp), ctx), arts


def old_worker(*a, **k):
    """state_transfer on a PC from before op=snapshot: export's op list."""
    raise ValueError("op: export | export_saved | import")


# --- the control plane's reports: issue report, failed-action auto report, disputed completion -------------------------
class InlineWorker:
    """The session's PC taking each job the moment it is queued: state_transfer / session_op run for real on the fake
    emulator, their artifacts stored with the job like an uploaded result; any other tool fails at once."""

    def __init__(self, store, submit, runtime: Path):
        self.store, self.submit, self.runtime, self.jobs = store, submit, runtime, []

    def __call__(self, req, actor, *args, **kwargs):
        job = self.submit(req, actor, *args, **kwargs)
        self.jobs.append((req.tool, dict(req.input)))
        if job.state != JobState.QUEUED:
            return job
        current = self.store.get("job", job.id)
        try:
            out, arts = run_tool(job.tool, job.input, self.runtime)
        except Exception as exc:                                  # noqa: BLE001 - a failed job, as a worker reports it
            self.store.put("job", job.id, current | {"state": "failed", "error": f"{type(exc).__name__}: {exc}",
                                                     "finished": time.time()})
            return job
        for name, data, mt, prov in arts:
            self.store.put_artifact(data, name, mt, prov | {"job": job.id})
        self.store.put("job", job.id, current | {"state": "succeeded", "output": out, "started": time.time(),
                                                 "finished": time.time()})
        return job

    def saves(self):
        return [i for t, i in self.jobs if t == "session_op" and i.get("op") == "save_state"]


class InlineThread:
    """server.threading.Thread here: a watcher runs at once, inside the request (its job has already run)."""

    def __init__(self, target=None, args=(), kwargs=None, daemon=None, name=None):
        self.target, self.args, self.kwargs = target, args, kwargs or {}

    def start(self):
        self.target(*self.args, **self.kwargs)


@pytest.fixture
def reports(cfg, tmp_path, monkeypatch):
    monkeypatch.setenv("GBOX_HERMES_HOME", str(tmp_path / "hermes"))
    monkeypatch.setattr(ChatHub, "post", lambda *a, **k: None)
    app = create_app(cfg)
    store = app.state.store
    issue = next(r.endpoint for r in app.routes if getattr(r, "path", None) == "/api/requests/issue")
    cells = dict(zip(issue.__code__.co_freevars, issue.__closure__))
    cells["_issue_log"].cell_contents = lambda *a: ("", "offline test")
    cells["_issue_chat"].cell_contents = lambda *a: []
    worker = InlineWorker(store, cells["submit"].cell_contents, tmp_path / "runtime")
    cells["submit"].cell_contents = worker                      # every route's submit (one closure cell)
    client = TestClient(app, headers={"Authorization": f"Bearer {cfg.token()}"})
    monkeypatch.setattr(server, "threading", SimpleNamespace(Thread=InlineThread, Lock=threading.Lock,
                                                             Condition=threading.Condition, get_ident=threading.get_ident))

    def start(kind, **kw):
        """A running RE4 session on the fake emulator, with a live picture for the reports' screenshots."""
        ad, g = emulator(kind, tmp_path / kind, **kw)
        monkeypatch.setitem(tools.SESSIONS, SID, (ad, g))
        store.put("session", SID, {"session_id": SID, "state": "running", "adapter": kind, "game_id": GID,
                                   "title": "Resident Evil 4", "started": time.time()})
        client.post(f"/api/sessions/{SID}/frame", content=png()).raise_for_status()
        return ad
    return SimpleNamespace(app=app, store=store, client=client, worker=worker, start=start)


def file_issue(r) -> str:
    res = r.client.post("/api/requests/issue", json={"session_id": SID, "what": "Report issue (Capture icon)",
                                                      "image_b64": base64.b64encode(png()).decode()})
    assert res.status_code == 200, res.text
    return res.json()["id"]


def file_auto_report(r) -> str:
    res = r.client.post("/api/requests/auto-mod-failure", json={"session_id": SID, "model": "Amy", "detail": "writer failed",
                                                                 "image_b64": base64.b64encode(png()).decode()})
    assert res.status_code == 200, res.text
    return res.json()["id"]


def dispute(r) -> str:
    rid = r.client.post("/api/requests", json={"title": "RE4 model swap", "body": "Replace Leon"}).json()["id"]
    r.client.post(f"/api/requests/{rid}/status", json={"status": "done"}).raise_for_status()
    res = r.client.post(f"/api/requests/{rid}/report-incomplete", json={"explanation": "Leon is still there",
                                                                         "session_id": SID})
    assert res.status_code == 200, res.text
    return rid


FLOWS = {"issue report": (file_issue, "save reported game moment"),
         "auto report": (file_auto_report, "save game moment"),
         "disputed completion": (dispute, "save failed moment")}


@pytest.mark.parametrize("flow", FLOWS)
@pytest.mark.parametrize("kind", KINDS)
def test_a_reported_moment_is_saved_through_gboxs_own_slot_and_attached(reports, kind, flow):
    file, action = FLOWS[flow]
    ad = reports.start(kind)
    before = ad.slots()
    rid = file(reports)
    report = reports.store.get("request", rid)
    ctx = report["context"]
    job = reports.store.get("job", ctx["state_job_id"])
    assert (job["tool"], job["input"]["op"], job["input"]["session_id"]) == ("state_transfer", "snapshot", SID)
    assert job["state"] == "succeeded" and job["parent_request_id"] == rid
    # the field contract: one job is both the save and its portable export; no emulator slot holds the moment
    assert ctx["state_export_job_id"] == ctx["state_job_id"] and ctx["state_snapshot"] is True
    assert "state_slot" not in ctx and "state_requested_slot" not in ctx
    assert (ctx["state_artifact"], ctx["state_file"]) == (DIGEST, SNAP_FILE[kind])
    attached = [a for m in report["messages"] for a in m.get("attachments", []) if a["name"] == SNAP_FILE[kind]]
    assert len(attached) == 1 and reports.client.get(f"/api/artifacts/{attached[0]['sha256']}").content == SNAP
    steps = [m for m in report["messages"] if (m.get("task_step") or {}).get("action") == action]
    assert [s["task_step"]["status"] for s in steps] == ["queued", "finished"]
    assert "through gBox's own save slot" in steps[0]["text"] and "your own save slots are left as they are" in steps[0]["text"]
    assert ("Dolphin slot 10" if kind == "dolphin" else "switched back to your slot 0") in steps[1]["text"]
    assert not any(f"slot {n}" in m["text"] for m in report["messages"] for n in (40, 60))
    untouched(ad, before)
    assert reports.worker.saves() == []                         # no session_op save_state: the operator's slot
    assert [t for t, _ in reports.worker.jobs if t == "state_transfer"] == ["state_transfer"]   # one job, no export_saved


@pytest.mark.parametrize("flow", FLOWS)
@pytest.mark.parametrize("kind", KINDS)
def test_a_pc_without_snapshots_reports_no_moment_and_never_saves_into_the_operators_slot(reports, monkeypatch, kind, flow):
    monkeypatch.setattr(state_snapshot, "take", old_worker)
    file, action = FLOWS[flow]
    ad = reports.start(kind)
    before = ad.slots()
    rid = file(reports)
    report = reports.store.get("request", rid)
    ctx = report["context"]
    assert reports.store.get("job", ctx["state_job_id"])["state"] == "failed"
    assert "state_artifact" not in ctx and "state_slot" not in ctx
    failed = [m for m in report["messages"] if (m.get("task_step") or {}).get("action") == action
              and m["task_step"]["status"] == "failed"]
    assert len(failed) == 1 and failed[0]["text"].startswith("The game moment could not be captured: ValueError: op:")
    assert "needs an update" in failed[0]["text"] and "Nothing was saved into your save slots instead" in failed[0]["text"]
    untouched(ad, before)
    assert reports.worker.saves() == [] and [t for t, _ in reports.worker.jobs if t == "state_transfer"] == ["state_transfer"]


@pytest.mark.parametrize("kind,trouble", [("dolphin", {"ff_on": True}),
                                          ("retroarch", {"land": 0, "verified": False})])   # the save hit slot 0
def test_a_snapshot_the_emulator_spoils_leaves_the_operators_slot_as_it_was(reports, kind, trouble):
    ad = reports.start(kind, **trouble)
    before = ad.slots()
    report = reports.store.get("request", file_issue(reports))
    assert "state_artifact" not in report["context"]
    assert report["messages"][-1]["text"].startswith("The game moment could not be captured: RuntimeError:")
    untouched(ad, before)                                        # RetroArch: their slot 0 file put back as it was
    assert reports.worker.saves() == []


@pytest.mark.parametrize("flow", FLOWS)
def test_a_snapshot_that_cannot_be_queued_is_said_once_and_nothing_is_saved(reports, monkeypatch, flow):
    file, action = FLOWS[flow]
    ad = reports.start("dolphin")
    before, queue = ad.slots(), reports.worker.submit

    def refuse(req, actor, *a, **k):
        if req.tool == "state_transfer":
            raise HTTPException(409, "this PC can't take a snapshot now")
        return queue(req, actor, *a, **k)
    monkeypatch.setattr(reports.worker, "submit", refuse)
    report = reports.store.get("request", file(reports))
    steps = [m for m in report["messages"] if (m.get("task_step") or {}).get("action") == action]
    assert [s["task_step"]["status"] for s in steps] == ["failed"] and "can't take a snapshot now" in steps[0]["text"]
    assert "state_job_id" not in report["context"] and "state_snapshot" not in report["context"]
    untouched(ad, before)
    assert reports.worker.saves() == []


def test_a_reported_snapshot_is_still_a_last_played_moment(reports):
    """A session that ended without a moment of its own (a crash) offers the newest state uploaded for it: a report's
    snapshot (G4BE08.s10) is one, as the slot 1 export (G4BE08.s01) it replaces was."""
    from gbox import last_played
    reports.start("dolphin")
    file_issue(reports)
    crashed = reports.store.get("session", SID) | {"state": "ended", "exit": {"returncode": 3221225477}}
    assert last_played.moment_of(reports.store, crashed)["artifact"] == DIGEST


def test_a_report_on_a_bot_demo_says_it_is_a_live_demo_report(reports):
    """A report filed while the operator watches a bot demo names the run kind so Hermes analyses state live."""
    from gbox import screensaver
    reports.start("dolphin")
    plain = reports.store.get("request", file_issue(reports))["body"]
    assert "## Run kind" not in plain
    reports.store.put(screensaver.BOT_DEMO, SID.split("-", 1)[-1], {"job": "moment", "game_id": GID, "by": "operator", "agent": False, "at": time.time()})
    body = reports.store.get("request", file_issue(reports))["body"]
    assert "## Run kind\nBot demo (autoplay)" in body and "Ghidra" in body


def test_other_emulators_keep_their_own_save_state(reports):
    """No slot of gBox's own (DuckStation, mGBA, RPCS3...): today's session_op save_state, saying no false slot."""
    reports.start("dolphin")
    reports.store.put("session", SID, reports.store.get("session", SID) | {"adapter": "duckstation"})
    report = reports.store.get("request", file_issue(reports))
    job = reports.store.get("job", report["context"]["state_job_id"])
    assert (job["tool"], job["input"]["op"]) == ("session_op", "save_state")
    assert report["context"]["state_slot"] == job["input"]["args"]["slot"] and "state_snapshot" not in report["context"]
    assert any("the emulator's own save state" in m["text"] for m in report["messages"])


# --- emulation incidents ------------------------------------------------------------------------------------------------
def incident(cfg, tmp_path, monkeypatch, kind, frames=None):
    app = create_app(cfg)
    store = app.state.store
    ad, g = emulator(kind, tmp_path / kind)
    monkeypatch.setitem(tools.SESSIONS, SID, (ad, g))
    game = {"game_id": GID, "title": "Resident Evil 4", "platform": "gamecube", "source_paths": ["/roms/re4.iso"]}
    store.upsert_catalog([game])
    session = {"session_id": SID, "state": "running", "game_id": GID, "title": "Resident Evil 4", "adapter": kind}
    store.put("session", SID, session)
    client = TestClient(app, headers={"Authorization": f"Bearer {cfg.token()}"})
    report = client.post("/api/requests", json={"title": "Emulation issue", "body": "RE4 froze"}).json()
    job = Job(tool="emulation_recovery", state=JobState.RUNNING, started=1, input={"session_id": SID},
              parent_request_id=report["id"])
    store.put("job", job.id, job.model_dump())
    calls, shots = [], iter(frames or [])

    def run(tool, data, wid, wait):
        calls.append((tool, data))
        if tool == "get_frame":
            return {"sha256": store.put_artifact(png(next(shots, (40, 90, 160))), "frame.png", "image/png", {}).sha256}
        if tool == "state_transfer" or (tool == "session_op" and data["op"] == "save_state"):
            out, arts = run_tool(tool, data, tmp_path / "runtime")
            for name, blob, mt, prov in arts:
                store.put_artifact(blob, name, mt, prov)
            return out
        if tool == "launch_game":
            return {"session_id": "w1-relaunched"}
        return {"result": {"state": "PAUSED", "running": True}}
    it = emulation_issue.Incident(store, report, session, game, {"id": "w1", "name": "PLAY-PC"}, run,
                                  lambda rid, number: "hermes-job", job, sleep=lambda _: None)
    return it, ad, calls


@pytest.mark.parametrize("kind", KINDS)
def test_an_emulation_incident_keeps_its_checkpoint_through_gboxs_own_slot(cfg, tmp_path, monkeypatch, kind):
    it, ad, calls = incident(cfg, tmp_path, monkeypatch, kind)
    it.action = "diagnose"
    before = ad.slots()
    it.run()
    report = it.store.get("request", it.rid)
    ctx = report["context"]
    assert ("state_transfer", {"session_id": SID, "op": "snapshot"}) in calls
    assert not any(t == "session_op" and d["op"] == "save_state" for t, d in calls)
    assert (ctx["state_artifact"], ctx["state_file"], ctx["state_snapshot"]) == (DIGEST, SNAP_FILE[kind], True)
    assert "state_slot" not in ctx
    kept = next(m for m in report["messages"] if (m.get("task_step") or {}).get("action") == "preserve program state")
    assert kept["attachments"][0]["name"] == SNAP_FILE[kind] and "saved through" in kept["text"]
    untouched(ad, before)


@pytest.mark.parametrize("kind", KINDS)
def test_an_incident_without_a_snapshot_neither_saves_into_the_operators_slot_nor_relaunches(cfg, tmp_path, monkeypatch,
                                                                                            kind):
    monkeypatch.setattr(state_snapshot, "take", old_worker)
    it, ad, calls = incident(cfg, tmp_path, monkeypatch, kind)
    before = ad.slots()
    it.run()
    report = it.store.get("request", it.rid)
    failed = next(m for m in report["messages"] if (m.get("task_step") or {}).get("action") == "preserve program state")
    assert failed["task_step"]["status"] == "failed" and "Nothing was saved into your save slots instead" in failed["text"]
    assert not any(t == "launch_game" or (t == "session_op" and d["op"] == "save_state") for t, d in calls)
    assert any("no portable checkpoint" in m["text"] for m in report["messages"])
    untouched(ad, before)


# --- pickwhip gap reports (gbox/char_coverage.py, on the worker) ----------------------------------------------------------
def pickwhip(tmp_path, monkeypatch, kind):
    from test_pickwhip_moment import API, SID as PW_SID, existing_gap
    import gbox.overlay_swap as overlay
    ad, g = emulator(kind, tmp_path / kind)
    monkeypatch.setitem(tools.SESSIONS, PW_SID, (ad, g))
    api = API(requests={}, sessions=[{"session_id": PW_SID, "state": "running", "adapter": kind}])
    existing_gap(api)
    calls = []

    def run_job(ctx, a, tool, inp, rid, limit=180):
        calls.append((tool, inp))
        try:
            return {"state": "succeeded", "output": run_tool(tool, inp, tmp_path / "runtime")[0]}
        except Exception as exc:                                  # noqa: BLE001
            return {"state": "failed", "error": f"{type(exc).__name__}: {exc}"}
    monkeypatch.setattr(cc, "_run_job", run_job)
    monkeypatch.setattr(overlay, "start", lambda *a, **k: {"status": "overlay"})
    return ad, api, calls, PW_SID


@pytest.mark.parametrize("kind", KINDS)
def test_a_pickwhip_moment_is_saved_through_gboxs_own_slot(tmp_path, monkeypatch, kind):
    from test_pickwhip_moment import CTX, GAME, META, NEED, inp
    ad, api, calls, sid = pickwhip(tmp_path, monkeypatch, kind)
    before = ad.slots()
    p = cc.no_writer(CTX, api, META, GAME, NEED, inp())["preserved"]
    assert p["saved"] is True and (p["artifact"], p["file"], p["bytes"]) == (DIGEST, SNAP_FILE[kind], len(SNAP))
    assert "slot" not in p and p["captured"] is True
    assert calls == [("state_transfer", {"session_id": sid, "op": "snapshot"})]
    line = next(m["text"] for m in api.requests["r1"]["messages"]
                if (m.get("task_step") or {}).get("action") == "preserve pickwhip moment")
    assert line.startswith("Checkpoint of this moment saved through") and DIGEST in line
    untouched(ad, before)


@pytest.mark.parametrize("kind", KINDS)
def test_a_failed_pickwhip_snapshot_never_falls_back_to_the_operators_slot(tmp_path, monkeypatch, kind):
    from test_pickwhip_moment import CTX, GAME, META, NEED, inp
    monkeypatch.setattr(state_snapshot, "take", old_worker)
    ad, api, calls, sid = pickwhip(tmp_path, monkeypatch, kind)
    before = ad.slots()
    res = cc.no_writer(CTX, api, META, GAME, NEED, inp())
    assert res["status"] == "missing" and res["preserved"]["saved"] is False
    assert calls == [("state_transfer", {"session_id": sid, "op": "snapshot"})]
    assert any("Nothing was saved into your save slots instead" in m["text"] for m in api.requests["r1"]["messages"])
    untouched(ad, before)


# --- last played on the PC: Stop and a game switch -----------------------------------------------------------------------
@pytest.mark.parametrize("kind", KINDS)
def test_stop_keeps_its_moment_through_gboxs_own_slot(tmp_path, monkeypatch, kind):
    ad, g = emulator(kind, tmp_path / kind)
    monkeypatch.setitem(tools.SESSIONS, "w1-stop", (ad, g))
    monkeypatch.setattr(tools, "track_emulator", lambda *a, **k: None)
    before, arts = ad.slots(), []
    ctx = SimpleNamespace(config=SimpleNamespace(runtime=tmp_path / "runtime"), artifact=lambda *a, **k: arts.append((a, k)))
    out = tools._stop_session("w1-stop", {"moment": True}, ctx)
    assert out["result"]["moment"]["artifact"] == DIGEST and ad.stopped
    assert [a[0] for a, _ in arts] == [SNAP_FILE[kind], "moment.png"] and arts[0][1]["snapshot"] is True
    untouched(ad, before)


@pytest.mark.parametrize("kind", KINDS)
def test_a_game_switch_keeps_the_previous_moment_through_gboxs_own_slot(tmp_path, monkeypatch, kind):
    ad, g = emulator(kind, tmp_path / kind)
    monkeypatch.setattr(tools, "SESSIONS", {"w1-old": (ad, g)})
    monkeypatch.setattr(tools, "track_emulator", lambda *a, **k: None)
    before = ad.slots()
    ctx = SimpleNamespace(config=SimpleNamespace(runtime=tmp_path / "runtime"), progress=lambda *a: None,
                          artifact=lambda *a, **k: None, server=None)
    (checkpoint,) = tools._close_previous_games(ctx)
    assert (checkpoint["artifact"], checkpoint["bytes"], checkpoint["file"]) == (DIGEST, len(SNAP), SNAP_FILE[kind])
    assert ad.stopped
    untouched(ad, before)


def test_the_app_quit_and_evidence_moments_ask_for_a_snapshot(cfg):
    app = create_app(cfg)
    app.state.store.put("session", SID, {"session_id": SID, "state": "running", "adapter": "dolphin", "game_id": GID})
    asked = []
    route = next(r for r in app.routes if getattr(r, "path", "") == "/api/sessions/{sid}/moment")
    cells = dict(zip(route.endpoint.__code__.co_freevars, route.endpoint.__closure__))
    cells["_run_job"].cell_contents = lambda tool, inp, *a, **k: asked.append((tool, inp)) or {"result": {"artifact": "a" * 64}}
    client = TestClient(app, headers={"Authorization": f"Bearer {cfg.token()}"})
    assert client.post(f"/api/sessions/{SID}/moment?wait=3").json() == {"saved": True, "artifact": "a" * 64}
    assert client.post("/api/evidence/moments", json={"session_id": SID}).status_code == 200
    assert asked == [("state_transfer", {"session_id": SID, "op": "snapshot"})] * 2
