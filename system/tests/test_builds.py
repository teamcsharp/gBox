"""Builds view (gbox/builds.py): every custom build (the Spark's collection + each PC's own builds, staged copies
deduped), kinds and filters, display names (store only: folders and markers untouched, shown on the Mods page and in
Special builds too), per-build details (modifications, characters with the 360 viewer models, codes, compile changes,
recipe, jobs / receipts, verification), the build record the shared build paths write, and the scheduled build jobs
(categories, ETA, edit = cancel + resubmit, investigate). A fake cache + store only: nothing is built or launched."""
import json
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from gbox import build_record as R
from gbox import builds as B
from gbox.config import Config
from gbox.server import create_app

GID, OTHER = "g1", "g2"


def mk(cache, gid, name, meta, files=None):
    d = cache / "mods" / gid / name
    d.mkdir(parents=True)
    (d / ".gbox-mod.json").write_text(json.dumps({"name": name, "game_id": gid, **meta}))
    for rel, data in (files or {}).items():
        (d / rel).parent.mkdir(parents=True, exist_ok=True)
        (d / rel).write_bytes(data)
    return d


def character(lib, slug, name, gid, model=True, targets=None, aliases=()):
    d = lib / slug
    d.mkdir(parents=True)
    meta = {"slug": slug, "name": name, "source": {"game_id": gid, "game_title": gid.upper()},
            "model": f"{slug}.glb" if model else "", "aliases": list(aliases)}
    (d / "meta.json").write_text(json.dumps(meta))
    (d / "preview.png").write_bytes(b"\x89PNG")
    if model:
        (d / f"{slug}.glb").write_bytes(b"glTF")
    for t in targets or []:
        (d / "targets").mkdir(exist_ok=True)
        (d / "targets" / t).write_bytes(b"glTF")
    return meta


def fixture(tmp_path):
    cache = tmp_path / "cache"
    cfg = Config(data_dir=tmp_path / "data", cache_dir=cache)
    lib = cache / "characters"
    character(lib, "kane", "Kane", "nomercy", targets=["g1_agent.glb", "g1_neo.glb", "sm64_mario.gltf"])
    character(lib, "rock", "The Rock", "nomercy", targets=["zz_smith.glb"])      # fitted for another game: not shown
    character(lib, "g1_neo", "Neo", GID, aliases=["the one"])
    character(lib, "g1_smith", "Agent Smith", GID)
    mk(cache, GID, "cast_g1_wrestlers", {
        "built": 3000.0, "writer": "gbox.etm_swap", "cast_source": "Wrestlers", "cast_mapping": "by_role", "job_id": "jcast",
        "title": "G1: cast as Wrestlers", "image": "game.iso",
        "cast": [{"slot": "neo", "character": "kane", "status": "built"},
                 {"slot": "agent:smith", "character": "rock", "status": "failed", "reason": "too many bones"}],
        "slots": [{"slot": "agent:smith", "slot_name": "Agent Smith", "donor": "rock", "donor_name": "The Rock"}],
        "recipe": {"tool": "characters", "input": {"op": "cast_swap", "target_game": GID, "source": "wrestlers"},
                   "recorded": 2999.0}}, {"game.iso": b"x" * 2048})
    mk(cache, GID, "g1_patch", {"built": 2000.0, "files": ["data/a.bin", "data/new.bin (new)",
                                                          "@image: Mario model (gbox.sm64_writer)"],
                                "image": "game.z64", "cheats": ["8001234 0063"],
                                "compiler_flags": "-O2 -g", "source_patches": [{"path": "src/mario.c", "lines": 12}]},
       {"data/a.bin": b"abc", "game.z64": b"z" * 100})
    mk(cache, GID, "g1_hack", {"built": 1500.0, "file_changes": [
        {"path": "EBOOT.BIN", "change": "patched", "size": 10, "base_size": 10, "patches": [{"offset": 16, "length": 2}]}]})
    mk(cache, GID, "showcase_sonic_g1", {"built": 4000.0, "showcase": {"source": "Sonic"}, "character": "kane"})
    mk(cache, OTHER, "g2_hucast", {"built": 1000.0, "character": "kane", "slot": "player"})
    mk(cache, GID, "g1_patch~abc123", {"built": 2001.0})                      # a staging copy: never its own build
    app = create_app(cfg)
    store = app.state.store
    store.put("mod", "card1", {"id": "card1", "title": "Patch card", "game_id": GID, "state_slot": 2, "requests": [7],
                               "calls": [{"tool": "@launch", "input": {"mod": "g1_patch"}},
                                         {"tool": "write_memory", "input": {"address": "0x8001234", "value": 99}},
                                         {"tool": "cheats", "input": {"codes": ["ABCD-1234"], "desc": "inf health"}}],
                               "ts": 10})
    store.put("request", "r7", {"id": "r7", "number": 7, "title": "Patch it", "status": "done"})
    now = time.time()
    store.put("worker", "w1", {"id": "w1", "name": "i9-NUC", "os": "windows", "last_seen": now, "tools": ["characters"],
                               "local_builds": [{"game_id": GID, "name": "g1_patch", "built": 2000.0},
                                                {"game_id": GID, "name": "cast_g1_wrestlers~9f", "built": 3001.0,
                                                 "staged_of": "cast_g1_wrestlers"},
                                                {"game_id": GID, "name": "g1_local_only", "built": 5000.0}]})
    store.put("worker", "w2", {"id": "w2", "name": "spark", "os": "linux", "last_seen": now, "tools": ["characters"],
                               "local_builds": [{"game_id": GID, "name": "ignored_spark_entry", "built": 1.0}]})
    return cfg, app, store, {"Authorization": f"Bearer {cfg.token()}"}


def get(c, h, path, code=200):
    r = c.get(path, headers=h)
    assert r.status_code == code, r.text
    return r.json()


def by_name(rows):
    return {r["name"]: r for r in rows}


def test_list_every_build_newest_first_with_kinds_where_and_launch(tmp_path):
    cfg, app, store, h = fixture(tmp_path)
    with TestClient(app) as c:
        assert app.state.built_mods.wait(10)
        r = get(c, h, "/api/builds")
        ws = get(c, h, "/api/workers")
    names = [x["name"] for x in r["items"]]
    assert names == ["g1_local_only", "showcase_sonic_g1", "cast_g1_wrestlers", "g1_patch", "g1_hack", "g2_hucast"]
    assert "g1_patch~abc123" not in names and "ignored_spark_entry" not in names, "staged copies / Spark heartbeat"
    b = by_name(r["items"])
    assert b["cast_g1_wrestlers"]["kind"] == "cast" and b["cast_g1_wrestlers"]["slots"] == 2
    assert b["showcase_sonic_g1"]["kinds"][0] == "showcase"
    assert b["g1_hack"]["kind"] == "romhack"
    assert b["g1_patch"]["kinds"] == ["compile", "cheats", "test"], "compiler flags + cheats + a ticket on its card"
    assert b["g2_hucast"]["kind"] == "character"
    # where it lives: the Spark collection, plus a PC's local / staged copy
    assert [w["label"] for w in b["g1_patch"]["where"]] == ["Spark collection", "i9-NUC (local copy)"]
    assert [w["label"] for w in b["cast_g1_wrestlers"]["where"]] == ["Spark collection", "i9-NUC (staged copy)"]
    lo = b["g1_local_only"]
    assert lo["local_only"] and [w["label"] for w in lo["where"]] == ["i9-NUC (local only)"]
    assert [o["id"] for o in lo["launch_options"]] == ["pc:i9-NUC"], "a PC-only build launches on that PC"
    opts = b["g1_patch"]["launch_options"]
    assert opts[0]["id"] == "here" and opts[0]["default"] and "mod=g1_patch" in opts[0]["call"]["path"]
    assert any(o["id"] == "moment" for o in opts), "the card's saved moment"
    assert b["g1_patch"]["image"] == "" and b["cast_g1_wrestlers"]["image"].startswith("/api/characters/")
    assert {g["game_id"]: g["count"] for g in r["games"]} == {GID: 5, OTHER: 1}
    assert [k["kind"] for k in r["kinds"]][:3] == ["showcase", "cast", "character"]
    assert all("local_builds" not in w for w in ws), "the workers list stays light"


@pytest.mark.parametrize("query,want", [("kind=cast", ["cast_g1_wrestlers"]),
                                        ("kind=cheats", ["g1_patch"]),
                                        ("game_id=g2", ["g2_hucast"]),
                                        ("q=rock", ["cast_g1_wrestlers"]),
                                        ("q=decomp", ["g1_patch"]),
                                        ("q=%237", ["g1_patch"])])
def test_list_filters(tmp_path, query, want):
    cfg, app, store, h = fixture(tmp_path)
    with TestClient(app) as c:
        assert app.state.built_mods.wait(10)
        assert [x["name"] for x in get(c, h, "/api/builds?" + query)["items"]] == want


def test_rename_is_a_display_name_shown_everywhere_and_never_touches_the_folder(tmp_path):
    cfg, app, store, h = fixture(tmp_path)
    marker = cfg.cache / "mods" / GID / "g1_patch" / ".gbox-mod.json"
    before = marker.read_bytes()
    with TestClient(app) as c:
        assert app.state.built_mods.wait(10)
        r = c.patch(f"/api/builds/{GID}/g1_patch", json={"display_name": "  My\tfavourite patch  "}, headers=h)
        assert r.status_code == 200, r.text
        assert r.json() == {"key": "g1/g1_patch", "display_name": "My favourite patch", "label": "My favourite patch"}
        row = by_name(get(c, h, "/api/builds")["items"])["g1_patch"]
        assert row["label"] == "My favourite patch" and row["original_title"] == "Patch card"
        assert [x["name"] for x in get(c, h, "/api/builds?q=favourite")["items"]] == ["g1_patch"]
        mods = by_name(get(c, h, "/api/mods/built")["items"])
        assert mods["g1_patch"]["mod_title"] == "My favourite patch" and mods["g1_patch"]["display_name"]
        special = get(c, h, f"/api/games/{GID}/special_builds")
        sb = {b["name"]: b for g in special["groups"] for b in g["builds"]}
        assert sb["g1_patch"]["mod_title"] == "My favourite patch"
        assert get(c, h, f"/api/builds/{GID}/g1_patch/details")["label"] == "My favourite patch"
        # a PC-only build can be named too; too long / unknown builds are refused
        assert c.patch(f"/api/builds/{GID}/g1_local_only", json={"display_name": "PC test"}, headers=h).status_code == 200
        assert by_name(get(c, h, "/api/builds")["items"])["g1_local_only"]["label"] == "PC test"
        assert c.patch(f"/api/builds/{GID}/g1_patch", json={"display_name": "x" * 121}, headers=h).status_code == 422
        assert c.patch(f"/api/builds/{GID}/nope", json={"display_name": "x"}, headers=h).status_code == 404
        assert c.patch(f"/api/builds/{GID}/g1_patch", json={"display_name": "x"}).status_code == 401
        # "" restores the writer's title
        assert c.patch(f"/api/builds/{GID}/g1_patch", json={"display_name": ""}, headers=h).json()["label"] == "Patch card"
        assert by_name(get(c, h, "/api/mods/built")["items"])["g1_patch"]["mod_title"] == "Patch card"
    assert marker.read_bytes() == before, "the marker (part of the pinned manifest) is never rewritten"
    assert (cfg.cache / "mods" / GID / "g1_patch").is_dir()
    assert [a["action"] for a in store.audit_log(0, 500) if a["action"] == "build.rename"]


def test_details_cast_characters_with_fitted_donor_and_the_original(tmp_path):
    cfg, app, store, h = fixture(tmp_path)
    store.put("job", "jcast", {"id": "jcast", "tool": "characters", "state": "succeeded", "receipt_id": "rc1",
                               "input": {"op": "cast_swap", "target_game": GID}, "created": 2990, "finished": 3000,
                               "output": {"result": {"mod": "cast_g1_wrestlers", "game_id": GID}},
                               "fitting": {"order": ["agent:smith"], "models": {"agent:smith": {
                                   "label": "Rock", "snapshot": "/api/jobs/jcast/fitting/files/smith.glb",
                                   "snapshot_stage": "write", "preview": "/api/jobs/jcast/fitting/files/smith-2.png"}}}})
    store.put("receipt", "rc1", {"id": "rc1", "job_id": "jcast", "tool": "characters", "validation_ok": True,
                                 "validation_problems": [], "finished": 3000,
                                 "artifacts": [{"sha256": "a" * 64, "name": "preview.png", "size": 4, "media_type": "image/png"}]})
    snap = cfg.cache / "fitting-jobs" / "jcast"
    snap.mkdir(parents=True)
    (snap / "smith.glb").write_bytes(b"glTF")
    (snap / "smith-2.png").write_bytes(b"PNG")
    with TestClient(app) as c:
        assert app.state.built_mods.wait(10)
        d = get(c, h, f"/api/builds/{GID}/cast_g1_wrestlers/details")
    ch = {r["slot"]: r for r in d["characters"]}
    neo, smith = ch["neo"], ch["agent:smith"]
    assert neo["donor"]["name"] == "Kane" and neo["status"] == "built"
    assert neo["fitted_url"] == "/api/characters/kane/file/targets/g1_neo.glb"
    assert neo["fitted_from"] == "fitted model kept in the collection"
    assert neo["original"]["slug"] == "g1_neo" and neo["original"]["model_url"] == "/api/characters/g1_neo/file/g1_neo.glb"
    assert smith["slot_name"] == "Agent Smith" and smith["reason"] == "too many bones"
    assert smith["fitted_url"] == "/api/jobs/jcast/fitting/files/smith.glb" and "fitting snapshot of job jcast" in smith["fitted_from"]
    assert smith["original"]["name"] == "Agent Smith"
    assert smith["fit_preview"] == "/api/jobs/jcast/fitting/files/smith-2.png" and neo["fit_preview"] == ""
    assert d["cast"] == {"source": "Wrestlers", "mapping": "by_role", "seed": ""}
    assert d["recipe"]["input"]["op"] == "cast_swap" and d["recipe_recorded"] is True
    assert [j["id"] for j in d["jobs"]] == ["jcast"] and d["receipts"][0]["artifacts"][0]["url"] == "/api/artifacts/" + "a" * 64
    assert d["modifications"]["files"][0] == {"path": "game.iso", "change": "image", "size": 2048,
                                              "what": "the built image the launch boots"}
    assert d["verification"]["text"] == "unverified in game until launched" and not d["verification"]["verified"]
    assert [w["label"] for w in d["where"]] == ["Spark collection", "i9-NUC (staged copy)"]
    assert d["codes"] == [] and d["codes_note"] and d["compile"] is None


def test_details_file_mod_codes_compile_and_launch_history(tmp_path):
    cfg, app, store, h = fixture(tmp_path)
    store.put("session", "w1-s1", {"session_id": "w1-s1", "game_id": GID, "mod": "g1_patch", "started": 5000.0,
                                   "state": "ended", "ended": 5100.0, "exit": "quit"})
    with TestClient(app) as c:
        assert app.state.built_mods.wait(10)
        d = get(c, h, f"/api/builds/{GID}/g1_patch/details")
        hack = get(c, h, f"/api/builds/{GID}/g1_hack/details")
        lo = get(c, h, f"/api/builds/{GID}/g1_local_only/details")
        get(c, h, f"/api/builds/{GID}/nope/details", 404)
    files = {f["path"]: f for f in d["modifications"]["files"]}
    assert files["game.z64"]["change"] == "image" and files["game.z64"]["size"] == 100
    assert "Mario model (gbox.sm64_writer)" in files["game.z64"]["what"]
    assert files["data/a.bin"] == {"path": "data/a.bin", "change": "replaced or patched", "size": 3}
    assert files["data/new.bin"]["change"] == "new" and "size" not in files["data/new.bin"]
    assert d["modifications"]["derived"] and "not recorded" in d["modifications"]["note"]
    types = [(x["type"], x.get("source")) for x in d["codes"]]
    assert types == [("cheat", "marker"), ("ram_write", "mod card"), ("cheat", "mod card")]
    assert d["codes"][2]["codes"] == ["ABCD-1234"] and d["codes"][1]["address"] == "0x8001234"
    assert d["compile"] == {"compiler_flags": "-O2 -g", "source_patches": [{"path": "src/mario.c", "lines": 12}]}
    assert d["verification"]["launches"][0]["session_id"] == "w1-s1"
    assert d["verification"]["text"].startswith("launched 1 time")
    assert d["tickets"][0]["number"] == 7
    assert hack["modifications"]["files"] == [{"path": "EBOOT.BIN", "change": "patched", "size": 10, "base_size": 10,
                                               "patches": [{"offset": 16, "length": 2}]}]
    assert not hack["modifications"]["derived"] and hack["kinds"][0] == "romhack"
    assert lo["local_only"] and "only on i9-NUC" in lo["note"]


def _job(store, jid, tool, inp, state="queued", **kw):
    doc = {"id": jid, "tool": tool, "input": inp, "state": state, "created": kw.pop("created", time.time()),
           "require_os": kw.pop("require_os", None), "require_worker": kw.pop("require_worker", None),
           "worker_id": kw.pop("worker_id", None), **kw}
    store.put("job", jid, doc)
    return doc


def test_scheduled_build_jobs_categories_phases_and_eta(tmp_path):
    cfg, app, store, h = fixture(tmp_path)
    now = time.time()
    _job(store, "q1", "characters", {"op": "cast_swap", "target_game": GID, "source": "wrestlers", "slots": "all"},
         require_os="linux", created=now - 30)
    _job(store, "r1", "characters", {"op": "use", "character": "kane", "game_id": GID, "slot": "player", "rebuild": True},
         state="running", worker_id="w2", started=now - 100, progress={"pct": 25.0, "msg": "retarget", "ts": now},
         fitting={"order": ["player"], "models": {"player": {"state": "running", "stages": {
             "scale": {"state": "done"}, "retarget": {"state": "running"}}}}, "current": "player"})
    _job(store, "c1", "file_mod", {"op": "build", "game_id": GID, "name": "x"}, state="running", worker_id="w1",
         started=now - 5, progress_log=["Copying 1/9 MB", "Copying 5/9 MB", "Patching EBOOT.BIN"])
    _job(store, "n1", "launch_game", {"mod": "g1_patch"})                          # not a build
    _job(store, "p1", "characters", {"op": "cast_swap", "target_game": GID, "plan_only": True})   # a plan
    _job(store, "f1", "characters", {"op": "collect", "game_id": GID}, state="failed", finished=now - 60, error="boom")
    _job(store, "old", "rom_export", {"op": "export"}, state="succeeded", finished=now - 99999)
    with TestClient(app) as c:
        r = get(c, h, "/api/builds/scheduled")
    rows = {x["id"]: x for x in r["jobs"]}
    assert list(rows) == ["r1", "c1", "q1"], "running, claimed, queued"
    assert rows["q1"]["category"] == "cast" and rows["q1"]["editable"] and rows["q1"]["phase"] == "queued"
    assert rows["q1"]["label"] == f"Cast swap: {GID} as wrestlers"
    assert rows["r1"]["phase"] == "running" and rows["r1"]["worker"] == "spark" and 290 <= rows["r1"]["eta_s"] <= 310
    assert rows["r1"]["label"].endswith("(rebuild)") and rows["r1"]["fitting"]["models"] == 1
    assert rows["c1"]["phase"] == "claimed" and rows["c1"]["category"] == "file" and rows["c1"]["eta_s"] is None
    assert rows["r1"]["stages"] == [{"name": "scale", "state": "done", "done": 1, "total": 1},
                                    {"name": "retarget", "state": "running", "done": 0, "total": 1}]
    assert rows["c1"]["steps"] == ["Copying 5/9 MB", "Patching EBOOT.BIN"], "one step per kind of message, newest numbers"
    assert rows["q1"]["stages"] == [] and rows["q1"]["steps"] == []
    assert [x["id"] for x in r["recent"]] == ["f1"] and r["recent"][0]["category"] == "collect"
    assert r["queued"] == 1 and r["running"] == 2


def test_edit_a_queued_job_is_cancel_and_resubmit_keeping_its_pinning(tmp_path):
    cfg, app, store, h = fixture(tmp_path)
    _job(store, "q1", "characters", {"op": "cast_swap", "target_game": GID, "source": "wrestlers", "slots": "all"},
         require_os="linux", parent_request_id="req1", agent_use=True)
    _job(store, "r1", "characters", {"op": "use", "character": "kane", "game_id": GID}, state="running", worker_id="w2")
    with TestClient(app) as c:
        bad = c.post("/api/builds/scheduled/q1/edit", json={"input": {"op": "use"}}, headers=h)
        assert bad.status_code == 422 and "op" in bad.text
        r = c.post("/api/builds/scheduled/q1/edit", json={"input": {"slots": "main", "source": "fighters"}}, headers=h)
        assert r.status_code == 200, r.text
        new = r.json()["job"]
        assert r.json()["cancelled"] == "q1" and new["edited_from"] == "q1"
        assert new["input"]["slots"] == "main" and new["input"]["source"] == "fighters" and new["input"]["op"] == "cast_swap"
        assert new["require_os"] == "linux" and new["parent_request_id"] == "req1" and new["agent_use"] is True
        assert new["state"] == "queued"
        old = store.get("job", "q1")
        assert old["state"] == "failed" and old["replaced_by"] == new["id"] and "edited" in old["error"]
        assert c.post("/api/builds/scheduled/r1/edit", json={"input": {"slot": "x"}}, headers=h).status_code == 409
        assert c.post("/api/builds/scheduled/nope/edit", json={"input": {"slot": "x"}}, headers=h).status_code == 404
        sched = get(c, h, "/api/builds/scheduled")
        assert [j["id"] for j in sched["jobs"] if j["state"] == "queued"] == [new["id"]]
        assert sched["jobs"][-1]["edited_from"] == "q1"
        # the existing cancel API stops a queued build job
        assert c.post(f"/api/jobs/{new['id']}/cancel", headers=h).json()["state"] == "failed"


def test_investigate_log_receipt_artifacts_and_fitting(tmp_path):
    cfg, app, store, h = fixture(tmp_path)
    log = store.put_artifact(b"line1\nwrote the image\n", "worker.log", "text/plain", {"job": "d1"}).sha256
    store.put("receipt", "rc", {"id": "rc", "job_id": "d1", "tool": "characters", "validation_ok": False,
                                "validation_problems": ["no image"], "finished": 1.0,
                                "artifacts": [{"sha256": "b" * 64, "name": "mod.json", "size": 9, "media_type": "application/json"}]})
    _job(store, "d1", "characters", {"op": "use", "character": "kane", "game_id": GID}, state="invalid", finished=time.time(),
         receipt_id="rc", log_sha=log, progress_log=["start", "retarget"],
         fitting={"order": ["player"], "models": {"player": {"state": "failed", "stages": {"write": {"state": "failed"}}}}},
         output={"result": {"status": "failed", "mod": "g1_kane", "report": [{"slot": "player", "status": "failed"}]}})
    with TestClient(app) as c:
        r = get(c, h, "/api/builds/scheduled/d1")
        get(c, h, "/api/builds/scheduled/nope", 404)
    assert r["log_tail"].endswith("wrote the image\n") and r["progress_log"] == ["start", "retarget"]
    assert r["receipt"]["validation_ok"] is False and r["receipt"]["problems"] == ["no image"]
    assert r["artifacts"][0]["url"] == "/api/artifacts/" + "b" * 64
    assert r["fitting_events"]["models"]["player"]["state"] == "failed"
    assert r["result"]["report"][0]["status"] == "failed" and r["mod"] == "g1_kane"


# ------------------------------------------------------------------------------------------------- build record

def test_stamp_and_stamp_marker(tmp_path):
    meta = R.stamp({"name": "m"}, kind="cast", job_id="j1", slots=[{"slot": "a", "donor": "b"}], codes=[], compile=None,
                   build_call=R.call_of("file_mod", {"op": "build", "changes": {"x": {"bytes": b"\0" * 9}},
                                                     "session_id": "s", "name": "m"}))
    assert meta["kind"] == "cast" and meta["job_id"] == "j1" and "codes" not in meta and "compile" not in meta
    assert meta["build_call"] == {"tool": "file_mod", "input": {"op": "build", "changes": {"x": {"bytes": "<9 bytes>"}},
                                                               "name": "m"}}
    with pytest.raises(ValueError):
        R.stamp({}, kind="nonsense")
    with pytest.raises(ValueError):
        R.stamp({}, title="not a record field")
    d = tmp_path / "m"
    d.mkdir()
    (d / ".gbox-mod.json").write_text(json.dumps({"name": "m", "writer": "w"}))
    assert R.stamp_marker(d, **R.from_ctx(SimpleNamespace(job_id="j2", worker="w1")))
    got = json.loads((d / ".gbox-mod.json").read_text())
    assert got["writer"] == "w" and got["job_id"] == "j2" and got["built_on"]["worker_id"] == "w1"
    assert not R.stamp_marker(tmp_path / "missing", job_id="x")
    assert R.file_change("a", "patched", 4, 4, [{"offset": "0x10", "hex": "ffee"}]) == {
        "path": "a", "change": "patched", "size": 4, "base_size": 4, "patches": [{"offset": 16, "length": 2}]}


def test_filemods_build_records_each_changed_file(tmp_path):
    from gbox import filemods
    src = tmp_path / "lib" / "Game" / "PS3_GAME" / "USRDIR"
    src.mkdir(parents=True)
    (src / "EBOOT.BIN").write_bytes(b"ELF0ELF0")
    (src / "data.bin").write_bytes(b"\x00\x01\x02\x03")
    new = tmp_path / "new.bin"
    new.write_bytes(b"NEWFILE")
    cfg = SimpleNamespace(cache=tmp_path / "cache")
    filemods.build(cfg, "g", src / "EBOOT.BIN", "hack", {"PS3_GAME/USRDIR/EBOOT.BIN": {"patch": [{"offset": "0x2", "hex": "ffff"}]},
                                                         "PS3_GAME/USRDIR/data.bin": {"bytes": b"xy"},
                                                         "PS3_GAME/USRDIR/extra.bin": {"from": str(new)}})
    meta = json.loads((filemods.mod_dir(cfg, "g", "hack") / ".gbox-mod.json").read_text())
    rows = {r["path"]: r for r in meta["file_changes"]}
    assert meta["kind"] == "romhack"
    assert rows["PS3_GAME/USRDIR/EBOOT.BIN"] == {"path": "PS3_GAME/USRDIR/EBOOT.BIN", "change": "patched", "size": 8,
                                                 "base_size": 8, "patches": [{"offset": 2, "length": 2}]}
    assert rows["PS3_GAME/USRDIR/data.bin"] == {"path": "PS3_GAME/USRDIR/data.bin", "change": "replaced", "size": 2,
                                                "base_size": 4}
    assert rows["PS3_GAME/USRDIR/extra.bin"]["change"] == "new" and rows["PS3_GAME/USRDIR/extra.bin"]["size"] == 7
    assert meta["files"] == ["PS3_GAME/USRDIR/EBOOT.BIN", "PS3_GAME/USRDIR/data.bin", "PS3_GAME/USRDIR/extra.bin (new)"] or \
        sorted(meta["files"]) == sorted(["PS3_GAME/USRDIR/EBOOT.BIN", "PS3_GAME/USRDIR/data.bin", "PS3_GAME/USRDIR/extra.bin (new)"])


def test_the_characters_build_path_stamps_job_and_call_but_never_a_reused_build(tmp_path, monkeypatch):
    from gbox import characters as C
    from gbox import special_builds as S
    from gbox.registry import REGISTRY
    cfg = Config(data_dir=tmp_path / "data", cache_dir=tmp_path / "cache")
    d = mk(cfg.cache, GID, "etm_kane_neo", {"writer": "gbox.etm_swap", "built": 5.0})
    result = {"status": "built", "mod": "etm_kane_neo", "slug": "kane", "game_id": GID}
    monkeypatch.setattr(C, "characters_tool", lambda inp, ctx: {"result": dict(result)})
    fn = REGISTRY["characters"].fn
    fn(C.CharIn(op="use", character="kane", game_id=GID, slot="neo"), SimpleNamespace(config=cfg, job_id="jb1", worker="w2"))
    meta = json.loads((d / ".gbox-mod.json").read_text())
    assert meta["job_id"] == "jb1" and meta["kind"] == "character" and meta["built_on"]["worker_id"] == "w2"
    assert meta["build_call"]["tool"] == "characters" and meta["build_call"]["input"]["character"] == "kane"
    assert meta["recipe"]["input"]["slot"] == "neo"
    before = (d / ".gbox-mod.json").read_bytes()
    result["status"] = "ready"                                       # reused as it is: the marker stays byte for byte
    fn(C.CharIn(op="use", character="kane", game_id=GID, slot="neo"), SimpleNamespace(config=cfg, job_id="jb2", worker="w2"))
    assert (d / ".gbox-mod.json").read_bytes() == before
    assert S.REUSED


def test_local_builds_report(tmp_path):
    from gbox import filemods
    cfg = SimpleNamespace(cache=tmp_path / "cache")
    mk(cfg.cache, "g", "a", {})
    st = mk(cfg.cache, "g", "a~123", {})
    (st / filemods.STAGED_MARK).write_text("a")
    (cfg.cache / "mods" / "g" / "nomarker").mkdir()
    rows = filemods.local_builds(cfg, now=1.0)
    assert sorted((r["name"], r.get("staged_of")) for r in rows) == [("a", None), ("a~123", "a")]
    assert filemods.local_builds(cfg, now=2.0) is rows, "cached"


def test_kinds_and_original_matching_helpers():
    assert B.kinds_of({"name": "x"}, {}) == ["file"]
    assert B.kinds_of({"name": "x", "tickets": [{"number": 1}]}, {}) == ["file", "test"]
    assert B.kinds_of({"name": "x"}, {"kind": "compile"})[0] == "compile"
    chars = [{"slug": "doa2_kasumi", "name": "Kasumi", "aliases": []}, {"slug": "hero", "name": "Ryu", "native_player": True}]
    assert B.original_for("fighter:kasumi", "", chars)["slug"] == "doa2_kasumi"
    assert B.original_for("player", "player", chars)["slug"] == "hero"
    assert B.original_for("enemy:booma", "Booma", chars) is None
    assert B.job_category("characters", {"op": "cast_swap", "mod_name": "showcase_sonic_x"}) == "showcase"
    assert B.job_category("characters", {"op": "live_use"}) is None
    assert B.job_category("n64recomp", {"op": "run"}) == "compile"


def test_favorites_first_filter_and_endpoints(tmp_path):
    """#1656: ☆/★ per build (store kind build_favorite, the folder untouched): listed first in Builds and on the Mods
    page, ?favorite=true filters, PUT / POST {favorite} and DELETE, unknown builds 404, bad values 422, audited."""
    from gbox import built_mods as BM
    cfg, app, store, h = fixture(tmp_path)
    marker = cfg.cache / "mods" / GID / "g1_hack" / ".gbox-mod.json"
    before = marker.read_bytes()
    with TestClient(app) as c:
        assert app.state.built_mods.wait(10)
        r = c.put(f"/api/builds/{GID}/g1_hack/favorite", json={"favorite": True}, headers=h)
        assert r.status_code == 200 and r.json() == {"key": "g1/g1_hack", "favorite": True}
        # the desktop app's IPC api() posts every body: POST does the same; a PC-only build can be starred too
        assert c.post(f"/api/builds/{GID}/g1_local_only/favorite", json={"favorite": True}, headers=h).status_code == 200
        lst = get(c, h, "/api/builds")
        names = [x["name"] for x in lst["items"]]
        assert names[:2] == ["g1_local_only", "g1_hack"], "favorites first, newest first among them"
        assert names[2:] == ["showcase_sonic_g1", "cast_g1_wrestlers", "g1_patch", "g2_hucast"]
        assert lst["favorites"] == 2 and by_name(lst["items"])["g1_hack"]["favorite"] is True
        assert by_name(lst["items"])["g1_patch"]["favorite"] is False
        assert [x["name"] for x in get(c, h, "/api/builds?favorite=true")["items"]] == ["g1_local_only", "g1_hack"]
        assert [x["name"] for x in get(c, h, "/api/builds?favorite=true&game_id=g2")["items"]] == []
        mods = get(c, h, "/api/mods/built")
        assert by_name(mods["items"])["g1_hack"]["favorite"] is True
        assert [x["name"] for x in get(c, h, "/api/mods/built?favorite=true")["items"]] == ["g1_hack"]
        assert get(c, h, f"/api/builds/{GID}/g1_hack/details")["favorite"] is True
        # protected from any disk budget (the Sonic showcase's LRU eviction asks built_mods.protected)
        assert BM.protected(store, GID, "g1_hack") == "the operator favorited it"
        assert BM.protected(store, GID, "g1_patch") == ""
        assert BM.favorites(store) == {"g1/g1_hack", "g1/g1_local_only"}
        # un-star: DELETE, or PUT {favorite: false}
        assert c.delete(f"/api/builds/{GID}/g1_hack/favorite", headers=h).json()["favorite"] is False
        assert c.put(f"/api/builds/{GID}/g1_local_only/favorite", json={"favorite": False}, headers=h).status_code == 200
        assert get(c, h, "/api/builds")["favorites"] == 0
        assert [x["name"] for x in get(c, h, "/api/builds")["items"]][0] == "g1_local_only", "newest first again"
        assert c.put(f"/api/builds/{GID}/nope/favorite", json={}, headers=h).status_code == 404
        assert c.put(f"/api/builds/{GID}/g1_hack/favorite", json={"favorite": "yes"}, headers=h).status_code == 422
        assert c.put(f"/api/builds/{GID}/g1_hack/favorite", json={}).status_code == 401
    assert marker.read_bytes() == before, "a favorite never touches the build's marker"
    acts = [a["action"] for a in store.audit_log(0, 500)]
    assert "build.favorite" in acts and "build.unfavorite" in acts


def test_display_name_reaches_mod_cards_launches_sessions_and_post_rename(tmp_path):
    """#1656 official names: a renamed build keeps its folder; the name shows on the mod cards (display_name next to
    the card's own title), on the launch job (mod_title: the launch bar) and on sessions (the Mini window title).
    POST renames too (the desktop app's IPC api)."""
    cfg, app, store, h = fixture(tmp_path)
    store.upsert_catalog([{"game_id": GID, "title": "Game One", "platform": "ps1", "source_paths": ["g1.cue"],
                           "format": "cue", "profile_id": GID, "core": "pcsx_rearmed",
                           "launch": {"kind": "retroarch", "path": "g1.cue"}}])
    store.put("session", "w1-s1", {"session_id": "w1-s1", "game_id": GID, "title": "Game One", "state": "ended",
                                   "mod": "g1_patch~ab", "collection_mod": "g1_patch", "started": 1.0})
    with TestClient(app) as c:
        assert app.state.built_mods.wait(10)
        r = c.post(f"/api/builds/{GID}/g1_patch", json={"display_name": "Sonic Full Cast"}, headers=h)
        assert r.status_code == 200 and r.json()["label"] == "Sonic Full Cast"
        cards = {m["id"]: m for m in get(c, h, f"/api/mods?game_id={GID}")}
        assert cards["card1"]["display_name"] == "Sonic Full Cast" and cards["card1"]["title"] == "Patch card"
        assert store.get("mod", "card1")["title"] == "Patch card", "the saved card is never rewritten"
        j = c.post(f"/api/games/{GID}/launch?node=windows&mod=g1_patch", headers=h)
        assert j.status_code == 200, j.text
        assert j.json()["input"]["mod"] == "g1_patch" and j.json()["input"]["mod_title"] == "Sonic Full Cast"
        plain = c.post(f"/api/games/{GID}/launch?node=windows&mod=g1_hack", headers=h).json()
        assert not plain["input"].get("mod_title"), "an unnamed build launches under its folder name"
        s = {x["session_id"]: x for x in get(c, h, "/api/sessions")}
        assert s["w1-s1"]["mod_title"] == "Sonic Full Cast"
    assert (cfg.cache / "mods" / GID / "g1_patch").is_dir() and not (cfg.cache / "mods" / GID / "Sonic Full Cast").exists()


def test_cache_eviction_never_touches_built_mods(tmp_path):
    """Favorited or not, a built mod is never a cache copy: catalog.evict skips mods/ (EVICT_KEEP)."""
    from gbox import catalog
    cache = tmp_path / "cache"
    mod = mk(cache, GID, "g1_fav", {"built": 1.0}, {"game.iso": b"m" * 4096})
    (cache / "g1").mkdir()
    (cache / "g1" / "copy.iso").write_bytes(b"c" * 4096)
    evicted = catalog.evict(cache, 0)
    assert evicted == [str(cache / "g1" / "copy.iso")]
    assert (mod / "game.iso").is_file() and (mod / ".gbox-mod.json").is_file()
