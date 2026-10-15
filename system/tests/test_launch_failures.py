"""Launch failure reports (gbox/launch_failures.py, docs/launch-failure-reports.md): a failed launch files one ticket per
failure signature, repeats append occurrences, known errors get a diagnosis and a safe first remedy, the ticket is queued
for a Hermes investigation, and the verify loop closes it once the merged fix launches (or reopens it). Real Store, fake
control plane; the server wiring is exercised through the HTTP API at the end."""
import io
import json
import time

import pytest
from fastapi.testclient import TestClient

from gbox import launch_failures as LF
from gbox.models import new_id
from gbox.store import Store

DOA2 = "1de2e7634f3161ff"
MGS = "ba32927ecc104b9a"
MOD = "doa2_roster_59d8ed0e"
PC = "wjay"
TIMEOUT_ERR = ("RuntimeError: retroarch started but content not running after 30s: [INFO] [Core]: Loading dynamic libretro "
               "core from: flycast_libretro.dll\n[INFO] [Content]: Loading content file: DOA2.gdi\n[WARN] flycast: GDROM not ready")
BLOCK_ERR = ("Unsupported: The previous game (Metal Gear Solid - The Twin Snakes) could not be saved: the emulator didn't write a "
             "save state. It was kept running. Stop it in Sessions (or close its emulator window) before starting another game.")


def png(colour=(200, 40, 40)) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (32, 24), colour).save(buf, "PNG")
    return buf.getvalue()


class Plane:
    """The control plane the ledger talks to: requests, jobs, Hermes, evidence capture, deploys - all recorded."""

    def __init__(self, store: Store):
        self.store, self.t = store, 1_000_000.0
        self.submitted, self.investigations, self.verifications, self.unprioritized = [], [], [], []
        self.job_outcome = {"launch_game": ("succeeded", None), "prepare_mod": ("succeeded", None)}
        self.queue_jobs, self.deployed, self.frames, self.attempts = {}, {}, {}, []
        self.verify_raises = None
        self.workers_list = [{"id": PC, "name": "JAYBUILTFINALE", "os": "windows", "online": True, "idle_seconds": 900,
                              "background_testing": True},
                             {"id": "wspark", "name": "lilspark", "os": "linux", "online": True}]

    def now(self):
        return self.t

    def create_request(self, body):
        rid, n = new_id(), len(self.store.all("request")) + 1
        doc = {"id": rid, "number": n, "title": body["title"], "body": body["body"], "source": body["source"],
               "author": body["author"], "automated": True, "context": body["context"], "status": "open",
               "created": self.t, "started": None, "completed": None, "messages": [], "metrics": {}}
        self.store.put("request", rid, doc)
        return doc

    def submit_job(self, tool, inp, worker_id):
        state, err = self.job_outcome.get(tool, ("succeeded", None))
        jid = new_id()
        job = {"id": jid, "tool": tool, "input": inp, "require_worker": worker_id, "worker_id": worker_id, "state": state,
               "error": err, "created": self.t, "started": self.t, "finished": self.t + 1,
               "output": {"session_id": f"{worker_id}-{jid}"} if state == "succeeded" else None}
        self.store.put("job", jid, job)
        self.submitted.append((tool, inp, worker_id, jid))
        return job

    def investigate(self, rid, number, task, attempt=1):
        self.investigations.append((rid, number, task))
        self.attempts.append(attempt)
        return {"mode": "queue", "job_id": None, "priority": 0}

    def verify_launch(self, rec, node):
        if self.verify_raises:
            raise RuntimeError(self.verify_raises)
        jid = new_id()
        job = {"id": jid, "tool": "evidence_capture", "state": "running", "input": {"game_id": rec["game_id"],
               "mod": rec["mod"], "node": node}, "created": self.t}
        self.store.put("job", jid, job)
        self.verifications.append((rec["id"], node, jid))
        return job

    def finish_verification(self, jid, ok=True, error=None, dark=False):
        job = self.store.get("job", jid)
        frames = []
        if ok or dark:
            ref = self.store.put_artifact(png(), "frame.png", "image/png", {"job": jid})
            frames = [{"label": "verification", "sha256": ref.sha256, "kind": "in-game frame", "mean_luma": 2 if dark else 90,
                       **({"dark": True} if dark else {})}]
        self.store.put("job", jid, job | {"state": "succeeded" if ok else "failed", "error": error,
                                          "output": {"worker": "lilspark", "frames": frames} if (ok or dark) else None})

    def hooks(self, **over):
        h = LF.Hooks(create_request=self.create_request, workers=lambda: self.workers_list, submit_job=self.submit_job,
                     investigate=self.investigate, queue_job_of=lambda rid: self.queue_jobs.get(rid),
                     unprioritize=self.unprioritized.append, verify_launch=self.verify_launch,
                     deploy_contains=lambda sha: self.deployed.get(sha), last_frame=lambda sid: self.frames.get(sid),
                     now=self.now, spawn=lambda fn: fn(), sleep=lambda s: None)
        for k, v in over.items():
            setattr(h, k, v)
        return h


@pytest.fixture
def plane(tmp_path):
    store = Store(tmp_path / "data")
    store.upsert_catalog([{"game_id": DOA2, "title": "Dead or Alive 2", "platform": "dreamcast", "core": "flycast", "format": "gdi", "profile_id": DOA2,
                           "source_paths": ["x"]},
                          {"game_id": MGS, "title": "Metal Gear Solid - The Twin Snakes", "platform": "gamecube",
                           "source_paths": ["y"]}])
    store.put("worker", PC, {"id": PC, "name": "JAYBUILTFINALE", "os": "windows", "last_seen": time.time()})
    p = Plane(store)
    return p, LF.Ledger(store, p.hooks())


def failed_launch(p, err=TIMEOUT_ERR, mod=MOD, game=DOA2, worker=PC, **extra):
    jid = new_id()
    title = p.store.catalog_get(game)["title"]
    job = {"id": jid, "tool": "launch_game", "state": "failed", "error": err, "worker_id": worker,
           "input": {"game": {"game_id": game, "title": title, "platform": "dreamcast", "source_paths": ["x"]}, "mod": mod},
           "created": p.t - 40, "started": p.t - 38, "finished": p.t,
           "progress_log": ["Loading Dead or Alive 2", "Fetching mod doa2_roster_59d8ed0e from the collection: 1272/1272 MB",
                            "Starting retroarch with DOA2.gdi"]} | extra
    p.store.put("job", jid, job)
    return job


# ------------------------------------------------------------------------------------------------ classification

def test_classifies_the_operator_examples_and_the_known_errors():
    c = LF.classify(TIMEOUT_ERR, adapter="retroarch")
    assert c["cls"] == "content_timeout" and c["label"] == "retroarch content not running after 30s"
    assert c["remedy"] == "relaunch_long_boot" and c["detail"]["secs"] == "30"
    b = LF.classify(BLOCK_ERR, adapter="retroarch")
    assert b["cls"] == "previous_game_blocking" and b["remedy"] == "none"
    assert b["detail"]["blocker"] == "Metal Gear Solid - The Twin Snakes"
    assert "could not be saved" in b["label"]
    cases = {
        "RuntimeError: Fetching mod doa2_roster from the collection timed out after 600 s": "mod_fetch",
        "RuntimeError: Replacement preparation did not complete": "mod_fetch",
        "RuntimeError: dc_boot.bin missing: Flycast needs the Dreamcast BIOS": "missing_bios",
        "FileNotFoundError: ROM not reachable from this node: Z:/DC/DOA2.gdi": "missing_file",
        "RuntimeError: retroarch exited 3221225477: [ERROR] crash": "emulator_crash",
        "worker JAYBUILTFINALE restarted while running": "worker_restarted",
        "JAYBUILTFINALE can't run launch_game: not installed there": "worker_unavailable",
        "Replacement state restore failed (load timed out). The original checkpoint is retained": "state_restore",
        "launch_game: timed out after 900 s": "timeout",
    }
    for err, cls in cases.items():
        assert LF.classify(err, adapter="retroarch")["cls"] == cls, err
    crash = LF.classify(TIMEOUT_ERR.replace("started but content not running after 30s", "exited -1073741819"))
    assert crash["cls"] == "emulator_crash" and "0xC0000005" in crash["label"]


def test_unknown_errors_get_a_stable_class_from_the_normalised_text():
    a = LF.classify("RuntimeError: widget 42 exploded at C:/x/y.bin (job ab12cd34ef)")
    b = LF.classify("RuntimeError: widget 7 exploded at D:/other/z.bin (job 99887766aa)")
    c = LF.classify("RuntimeError: the gizmo refused")
    assert a["cls"].startswith("unknown:") and a["cls"] == b["cls"] != c["cls"]
    assert a["label"].startswith("widget 42 exploded")


def test_signature_is_game_mod_adapter_and_class():
    s = LF.signature(DOA2, MOD, "retroarch", "content_timeout")
    assert s == LF.signature(DOA2, MOD, "RetroArch", "content_timeout")
    assert len({s, LF.signature(DOA2, "", "retroarch", "content_timeout"), LF.signature(DOA2, MOD, "flycast", "content_timeout"),
                LF.signature(DOA2, MOD, "retroarch", "emulator_crash"), LF.signature(MGS, MOD, "retroarch", "content_timeout")}) == 5
    assert LF.adapter_for({"platform": "gamecube"}, "") == "dolphin"
    assert LF.adapter_for({"platform": "xbox"}, "") == "cxbx"
    assert LF.adapter_for({}, "cxbx exited 1 during boot") == "cxbx"
    assert LF.adapter_for({"platform": "dreamcast", "core": "flycast"}, BLOCK_ERR) == "retroarch"
    assert LF.adapter_for({"platform": "dreamcast"}, "redream exited 1") == "redream"
    assert LF.adapter_for({}, "", "Dolphin") == "dolphin"


# ------------------------------------------------------------------------------------------------ filing and dedupe

def test_a_failed_launch_files_one_ticket_with_the_evidence(plane):
    p, ledger = plane
    p.store.put("job", "older", {"id": "older", "tool": "session_op", "state": "succeeded", "worker_id": PC,
                                 "input": {"op": "stop_game"}, "created": p.t - 600})
    job = failed_launch(p)
    log = p.store.put_artifact(b"[worker] launch_game\nRuntimeError ...", "worker.log", "text/plain", {"job": job["id"]})
    p.store.put("job", job["id"], job | {"log_sha": log.sha256})
    rec = ledger.observe_job(p.store.get("job", job["id"]))
    req = p.store.get("request", rec["request_id"])
    assert req["title"] == ("Launch failed: Dead or Alive 2 (doa2_roster_59d8ed0e) on JAYBUILTFINALE: "
                            "retroarch content not running after 30s")
    ctx = req["context"]
    assert ctx["launch_failure"] and ctx["auto_report"] and ctx["error_class"] == "content_timeout"
    assert ctx["game_id"] == DOA2 and ctx["mod"] == MOD and ctx["adapter"] == "retroarch" and ctx["job_id"] == job["id"]
    body = req["body"]
    for part in ("## What failed", "## Error", "## Diagnosis (content_timeout)", "## Automatic remedy", "## Timings",
                 "## Mod and staging", "## Logs", "GDROM not ready", "## Recent jobs", "Fetching mod doa2_roster"):
        assert part in body, part
    names = {a["name"] for a in req["messages"][0]["attachments"]}
    assert {"worker.log", "job-progress.txt", "emulator-log.txt", "launch-failure-evidence.json"} <= names
    evidence = json.loads(p.store.read_artifact(next(a["sha256"] for a in req["messages"][0]["attachments"]
                                                     if a["name"] == "launch-failure-evidence.json")))
    assert evidence["timings"]["queued_s"] == 2.0 and evidence["worker"] == "JAYBUILTFINALE"
    assert evidence["classification"]["cls"] == "content_timeout"
    stamped = p.store.get("job", job["id"])["launch_report"]
    assert stamped["number"] == req["number"] and stamped["text"] == f"Reported as #{req['number']}, being investigated"
    assert p.store.catalog_get(DOA2)["launch_report"]["number"] == req["number"]


def test_repeats_append_an_occurrence_instead_of_a_new_ticket(plane):
    p, ledger = plane
    first = ledger.observe_job(failed_launch(p))
    p.t += 300
    again = ledger.observe_job(failed_launch(p))
    assert again["id"] == first["id"] and again["count"] == 2 and len(again["occurrences"]) == 2
    req = p.store.get("request", first["request_id"])
    assert any(m["text"].startswith("Occurred again (2 times)") for m in req["messages"])
    assert len([r for r in p.store.all("request")]) == 1
    # the same job seen twice (hook + scan) counts once
    assert ledger.observe_job(p.store.get("job", again["occurrences"][-1]["job_id"]))["count"] == 2
    # another error class, another mod or another game: separate tickets
    ledger.observe_job(failed_launch(p, err=BLOCK_ERR))
    ledger.observe_job(failed_launch(p, mod=""))
    assert len(p.store.all("request")) == 3


def test_skips_cancels_intentional_and_agent_launches(plane):
    p, ledger = plane
    skips = [failed_launch(p, err="cancelled by the operator"),
             failed_launch(p, cancel=True),
             failed_launch(p, agent_use=True),
             failed_launch(p, parent_request_id="r1"),
             failed_launch(p, state="succeeded", error=None),
             failed_launch(p, input={"game": {"game_id": DOA2}, "capture_backend": "vulkan"})]
    for job in skips:
        assert ledger.observe_job(job) is None
    assert not p.store.all("request")
    assert ledger.skip_reason(skips[0]) == "cancelled by the operator"
    # a launch that a session swap ran is reported by the swap
    swapped = LF.Ledger(p.store, p.hooks(swap_parent=lambda job: "swap-1"))
    assert swapped.observe_job(failed_launch(p)) is None


def test_a_swap_failure_carries_the_launch_it_ran(plane):
    p, ledger = plane
    p.store.put("session", f"{PC}-s1", {"session_id": f"{PC}-s1", "game_id": DOA2, "title": "Dead or Alive 2",
                                        "adapter": "retroarch", "state": "running", "started": p.t - 900})
    inner = failed_launch(p)
    swap = {"id": "swap-1", "tool": "session_swap", "state": "failed", "error": TIMEOUT_ERR.split(": ", 1)[1],
            "input": {"session_id": f"{PC}-s1", "game_id": DOA2, "mod": MOD, "to": "", "keep_state": True},
            "created": p.t - 41, "started": p.t - 41, "finished": p.t + 1}
    p.store.put("job", "swap-1", swap)
    rec = ledger.observe_job(swap)
    req = p.store.get("request", rec["request_id"])
    assert rec["error_class"] == "content_timeout" and "## Launch jobs the swap ran" in req["body"]
    assert inner["id"] in req["body"] and "## Session" in req["body"]


def test_a_crash_right_after_start_is_a_failure_but_stops_are_not(plane):
    p, ledger = plane
    sess = {"session_id": f"{PC}-abc", "game_id": DOA2, "title": "Dead or Alive 2", "mod": MOD, "adapter": "retroarch",
            "state": "ended", "started": p.t - 12, "ended": p.t}
    assert ledger.observe_session_end(sess, {"returncode": 3221225477}, stop_requested=True) is None
    assert ledger.observe_session_end(sess, {"returncode": 0}) is None
    assert ledger.observe_session_end(sess, {"returncode": 1}) is None
    assert ledger.observe_session_end(sess, {"returncode": 1, "timings": {"kill_s": .1}}) is None
    assert ledger.observe_session_end(sess, {"returncode": 1, "via": "single_game"}) is None
    assert ledger.observe_session_end(sess | {"started": p.t - 600}, {"returncode": 1}) is None
    assert ledger.observe_session_end(sess, {"returncode": 1}, label={"owner": "agent"}) is None
    p.frames[sess["session_id"]] = png()
    rec = ledger.observe_session_end(sess, {"returncode": 3221225477, "log_tail": "[ERROR] vulkan device lost"})
    req = p.store.get("request", rec["request_id"])
    assert rec["error_class"] == "emulator_crash" and "crashed 12 s after starting" in req["title"]
    assert "0xC0000005" in req["title"] and "vulkan device lost" in req["body"]
    assert req["image"] and any(a["name"] == "last-frame.png" for a in req["messages"][0]["attachments"])
    assert ledger.observe_session_end(sess, {"returncode": 3221225477}) is None   # one report per session


def test_the_previous_session_blocker_is_named(plane):
    p, ledger = plane
    p.store.put("session", f"{PC}-mgs", {"session_id": f"{PC}-mgs", "game_id": MGS, "state": "running", "adapter": "dolphin",
                                         "title": "Metal Gear Solid - The Twin Snakes", "started": p.t - 3600})
    rec = ledger.observe_job(failed_launch(p, err=BLOCK_ERR))
    req = p.store.get("request", rec["request_id"])
    assert "## Previous session blocking the launch" in req["body"] and f"{PC}-mgs" in req["body"]
    assert "never stops a running game" in req["body"]
    assert not p.submitted                                         # no automatic remedy for a blocker


# ------------------------------------------------------------------------------------------------ remedies

def test_content_timeout_relaunches_once_with_a_longer_boot_when_the_pc_is_idle(plane):
    p, ledger = plane
    rec = ledger.observe_job(failed_launch(p))
    assert [(t, i.get("boot_timeout_s"), w) for t, i, w, _ in p.submitted] == [("launch_game", 90.0, PC)]
    assert LF.JOB_KIND and p.store.get(LF.JOB_KIND, p.submitted[0][3])["remedy_for"] == rec["id"]
    req = p.store.get("request", rec["request_id"])
    steps = [m["task_step"]["action"] for m in req["messages"] if m.get("task_step")]
    assert "automatic remedy: relaunch" in steps and "automatic remedy: relaunch result" in steps
    assert any("The relaunch worked" in m["text"] for m in req["messages"])
    # the remedy's own launch is not a new failure
    assert ledger.observe_job(p.store.get("job", p.submitted[0][3]) | {"state": "failed", "error": TIMEOUT_ERR}) is None
    # a second failure soon after: no second automatic relaunch
    ledger.observe_job(failed_launch(p))
    assert len(p.submitted) == 1
    assert any("already relaunched automatically" in m["text"] for m in p.store.get("request", rec["request_id"])["messages"])


def test_no_relaunch_over_a_running_game_or_for_old_failures(plane):
    p, ledger = plane
    p.store.put("session", f"{PC}-x", {"session_id": f"{PC}-x", "game_id": MGS, "state": "running", "title": "MGS"})
    rec = ledger.observe_job(failed_launch(p))
    assert not p.submitted
    assert any("a relaunch would close it" in m["text"] for m in p.store.get("request", rec["request_id"])["messages"])
    p.store.delete("session", f"{PC}-x")
    p.t += 1000
    old = failed_launch(p, err=TIMEOUT_ERR.replace("retroarch", "retroarch"), finished=p.t - 900)
    ledger2 = LF.Ledger(p.store, p.hooks())
    ledger2.observe_job(old | {"id": "other"})
    assert not p.submitted


def test_mod_fetch_restages_the_mod_then_relaunches(plane):
    p, ledger = plane
    rec = ledger.observe_job(failed_launch(p, err="RuntimeError: Fetching mod doa2_roster_59d8ed0e from the collection "
                                                  "timed out after 600 s"))
    assert rec["error_class"] == "mod_fetch"
    assert [t for t, *_ in p.submitted] == ["prepare_mod", "launch_game"]
    assert p.submitted[0][1]["mod"] == MOD and p.submitted[0][1]["game"]["game_id"] == DOA2
    assert "boot_timeout_s" not in p.submitted[1][1]


def test_remedies_can_be_switched_off(plane):
    p, ledger = plane
    ledger.set_settings(auto_remedy=False)
    rec = ledger.observe_job(failed_launch(p))
    assert not p.submitted and "switched off" in p.store.get("request", rec["request_id"])["body"]


# ------------------------------------------------------------------------------------------------ investigation

def test_each_new_ticket_is_queued_for_hermes_and_marked_in_progress(plane):
    p, ledger = plane
    rec = ledger.observe_job(failed_launch(p))
    assert len(p.investigations) == 1
    rid, number, task = p.investigations[0]
    assert rid == rec["request_id"] and number == rec["number"]
    for words in ("find the root cause", "fix it in gBox code", "draft PR", "screenshots", "idle node", "in_progress"):
        assert words.lower() in task.lower(), words
    req = p.store.get("request", rid)
    assert req["status"] == "in_progress"
    assert any("Investigation queued in the Hermes work queue at priority 1" in m["text"] for m in req["messages"])
    ledger.observe_job(failed_launch(p))                           # a repeat is not queued again
    assert len(p.investigations) == 1
    p.queue_jobs[rid] = "hermes-job-7"                             # the work queue dispatched it
    ledger.tick()
    assert p.store.get(LF.KIND, rec["id"])["hermes"]["job_id"] == "hermes-job-7"
    assert any("dispatched job hermes-job-7" in m["text"] for m in p.store.get("request", rid)["messages"])


def test_a_direct_dispatch_records_the_job_id_and_a_failure_leaves_the_ticket_open(plane):
    p, _ = plane
    ledger = LF.Ledger(p.store, p.hooks(investigate=lambda rid, n, task, attempt: {"mode": "dispatch", "job_id": "hj1", "priority": 2}))
    rec = ledger.observe_job(failed_launch(p))
    assert p.store.get(LF.KIND, rec["id"])["hermes"]["job_id"] == "hj1"
    assert any("Hermes job hj1" in m["text"] for m in p.store.get("request", rec["request_id"])["messages"])

    def down(*a):
        raise RuntimeError("hermes is not installed here")
    ledger = LF.Ledger(p.store, p.hooks(investigate=down))
    rec = ledger.observe_job(failed_launch(p, err=BLOCK_ERR))
    req = p.store.get("request", rec["request_id"])
    assert req["status"] == "open" and any("could not be queued" in m["text"] for m in req["messages"])


def test_work_queue_prompt_and_sync_know_launch_failures():
    from gbox import hermes_work_queue as Q
    data = {"items": {}, "version": 1}
    req = {"id": "a" * 16, "number": 9, "title": "Launch failed: X", "status": "in_progress", "source": "automation",
           "automated": True, "context": {"launch_failure": True, "auto_report": True, "game_id": DOA2}}
    Q.sync(data, {"items": [], "count": 0}, [req], now=1)
    item = data["items"]["inbox:" + "a" * 16]
    assert item["launch_failure"] and item["repair"] and item["game_id"] == DOA2
    assert Q.priority_rank(item, {"priority": ["a" * 16]}) == 0
    from unittest import mock
    with mock.patch.object(Q.mode, "_handoff", return_value=""):
        prompt = Q._prompt(item)
    assert "launch failure report" in prompt and "draft PR" in prompt and "native character work" not in prompt


# ------------------------------------------------------------------------------------------------ verify and resolve

def merge(p, rid, number=412, sha="abc1234def56"):
    req = p.store.get("request", rid)
    req["messages"].append({"author": "agent", "ts": p.t, "text": f"PR #{number} merged to main as {sha} at 2026-10-13 10:00 UTC."})
    p.store.put("request", rid, req)


def test_merged_and_deployed_fix_is_verified_on_an_idle_node_and_closed_with_the_frame(plane):
    p, ledger = plane
    ledger.set_settings(auto_remedy=False)
    rec = ledger.observe_job(failed_launch(p))
    rid = rec["request_id"]
    assert ledger.tick() == []                                     # nothing merged yet
    p.t += 60
    merge(p, rid)
    assert ledger.tick()[0]["state"] == "merged"
    p.deployed["abc1234def56"] = False                             # merged, not deployed yet
    assert ledger.tick() == []
    p.deployed["abc1234def56"] = True
    assert ledger.tick()[0]["state"] == "awaiting_verify"
    ch = ledger.tick()[0]
    assert ch["state"] == "verifying"
    sig, node, jid = p.verifications[0]
    assert sig == rec["id"] and node == "JAYBUILTFINALE"          # the failing PC, idle and free
    assert ledger.tick() == []                                     # still running
    p.finish_verification(jid, ok=True)
    assert ledger.tick()[0]["verified"] == "verification launch"
    req = p.store.get("request", rid)
    assert req["status"] == "done"
    last = req["messages"][-1] if req["messages"][-1].get("attachments") else req["messages"][-2]
    assert last["attachments"] and last["attachments"][0]["type"] == "image/png"
    assert p.unprioritized == [rid]
    assert p.store.get(LF.KIND, rec["id"])["state"] == "verified"
    assert p.store.catalog_get(DOA2)["launch_report"]["verified"] is True
    assert LF.badge(p.store.catalog_get(DOA2)["launch_report"]) == f"Fixed, verified (#{req['number']})"
    assert ledger.tick() == []


def test_a_busy_node_defers_and_a_failed_verification_reopens_with_the_evidence(plane):
    p, ledger = plane
    ledger.set_settings(auto_remedy=False)
    p.workers_list[0]["idle_seconds"] = 20                         # the operator is at the failing PC
    rec = ledger.observe_job(failed_launch(p))
    merge(p, rec["request_id"])
    p.deployed["abc1234def56"] = True
    ledger.tick(), ledger.tick()
    p.verify_raises = "an evidence capture is already running (job q1); they run one at a time"
    assert ledger.tick()[0]["verify"] == "deferred"
    assert ledger.tick() == []                                     # waits VERIFY_RETRY_S
    p.verify_raises = None
    p.t += LF.VERIFY_RETRY_S + 1
    ledger.tick()
    _sig, node, jid = p.verifications[0]
    assert node == "auto"                                          # never the PC someone is using
    p.finish_verification(jid, ok=False, error="Unsupported: No idle node can run an evidence capture right now: ...")
    assert ledger.tick()[0]["verify"] == "retry"                   # transient: try again later
    p.t += LF.VERIFY_RETRY_S + 1
    ledger.tick()
    jid2 = p.verifications[1][2]
    p.finish_verification(jid2, ok=False, error="Unsupported: no frame was captured on lilspark: launch_game: " + TIMEOUT_ERR)
    assert ledger.tick()[0]["state"] == "reopened"
    req = p.store.get("request", rec["request_id"])
    assert req["status"] == "in_progress"                          # reopened and queued again
    assert any(m["text"].startswith("Verification failed after PR #412") for m in req["messages"])
    assert len(p.investigations) == 2 and p.store.get(LF.KIND, rec["id"])["state"] == "investigating"
    assert p.attempts == [1, 2]                                    # a new Hermes attempt, not the finished job


def test_black_frames_do_not_verify(plane):
    p, ledger = plane
    ledger.set_settings(auto_remedy=False)
    rec = ledger.observe_job(failed_launch(p))
    merge(p, rec["request_id"])
    p.deployed["abc1234def56"] = True
    ledger.tick(), ledger.tick(), ledger.tick()
    p.finish_verification(p.verifications[0][2], ok=True, dark=True)
    assert ledger.tick()[0]["state"] == "reopened"


def test_an_operator_launch_that_keeps_running_counts_as_verification(plane):
    p, ledger = plane
    ledger.set_settings(auto_remedy=False)
    rec = ledger.observe_job(failed_launch(p))
    sid = f"{PC}-ok"
    p.store.put("session", sid, {"session_id": sid, "game_id": DOA2, "mod": MOD, "state": "running", "started": p.t + 5})
    p.store.put("session", f"{PC}-agent", {"session_id": f"{PC}-agent", "game_id": DOA2, "mod": MOD, "state": "running",
                                           "started": p.t + 5})
    p.store.put("slabel", f"{PC}-agent", {"label": "Evidence capture: DOA2", "owner": "agent"})
    p.t += 30
    assert ledger.tick() == []                                     # not long enough yet
    p.t += 60
    p.frames[sid] = png((10, 200, 10))
    assert ledger.tick()[0]["verified"] == "operator launch"
    req = p.store.get("request", rec["request_id"])
    assert req["status"] == "done" and any(sid in m["text"] and "ran 85 s" in m["text"] for m in req["messages"])


def test_the_failure_coming_back_after_a_fix_reopens_the_ticket(plane):
    p, ledger = plane
    ledger.set_settings(auto_remedy=False)
    rec = ledger.observe_job(failed_launch(p))
    ledger.close_verified(rec["id"], "verification launch", "Verified.")
    assert p.store.get("request", rec["request_id"])["status"] == "done"
    p.t += 3600
    again = ledger.observe_job(failed_launch(p))
    assert again["id"] == rec["id"] and again["state"] == "investigating" and again["reopen_count"] == 1
    assert p.store.get("request", rec["request_id"])["status"] == "in_progress"
    assert len(p.investigations) == 2 and p.attempts == [1, 2]
    assert p.store.get(LF.KIND, rec["id"])["hermes"]["attempt"] == 2   # the requeue is kept on the record


# ------------------------------------------------------------------------------------------------ backfill

def test_backfill_files_grouped_tickets_for_the_last_seven_days(plane):
    p, ledger = plane
    for age_days, err in ((1, TIMEOUT_ERR), (2, TIMEOUT_ERR), (3, BLOCK_ERR), (9, TIMEOUT_ERR)):
        failed_launch(p, err=err, created=p.t - age_days * 86400 - 40, finished=p.t - age_days * 86400)
    failed_launch(p, err="cancelled by the operator", finished=p.t - 3600)
    preview = ledger.preview(7)
    assert sorted(g["count"] for g in preview.values()) == [1, 2]
    assert not p.store.all("request")
    out = ledger.backfill(7)
    assert len(out["filed"]) == 2 and out["skipped"] == {"cancelled by the operator": 1}
    timeout = next(r for r in p.store.all(LF.KIND) if r["error_class"] == "content_timeout")
    assert timeout["count"] == 2 and all(o["source"] == "backfill" for o in timeout["occurrences"])
    assert not p.submitted                                         # no relaunch for old failures
    assert len(p.investigations) == 2
    assert ledger.backfill(7)["filed"] == []                       # idempotent


# ------------------------------------------------------------------------------------------------ the server wiring

def test_server_files_the_report_from_a_worker_result_and_the_api_shows_it(cfg, monkeypatch, tmp_path):
    from gbox import hermes_task_mode
    from gbox.server import create_app
    monkeypatch.setenv("GBOX_HERMES_DISPATCH_STATE", str(tmp_path / "dispatch"))
    monkeypatch.setenv("GBOX_HERMES_HOME", str(tmp_path / "hermes"))
    monkeypatch.setattr(hermes_task_mode, "_job", lambda: {"no_agent": True, "enabled": True})
    app = create_app(cfg)
    store = app.state.store
    store.upsert_catalog([{"game_id": DOA2, "title": "Dead or Alive 2", "platform": "dreamcast", "core": "flycast", "format": "gdi", "profile_id": DOA2,
                           "source_paths": ["x"]}])
    client = TestClient(app, headers={"Authorization": f"Bearer {cfg.token()}"})
    client.post("/api/workers/register", json={"id": "jay", "name": "JAYBUILTFINALE", "os": "windows",
                                               "tools": ["launch_game"]}).raise_for_status()
    app.state.launch_ledger.set_settings(auto_remedy=False)
    job = client.post("/api/games/" + DOA2 + "/launch?node=JAYBUILTFINALE&mod=" + MOD, json={}).json()
    claimed = client.post("/api/workers/jay/claim").json()
    assert claimed["id"] == job["id"]
    r = client.post("/api/workers/jay/result", json={"job_id": job["id"], "ok": False, "error": TIMEOUT_ERR,
                                                     "log": ["launch_game started"], "artifacts": []})
    assert r.status_code == 200
    deadline = time.time() + 10
    while not (got := client.get("/api/launch-failures", params={"job_id": job["id"]}).json())["report"] and time.time() < deadline:
        time.sleep(0.1)
    report = got["report"]
    assert report["number"] and report["text"] == f"Reported as #{report['number']}, being investigated"
    while "launch_report" not in client.get(f"/api/jobs/{job['id']}").json() and time.time() < deadline:
        time.sleep(0.1)
    assert client.get(f"/api/jobs/{job['id']}").json()["launch_report"]["number"] == report["number"]
    req = client.get(f"/api/requests/{report['request_id']}").json()
    assert req["context"]["launch_failure"] and req["title"].startswith("Launch failed: Dead or Alive 2 (doa2_roster_59d8ed0e)")
    from gbox import hermes_work_queue
    while not hermes_work_queue.get_priority() and time.time() < deadline:
        time.sleep(0.1)
    assert hermes_work_queue.get_priority()[0] == report["request_id"]   # first in the Hermes queue's priority list
    while client.get(f"/api/requests/{report['request_id']}").json()["status"] != "in_progress" and time.time() < deadline:
        time.sleep(0.1)
    req = client.get(f"/api/requests/{report['request_id']}").json()
    assert any("Hermes work queue at priority 1" in m["text"] for m in req["messages"])
    # no second "Auto report: launch_game failed" mod ticket; the app's own auto report lands on the same ticket
    same = client.post("/api/requests/auto-mod-failure", json={"job_id": job["id"], "detail": "Could not open the mod"}).json()
    assert same["id"] == report["request_id"]
    assert [x["id"] for x in client.get("/api/requests").json()] == [report["request_id"]]
    listing = client.get("/api/launch-failures").json()
    assert listing["items"][0]["number"] == report["number"] and listing["settings"]["auto_remedy"] is False
    assert client.post("/api/launch-failures/backfill", json={"days": 7, "dry_run": True}).json()["groups"] == {}
    assert client.post("/api/launch-failures/backfill", json={"days": 7}).json()["filed"] == []


def test_mods_gallery_entries_carry_the_launch_report(plane):
    p, ledger = plane
    from gbox import built_mods
    rec = ledger.observe_job(failed_launch(p))
    reports = LF.index(p.store)
    entry = built_mods.entry({"game_id": DOA2, "name": MOD, "meta": {"title": "DOA2 roster"}}, None, None,
                             p.store.catalog_get(DOA2), {}, None, launch_report=reports.get((DOA2, MOD)))
    assert entry["launch_report"]["number"] == rec["number"]
    assert any(t["number"] == rec["number"] for t in entry["tickets"])


def test_a_failed_launch_on_the_worker_leaves_its_evidence(monkeypatch):
    from gbox import tools

    class Ad:
        name = "retroarch"

        def log_tail(self, n):
            return "[WARN] GDROM not ready"

    def launch(inp, ctx):
        d = tools._LAUNCH_DIAG.d
        d.update(_adapter=Ad(), adapter="retroarch", stage="start the emulator", staged_mod=MOD)
        d.setdefault("timings", {})["mod_s"] = 4.2
        raise RuntimeError("retroarch started but content not running after 30s")

    class Ctx:
        def __init__(self):
            self.artifacts = []

        def artifact(self, name, data, media, **prov):
            self.artifacts.append((name, data, media))
    monkeypatch.setattr(tools, "_launch_game", launch)
    inp = tools.LaunchIn(game={"game_id": DOA2, "title": "Dead or Alive 2", "platform": "dreamcast", "format": "gdi",
                               "profile_id": DOA2, "source_paths": ["x"]}, mod=MOD, boot_timeout_s=90)
    ctx = Ctx()
    with pytest.raises(RuntimeError):
        tools.launch_game(inp, ctx)
    got = {n: d for n, d, _m in ctx.artifacts}
    info = json.loads(got["launch-failure.json"])
    assert info["adapter"] == "retroarch" and info["stage"] == "start the emulator" and info["staged_mod"] == MOD
    assert info["timings"] == {"mod_s": 4.2} and info["boot_timeout_s"] == 90 and "_adapter" not in info
    assert got["emulator-log.txt"] == b"[WARN] GDROM not ready"
    assert tools._LAUNCH_DIAG.d is None
