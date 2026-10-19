"""PR evidence (docs/pr-evidence.md): evidence_capture drives its own agent test session on an idle node, reaches
gameplay from the recipe (moment + inputs), grabs frames, optionally the stock game for a before/after pair, and
always stops its own session - never touching the operator's. Fake control plane, no emulator."""
import io
import json
import time

import pytest
from fastapi.testclient import TestClient

from gbox import evidence_capture as EC
from gbox import evidence_render as ER

SHA = "a" * 64


def png(colour=(200, 40, 40), size=(64, 48)) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", size, colour).save(buf, "PNG")
    return buf.getvalue()


def worker(wid, name, os_="windows", idle=900.0, **o):
    return {"id": wid, "name": name, "os": os_, "online": True, "background_testing": True, "idle_seconds": idle,
            "tools": ["launch_game", "get_frame", "session_op", "state_transfer", "scene_capture", "zelda_oot"]} | o


class Jobs:
    """Records every job; answers like the workers would. Frames are real PNGs kept in self.arts."""

    def __init__(self, fail=None):
        self.calls, self.fail, self.arts, self.n = [], fail or {}, {}, 0

    def __call__(self, tool, inp, worker_id, wait, progress=None):
        self.calls.append((tool, json.loads(json.dumps(inp)), worker_id))
        op = inp.get("op")
        if (tool, op) in self.fail or (tool, None) in self.fail:
            raise RuntimeError(f"{tool} {op}: boom")
        if tool == "launch_game":
            self.n += 1
            return {"session_id": f"{worker_id}-ev{self.n}", "adapter": "retroarch"}
        if tool == "get_frame":
            data = png((40 * self.n % 255, 120, 200))
            sha = f"{len(self.arts):064x}"
            self.arts[sha] = data
            return {"sha256": sha, "width": 64, "height": 48, "mean_luma": 90.0}
        if tool == "state_transfer":
            return {"result": {"load_requested": True, "load_verified": True}}
        return {"result": {}}

    def tools(self):
        return [(t, i.get("op")) for t, i, _w in self.calls]

    def stops(self):
        return [i["session_id"] for t, i, _w in self.calls if t == "session_op" and i.get("op") == "stop_game"]


RECIPES = {
    "g1": {"status": "unverified", "title": "Game One", "boot_s": 1,
           "moment": {"kind": "artifact", "artifact": SHA, "label": "title"},
           "after_moment": [{"press": ["start"], "wait_s": 1, "label": "title"},
                            {"press": ["a"], "wait_s": 1, "label": "select", "shot": "select screen"}],
           "steps": [{"press": ["start"], "wait_s": 1}],
           "shots": [{"label": "fight", "at_s": 3}, {"label": "after title", "after_inputs": 0}],
           "variants": {"boot": {"moment": None, "shots": [{"label": "boot shot", "at_s": 1}]}}},
}


def capture(jobs, ws, live=(), inp=None, **kw):
    labels, ended, arts = {}, [], {}

    def put_artifact(data, name, media, prov):
        sha = f"{9000 + len(arts):064x}"
        arts[sha] = data
        return sha
    out = EC.run(EC.EvidenceIn.model_validate(inp or {"game_id": "g1", "mod": "m1"}), {"game_id": "g1", "title": "Game One"},
                 run_job=jobs, workers=lambda: ws, live_sessions=lambda: list(live), recipes=RECIPES,
                 label=lambda s, l: labels.update({s: l}), end_session=ended.append, put_artifact=put_artifact,
                 read_artifact=lambda sha: jobs.arts.get(sha) or arts.get(sha), sleep=lambda s: None, **kw)
    return out, labels, ended, arts


# ------------------------------------------------------------------------------------------------ the node

def test_never_on_a_node_with_the_operators_game_and_prefers_an_idle_windows_pc():
    ws = [worker("op", "i9-NUC"), worker("test", "JAYBUILTFINALE", idle=1200), worker("spark", "lilspark", "linux", None)]
    live = [{"session_id": "op-s1", "state": "running", "title": "DOA2"}]
    assert EC.pick_node("auto", ws, live, needs={"launch_game"})["name"] == "JAYBUILTFINALE"
    with pytest.raises(EC.EvidenceError, match="running DOA2"):
        EC.pick_node("i9-NUC", ws, live, needs={"launch_game"})


def test_busy_unticked_or_recently_used_pcs_fall_back_to_the_spark():
    ws = [worker("a", "A", idle=20), worker("b", "B", background_testing=False), worker("c", "C"),
          worker("spark", "lilspark", "linux", None)]
    w = EC.pick_node("auto", ws, [], needs={"launch_game"}, running_jobs={"c": 2})
    assert w["name"] == "lilspark"
    with pytest.raises(EC.EvidenceError) as e:
        EC.pick_node("auto", ws, [{"session_id": "spark-x", "state": "running"}], needs={"launch_game"},
                     running_jobs={"c": 2})
    msg = str(e.value)
    assert "used 20 s ago" in msg and "unticked" in msg and "busy with 2 job" in msg and "lilspark is running" in msg


def test_agent_sessions_block_the_node_too_and_missing_tools_are_named():
    ws = [worker("a", "A", tools=["launch_game"])]
    with pytest.raises(EC.EvidenceError, match="can't run get_frame"):
        EC.pick_node("auto", ws, [], needs={"launch_game", "get_frame"})
    with pytest.raises(EC.EvidenceError, match="running"):
        EC.pick_node("A", [worker("a", "A")], [{"session_id": "a-agent", "state": "running"}], needs={"launch_game"})


def test_required_os_pins_windows_only_platforms():
    assert EC.required_os({"platform": "xbox"}) == "windows"
    assert EC.required_os({"platform": "ps3"}) == "windows"
    assert EC.required_os({"platform": "xbox360"}) == "windows"
    assert EC.required_os({"platform": "switch"}) == "windows"
    assert EC.required_os({"launch": {"kind": "savemgo_bundle"}}) == "windows"
    assert EC.required_os({"platform": "gamecube"}) is None
    assert EC.required_os({}) is None


def test_windows_only_game_never_falls_back_to_a_linux_worker():
    # Every Windows PC is refused; the Spark (linux) can't run cxbx, so the capture
    # must refuse instead of silently launching an Xbox game on Linux.
    ws = [worker("op", "i9-NUC", idle=20), worker("spark", "lilspark", "linux", None)]
    with pytest.raises(EC.EvidenceError, match="was used 20 s ago"):
        EC.pick_node("auto", ws, [], needs={"launch_game"}, required_os="windows")


def test_required_os_refuses_an_explicit_linux_worker_name():
    ws = [worker("spark", "lilspark", "linux", None)]
    with pytest.raises(EC.EvidenceError, match="needs a windows worker"):
        EC.pick_node("lilspark", ws, [], needs={"launch_game"}, required_os="windows")


def test_windows_only_game_uses_the_idle_windows_pc():
    ws = [worker("op", "i9-NUC"), worker("test", "JAYBUILTFINALE", idle=1200),
          worker("spark", "lilspark", "linux", None)]
    live = [{"session_id": "op-s1", "state": "running", "title": "DOA2"}]
    assert EC.pick_node("auto", ws, live, needs={"launch_game"}, required_os="windows")["name"] == "JAYBUILTFINALE"


# ------------------------------------------------------------------------------------------------ the capture

def test_mod_and_stock_runs_reach_gameplay_shoot_and_stop_only_their_own_sessions():
    jobs = Jobs()
    live = [{"session_id": "op-s1", "state": "running", "title": "DOA2"}]
    out, labels, ended, arts = capture(jobs, [worker("op", "i9-NUC"), worker("t", "JAY")], live,
                                       {"game_id": "g1", "mod": "m1", "compare_stock": True})
    assert out["worker"] == "JAY" and [r["variant"] for r in out["runs"]] == ["mod", "stock"]
    assert all(w == "t" for _t, _i, w in jobs.calls)                         # nothing on the operator's PC
    launches = [i for t, i, _w in jobs.calls if t == "launch_game"]
    assert [l["mod"] for l in launches] == ["m1", ""]
    assert sorted(jobs.stops()) == ["t-ev1", "t-ev2"] and "op-s1" not in jobs.stops()
    assert sorted(ended) == ["t-ev1", "t-ev2"]
    assert all(l["owner"] == "agent" and l["label"].startswith("Evidence capture") for l in labels.values())
    imports = [i for t, i, _w in jobs.calls if t == "state_transfer"]
    assert [i["op"] for i in imports] == ["import", "import"] and imports[0]["artifact"] == SHA
    presses = [e for t, i, _w in jobs.calls if t == "session_op" and i["op"] == "send_input" for e in i["args"]["events"]]
    assert presses[:2] == [{"key": "start", "down": True}, {"key": "start", "down": False}]
    labs = [f["label"] for f in out["frames"] if f["run"] == "mod"]
    assert labs == ["after title", "select screen", "fight"]
    assert all(f["kind"] == "session screenshot" and f["gameplay_verified"] is False for f in out["frames"])
    assert all(p["kind"] == "session screenshot" and p["gameplay_verified"] is False for p in out["pairs"])
    assert {p["label"] for p in out["pairs"]} == {"after title", "select screen", "fight"}
    pair = arts[out["pairs"][0]["composite"]]
    assert pair[:8] == b"\x89PNG\r\n\x1a\n"
    assert set(out["artifacts"]) >= {f["sha256"] for f in out["frames"]} | {p["composite"] for p in out["pairs"]}


def test_the_session_is_stopped_when_a_step_fails_and_the_error_is_reported():
    jobs = Jobs(fail={("session_op", "send_input"): True})
    with pytest.raises(EC.EvidenceError, match="no frame"):
        capture(jobs, [worker("t", "JAY")])
    assert jobs.stops() == ["t-ev1"]


def test_frames_taken_before_a_failure_are_kept():
    jobs = Jobs(fail={("state_transfer", "import"): True})
    out, *_ = capture(jobs, [worker("t", "JAY")], inp={"game_id": "g1", "mod": "m1", "load_moment": "none",
                                                         "inputs": [{"press": ["a"], "shot": "boot a"}]})
    assert [f["label"] for f in out["frames"]][:1] == ["boot a"] and jobs.stops() == ["t-ev1"]
    assert not any(t == "state_transfer" for t, _o in jobs.tools())


def test_yields_when_someone_starts_using_the_node():
    jobs, calls = Jobs(), {"n": 0}

    def active(w):
        calls["n"] += 1
        return "someone is using JAY (input 3 s ago)" if calls["n"] > 3 else None
    with pytest.raises(EC.Yielded, match="someone is using JAY"):
        capture(jobs, [worker("t", "JAY")], inp={"game_id": "g1", "mod": "m1", "compare_stock": True},
                operator_active=active)
    assert jobs.stops() == ["t-ev1"]                                          # stock run never started
    assert sum(1 for t, _o in jobs.tools() if t == "launch_game") == 1


def test_step_tools_are_limited_and_session_scoped():
    jobs = Jobs()
    out, *_ = capture(jobs, [worker("t", "JAY")], inp={
        "game_id": "g1", "mod": "m1", "load_moment": {"artifact": SHA},
        "inputs": [{"tool": "zelda_oot", "input": {"op": "goto", "place": "kakariko"}, "wait_s": 1, "shot": "kak"}]})
    goto = next(i for t, i, _w in jobs.calls if t == "zelda_oot")
    assert goto == {"op": "goto", "place": "kakariko", "session_id": "t-ev1"}
    with pytest.raises(EC.EvidenceError, match="not allowed"):
        capture(Jobs(), [worker("t", "JAY")], inp={"game_id": "g1", "inputs": [{"tool": "write_memory",
                                                                                 "input": {"op": "x"}}]})
    with pytest.raises(EC.EvidenceError, match="not allowed"):
        capture(Jobs(), [worker("t", "JAY")], inp={"game_id": "g1", "inputs": [{"tool": "session_op",
                                                                                 "input": {"op": "stop_game"}}]})


def test_a_slot_moment_runs_on_the_node_that_saved_it():
    jobs = Jobs()
    ws = [worker("a", "A", idle=5000), worker("jay", "JAYBUILTFINALE", idle=400)]
    card = {"title": "mission failed", "state_slot": 21, "session_id": "old-1", "worker": "JAYBUILTFINALE"}
    out, *_ = capture(jobs, ws, inp={"game_id": "g1", "mod": "m1", "load_moment": {"mod_card": "c1"}},
                      mod_card=lambda cid: card if cid == "c1" else None)
    assert out["worker"] == "JAYBUILTFINALE"
    load = next(i for t, i, _w in jobs.calls if t == "session_op" and i["op"] == "load_state")
    assert load["args"] == {"slot": 21}


def test_boot_variant_and_default_shot():
    jobs = Jobs()
    out, *_ = capture(jobs, [worker("t", "JAY")], inp={"game_id": "g1", "recipe": "boot"})
    assert [f["label"] for f in out["frames"]] == ["boot shot"]
    assert not any(t == "state_transfer" for t, _o in jobs.tools())
    out, *_ = capture(Jobs(), [worker("t", "JAY")], inp={"game_id": "unknown", "inputs": []})
    assert [f["label"] for f in out["frames"]] == ["gameplay"] and out["notes"]


def test_dark_frames_are_flagged():
    class Dark(Jobs):
        def __call__(self, tool, inp, worker_id, wait, progress=None):
            r = super().__call__(tool, inp, worker_id, wait, progress)
            return r | {"mean_luma": 1.0} if tool == "get_frame" else r
    out, *_ = capture(Dark(), [worker("t", "JAY")], inp={"game_id": "g1", "recipe": "boot"})
    assert out["frames"][0]["dark"] and any("black" in n for n in out["runs"][0]["notes"])


# ------------------------------------------------------------------------------------------------ recipes

def test_seed_recipes_load_and_cover_the_requested_games():
    r = EC.load_recipes()
    for gid in ("1de2e7634f3161ff", "bc02bb68790ce2e7", "afd2fc507bb69843", "ba32927ecc104b9a", "446e8e442d726e31",
                "b7aecee966090bfa"):
        assert gid in r, gid
        assert r[gid]["status"] in ("ready", "unverified", "needs_state", "todo")
        assert r[gid].get("shows")
        if r[gid]["status"] in ("needs_state", "todo"):
            assert "POST /api/evidence/moments" in r[gid]["todo"]
    assert EC.recipe_for("afd2fc507bb69843", "mission_failed", r)["moment"]["kind"] == "mod_card"
    assert EC.recipe_for("afd2fc507bb69843", "ninja", r)["status"] == "needs_state"
    with pytest.raises(EC.EvidenceError, match="no variant"):
        EC.recipe_for("afd2fc507bb69843", "nope", r)


def test_auf_recipe_reaches_the_first_mission_cut_scene_and_the_bots():
    """007 Agent Under Fire (#1776 cast builds): the boot path ends on Start Mission, every cut scene shot is timed
    after it (a press during the cut scene would skip it), and the bots variant starts a Combat Training match."""
    r = EC.load_recipes()
    auf = EC.recipe_for("65b7187589166b26", "", r)
    assert auf["status"] in ("ready", "unverified") and auf["adapter"] == "dolphin" and auf["boot_s"] == 25
    assert auf.get("moment") is None and auf["steps"][-1]["label"].startswith("start mission")
    assert [s["press"] for s in auf["steps"]][-4:] == [["a"]] * 4             # select mission, briefing, setup, start
    cut = [s for s in auf["shots"] if s["label"].startswith("cut scene")]
    assert len(cut) >= 5 and all(s.get("at_s") is not None for s in auf["shots"])
    assert any("guard" in s["label"] for s in cut) and any("Bond" in s["label"] for s in cut)
    bots = EC.recipe_for("65b7187589166b26", "bots", r)
    labels = [s.get("label", "") for s in bots["steps"]]
    assert "to Multiplayer" in labels and "start game" in labels and labels.index("to Bots") < labels.index("start game")
    assert bots["shots"] and "variants" not in bots

def test_recipe_checks_and_recorded_moments(tmp_path):
    bad = {"games": {"x": {"status": "ready", "moment": {"kind": "artifact", "artifact": "short"},
                           "steps": [{"tool": "poke", "input": {"op": "x"}}], "shots": [{"at_s": 1}]}}}
    f = tmp_path / "r.json"
    f.write_text(json.dumps(bad))
    with pytest.raises(ValueError) as e:
        EC.load_recipes(f)
    assert "sha256" in str(e.value) and "poke" in str(e.value) and "shots[0]" in str(e.value)
    rec = EC.recipe_for("g1", "", RECIPES, {"artifact": "b" * 64, "label": "dock", "after_moment": [{"press": ["a"]}]})
    assert rec["moment"] == {"kind": "artifact", "artifact": "b" * 64, "label": "dock", "recorded": True}
    assert rec["after_moment"] == [{"press": ["a"]}]
    assert EC.resolve_moment("none") is None and EC.resolve_moment({"kind": "none"}) is None
    with pytest.raises(EC.EvidenceError):
        EC.resolve_moment({"mod_card": "c"}, mod_card=lambda c: {"state_slot": None})


# ------------------------------------------------------------------------------------------------ the server

def test_server_runs_it_as_one_in_server_job_at_a_time(tmp_path, monkeypatch):
    from gbox.config import Config
    from gbox.server import create_app
    cfg = Config(data_dir=tmp_path)
    app = create_app(cfg)
    store = app.state.store
    monkeypatch.setattr(store, "catalog_get", lambda gid: {"game_id": gid, "title": "Game One"} if gid == "g1" else None)
    gate, seen = {"go": False}, {}

    def fake_run(inp, game, **kw):
        seen.update(game=game, mod=inp.mod, recorded=kw["recorded"])
        while not gate["go"]:
            time.sleep(0.01)
        kw["say"](50, "capturing")
        return {"game_id": inp.game_id, "mod": inp.mod, "recipe": "default", "worker": "JAY", "runs": [],
                "frames": [{"label": "fight", "sha256": SHA, "kind": "in-game frame"}], "pairs": [], "artifacts": [SHA],
                "notes": []}
    monkeypatch.setattr(EC, "run", fake_run)
    with TestClient(app, headers={"Authorization": "Bearer " + cfg.token()}) as client:
        r = client.post("/api/jobs", json={"tool": "evidence_capture", "input": {"game_id": "g1", "mod": "m1"}})
        assert r.status_code == 200, r.text
        job = r.json()
        assert job["tool"] == "evidence_capture" and job["state"] == "running"
        again = client.post("/api/jobs", json={"tool": "evidence_capture", "input": {"game_id": "g1"}})
        assert again.status_code == 409 and "one at a time" in again.text
        assert client.post("/api/jobs", json={"tool": "evidence_capture", "input": {"game_id": "zz"}}).status_code == 404
        gate["go"] = True
        for _ in range(200):
            j = client.get(f"/api/jobs/{job['id']}").json()
            if j["state"] not in ("queued", "running"):
                break
            time.sleep(0.02)
        assert j["state"] == "succeeded" and j["output"]["frames"][0]["sha256"] == SHA
        assert seen["mod"] == "m1" and seen["recorded"] is None
        ev = client.get("/api/evidence?game_id=g1").json()
        assert ev and ev[0]["frames"][0]["label"] == "fight"
        recipes = client.get("/api/evidence/recipes").json()
        assert "afd2fc507bb69843" in recipes and recipes["afd2fc507bb69843"]["recorded"] == {}


# ------------------------------------------------------------------------------------------------ pictures

def test_before_after_composite_is_a_labelled_png():
    data = ER.before_after(png((10, 10, 10)), png((250, 250, 250), (80, 60)), "caption " * 30, kind="in-game frame")
    from PIL import Image
    im = Image.open(io.BytesIO(data))
    assert im.format == "PNG" and im.height > 420 and im.width > 2 * 420 * 64 // 48
    with pytest.raises(ValueError):
        ER.compose([(png(), "x")], kind="screenshot of something")


def test_kmd_and_prims_render_offline(tmp_path):
    from gbox import mgs_kmd
    obj = mgs_kmd.KmdObject(flags=0, pos=(0, 0, 0), parent=-1, unknown=0,
                            vertices=[(0, 0, 0, -1), (100, 0, 0, -1), (0, 200, 0, -1), (100, 200, 0, -1)],
                            normals=[(0, 0, 4096, 0)], faces=[(0, 1, 2, 3)], face_normals=[(0, 0, 0, 0)],
                            uvs=[bytes(8)], textures=[0])
    child = mgs_kmd.KmdObject(flags=0, pos=(0, 200, 0), parent=0, unknown=0,
                              vertices=[(0, 0, 0, -1), (100, 0, 0, -1), (0, 100, 0, -1), (100, 100, 0, -1)],
                              normals=[(0, 0, 4096, 0)], faces=[(0, 1, 2, 3)], face_normals=[(0, 0, 0, 0)],
                              uvs=[bytes(8)], textures=[0])
    data = mgs_kmd.dumps(mgs_kmd.Kmd(bones=2, bbox=(0,) * 6, objects=[obj, child]), recompute_bbox=True)
    prims = ER.kmd_prims(data)
    assert len(prims) == 2 and prims[1]["pos"][:, 1].min() == 200 and len(prims[0]["tris"]) == 2
    glb = ER.prims_glb(prims, tmp_path / "m.glb")
    out = ER.render_model(glb, tmp_path / "m.png", size=96)
    from gbox.characters import check_preview
    assert check_preview(out)["coverage"] > 0.02


def test_required_os_does_not_redirect_an_explicit_linux_selection():
    ws = [worker("test", "TestPC", idle=1200), worker("spark", "lilspark", "linux", None)]
    with pytest.raises(EC.EvidenceError, match="needs a windows worker"):
        EC.pick_node("linux", ws, [], needs={"launch_game"}, required_os="windows")


@pytest.mark.parametrize("source,occlusion,covered", [(None,"unknown",0),
    ("cxbx-print-window","occluded",3),("cxbx-print-window","sampled-clear",0)])
def test_bright_diagnostic_capture_keeps_provenance_without_gameplay_claim(source,occlusion,covered):
    jobs=Jobs()
    def diagnostic(tool,inp,worker_id,wait,progress=None):
        out=jobs(tool,inp,worker_id,wait,progress)
        if tool=='get_frame':out.update(capture_source=source,capture_occlusion=occlusion,covered=covered)
        return out
    out,*_=capture(diagnostic,[worker('t','Test')])
    assert out['frames'] and all(f['mean_luma']>3 for f in out['frames'])
    for f in out['frames']:
        assert (f['capture_source'],f['capture_occlusion'],f['covered'])==(source,occlusion,covered)
        assert f['kind']=='session screenshot' and f['gameplay_verified'] is False
    assert all(r['gameplay_verified'] is False for r in out['runs'])
    assert any('do not verify gameplay' in n for r in out['runs'] for n in r['notes'])
