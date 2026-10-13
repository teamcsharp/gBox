"""Special builds (gbox/special_builds.py): one game's built mods grouped for the right-click menu (confirmation builds
linked to requests, cast swaps, character swaps, other), their launch options and rebuild recipes, recipes recorded
into the markers by the shared characters build path, and rebuilds queued as Spark jobs. A fake cache + store only:
nothing is built or launched."""
import json
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from gbox import special_builds as S
from gbox.config import Config
from gbox.server import create_app

GID = "g1"
WRESTLERS = "Wrestlers (No Mercy, WCW, SmackDown! 2, Def Jam)"
KANE_RECIPE = {"tool": "characters", "input": {"op": "use", "character": "kane", "game_id": GID, "slot": "player",
                                               "launch": False, "rebuild": True}}


def build(cache, gid, name, meta):
    d = cache / "mods" / gid / name
    d.mkdir(parents=True)
    (d / ".gbox-mod.json").write_text(json.dumps({"name": name, "game_id": gid, **meta}))
    return d


def fixture(tmp_path):
    cache = tmp_path / "cache"
    cfg = Config(data_dir=tmp_path / "data", cache_dir=cache)
    build(cache, GID, "cast_g1_wrestlers_abcd", {
        "built": 3000.0, "writer": "gbox.etm_swap", "cast_source": WRESTLERS, "cast_mapping": "by_role", "cast_seed": "s",
        "cast": [{"slot": "neo", "character": "kane", "status": "built"},
                 {"slot": "agent:smith", "character": "rock", "status": "failed", "reason": "too many bones"}]})
    build(cache, GID, "g1_hucast", {"built": 1000.0, "character": "hucast", "slot": "player"})
    build(cache, GID, "g1_kane_req", {"built": 4000.0, "character": "kane", "requests": [9],
                                       "recipe": dict(KANE_RECIPE, recorded=3999.0)})
    build(cache, GID, "g1_patch", {"built": 2000.0, "files": ["a.bin"]})
    build(cache, GID, "g1_ryu", {"built": 2500.0, "characters": ["ryu"], "replaces": ["Axel"]})
    build(cache, "g2", "other_game", {"built": 5000.0, "character": "kane", "requests": [9]})
    app = create_app(cfg)
    store = app.state.store
    store.put("mod", "card1", {"id": "card1", "title": "HUcast in G1", "game_id": GID, "state_slot": 3, "requests": [5],
                               "calls": [{"tool": "@launch", "input": {"mod": "g1_hucast"}}], "ts": 10})
    store.put("request", "r5", {"id": "r5", "number": 5, "title": "Put HUcast in G1", "status": "done"})
    store.put("request", "r9", {"id": "r9", "number": 9, "title": "Kane as the hero", "status": "in_progress"})
    now = time.time()
    store.put("worker", "w1", {"id": "w1", "name": "i9-NUC", "os": "windows", "last_seen": now, "tools": []})
    store.put("worker", "w2", {"id": "w2", "name": "spark", "os": "linux", "last_seen": now, "tools": []})
    store.put("worker", "w3", {"id": "w3", "name": "old-laptop", "os": "windows", "last_seen": now - 9999, "tools": []})
    return cfg, app, store, {"Authorization": f"Bearer {cfg.token()}"}


def special(c, h, gid=GID):
    r = c.get(f"/api/games/{gid}/special_builds", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def by_key(groups):
    return {g["key"]: g for g in groups}


def test_groups_confirmation_cast_character_other_newest_first(tmp_path):
    cfg, app, store, h = fixture(tmp_path)
    with TestClient(app) as c:
        assert app.state.built_mods.wait(10)
        r = special(c, h)
    assert [g["label"] for g in r["groups"]] == ["Confirmation builds", "Cast swaps", "Character swaps", "Other"]
    g = by_key(r["groups"])
    assert r["total"] == 5, "the other game's build is not listed"
    # confirmation builds: linked to a request (marker or mod card), newest first, with the ticket titles
    conf = g["confirmation"]["builds"]
    assert [b["name"] for b in conf] == ["g1_kane_req", "g1_hucast"]
    assert conf[0]["tickets"] == [{"number": 9, "id": "r9", "title": "Kane as the hero", "status": "in_progress"}]
    assert conf[1]["tickets"][0]["title"] == "Put HUcast in G1" and conf[1]["kind"] == "character"
    # cast swaps: source group and per-slot summary
    cast = g["cast"]["builds"]
    assert [b["name"] for b in cast] == ["cast_g1_wrestlers_abcd"]
    assert cast[0]["cast"]["source"] == WRESTLERS
    assert cast[0]["cast"]["summary"] == "1/2 slots built, 1 failed"
    assert cast[0]["cast"]["rows"][1] == {"slot": "agent:smith", "donor": "rock", "status": "failed", "reason": "too many bones"}
    assert [b["name"] for b in g["character"]["builds"]] == ["g1_ryu"]
    assert g["character"]["builds"][0]["summary"] == "ryu → Axel"
    assert [b["name"] for b in g["other"]["builds"]] == ["g1_patch"]
    assert {p["name"] for p in r["pcs"]} == {"i9-NUC", "spark"}, "offline PCs are not offered"


def test_rebuild_recipes_recorded_or_inferred(tmp_path):
    cfg, app, store, h = fixture(tmp_path)
    with TestClient(app) as c:
        assert app.state.built_mods.wait(10)
        g = by_key(special(c, h)["groups"])
    kane, hucast = g["confirmation"]["builds"]
    assert kane["rebuild_recipe"] == KANE_RECIPE and kane["recipe_recorded"] is True
    assert hucast["rebuild_recipe"] == {"tool": "characters", "input": {
        "op": "use", "character": "hucast", "game_id": GID, "slot": "player", "launch": False, "rebuild": True}}
    assert hucast["recipe_recorded"] is False
    cast = g["cast"]["builds"][0]["rebuild_recipe"]["input"]
    assert cast == {"op": "cast_swap", "target_game": GID, "source": "wrestlers", "mapping": "by_role", "seed": "s",
                    "slots": "neo,agent:smith", "assignments": [{"slot": "neo", "character": "kane"},
                                                                {"slot": "agent:smith", "character": "rock"}],
                    "launch": False, "rebuild": True}
    assert g["character"]["builds"][0]["rebuild_recipe"]["input"]["character"] == "ryu"
    other = g["other"]["builds"][0]
    assert other["rebuild_recipe"] is None and "records no character" in other["recipe_missing"]


def test_launch_options_this_pc_chosen_pc_saved_moment_debug(tmp_path):
    cfg, app, store, h = fixture(tmp_path)
    with TestClient(app) as c:
        assert app.state.built_mods.wait(10)
        g = by_key(special(c, h)["groups"])
    hucast = g["confirmation"]["builds"][1]
    opts = {o["id"]: o for o in hucast["launch_options"]}
    assert [o["id"] for o in hucast["launch_options"]] == ["here", "pc:i9-NUC", "pc:spark", "moment", "debug", "moment+debug"]
    assert opts["here"]["default"] and opts["here"]["target"] == "here"
    assert opts["here"]["call"] == {"method": "POST", "path": "/api/games/g1/launch?node=auto&mod=g1_hucast"}
    assert opts["pc:i9-NUC"]["call"]["path"] == "/api/games/g1/launch?node=i9-NUC&mod=g1_hucast"
    assert opts["moment"]["call"]["then"] == {"tool": "session_op", "op": "load_state", "slot": 3}
    assert opts["debug"]["debug"] and opts["debug"]["call"]["path"].endswith("&debug=true")
    assert not any(o["moment"] for o in g["other"]["builds"][0]["launch_options"]), "no saved moment: no moment option"


def test_rebuild_all_confirmation_builds_queues_spark_jobs(tmp_path):
    cfg, app, store, h = fixture(tmp_path)
    with TestClient(app) as c:
        assert app.state.built_mods.wait(10)
        r = c.post(f"/api/games/{GID}/special_builds/rebuild", json={"recipes": "all"}, headers=h).json()
        assert r["queued"] == 2 and len(r["job_ids"]) == 2 and r["skipped"] == []
        assert [j["key"] for j in r["jobs"]] == ["g1/g1_kane_req", "g1/g1_hucast"]
        for jid in r["job_ids"]:
            j = store.get("job", jid)
            assert j["tool"] == "characters" and j["state"] == "queued" and j["require_os"] == "linux"
            assert j["input"]["launch"] is False and j["input"]["rebuild"] is True and j["input"]["op"] == "use"
        assert store.get("job", r["job_ids"][0])["input"]["character"] == "kane"
        # every group, by key, and nothing without a recipe
        r = c.post(f"/api/games/{GID}/special_builds/rebuild", json={"recipes": "all", "group": "other"}, headers=h).json()
        assert r["queued"] == 0 and r["skipped"][0]["key"] == "g1/g1_patch"
        r = c.post(f"/api/games/{GID}/special_builds/rebuild", json={"keys": ["g1/cast_g1_wrestlers_abcd"]}, headers=h).json()
        assert r["queued"] == 1 and store.get("job", r["job_ids"][0])["input"]["op"] == "cast_swap"
        assert c.post(f"/api/games/{GID}/special_builds/rebuild", json={"recipes": 7}, headers=h).status_code == 422
        assert c.post(f"/api/games/{GID}/special_builds/rebuild", json={}).status_code == 401


def test_rebuild_explicit_recipes_never_launch_and_skip_bad_ones(tmp_path):
    cfg, app, store, h = fixture(tmp_path)
    sneaky = {"tool": "characters", "input": dict(KANE_RECIPE["input"], launch=True, rebuild=False, session_id="w1-s")}
    with TestClient(app) as c:
        assert app.state.built_mods.wait(10)
        r = c.post(f"/api/games/{GID}/special_builds/rebuild", headers=h, json={"recipes": [
            sneaky, KANE_RECIPE, {"tool": "launch_game", "input": {}}, {"tool": "characters", "input": {"op": "extract"}}]}).json()
    assert r["queued"] == 1
    j = store.get("job", r["job_ids"][0])
    assert j["input"]["launch"] is False and j["input"]["rebuild"] is True and not j["input"].get("session_id")
    reasons = [s["reason"] for s in r["skipped"]]
    assert any("queued once" in x for x in reasons), "the same recipe twice is queued once"
    assert any("tool: 'characters'" in x for x in reasons) and any("op='extract'" in x for x in reasons)


def test_queue_reports_rejected_and_failing_submits():
    calls = []

    def submit(tool, inp, os_):
        calls.append((tool, inp["character"], os_))
        if inp["character"] == "a":
            return {"id": "j1", "state": "queued", "tool": tool, "input": inp}
        if inp["character"] == "b":
            return {"id": "j2", "state": "rejected", "error": "permission not granted"}
        raise RuntimeError("store down")
    todo = [{"key": k, "label": k, "recipe": {"tool": "characters", "input": {"op": "use", "character": k, "game_id": "g"}}}
            for k in "abc"]
    jobs, skipped = S.queue(todo, submit)
    assert [j["job_id"] for j in jobs] == ["j1"]
    assert [(s["key"], s["reason"]) for s in skipped] == [("b", "permission not granted"), ("c", "store down")]
    assert all(c[2] == "linux" for c in calls)


def test_recipe_from_call_per_op():
    use = S.recipe_from_call({"op": "use", "character": "Kane", "game_id": "", "game": "Enter the Matrix", "slot": "neo",
                              "active_id": None, "launch": True, "session_id": "w1-s", "head_scale": 0.0},
                             {"status": "built+launched", "mod": "etm_kane_neo", "slug": "kane", "game_id": GID})
    assert use == {"tool": "characters", "input": {"op": "use", "character": "kane", "game_id": GID, "slot": "neo",
                                                   "launch": False, "rebuild": True}}
    match = S.recipe_from_call({"op": "match", "game_id": GID, "pairs": [{"character": "a", "slot": "x"}], "title": "A v X"},
                               {"status": "built", "mod": "m"})
    assert match["input"] == {"op": "match", "game_id": GID, "pairs": [{"character": "a", "slot": "x"}], "title": "A v X",
                              "launch": False, "rebuild": True}
    cast = S.recipe_from_call({"op": "cast_swap", "target_game": "Enter the Matrix", "source": "wrestlers", "mapping": "auto",
                               "seed": "", "slots": "all", "assignments": []},
                              {"status": "partial", "mod": "cast_x", "game_id": GID,
                               "assignments": [{"slot": "neo", "character": "kane"}, {"slot": "trinity", "character": "lita"}]})
    assert cast["input"]["target_game"] == GID and len(cast["input"]["assignments"]) == 2
    for inp, res in [({"op": "use"}, {"status": "failed", "mod": "x", "game_id": GID}),
                     ({"op": "use", "game_id": GID}, {"status": "not_in_collection"}),
                     ({"op": "cast_swap", "plan_only": True}, {"status": "planned", "mod": "x"}),
                     ({"op": "list"}, {"mod": "x"}),
                     ({"op": "use", "character": "k"}, {"status": "overlay", "mod": "x", "game_id": GID})]:
        assert S.recipe_from_call(inp, res) is None, (inp, res)


def test_the_shared_build_path_records_the_recipe_in_the_marker(tmp_path, monkeypatch):
    from gbox import characters as C
    from gbox.registry import REGISTRY
    cfg = Config(data_dir=tmp_path / "data", cache_dir=tmp_path / "cache")
    d = build(cfg.cache, GID, "etm_kane_neo", {"writer": "gbox.etm_swap", "built": 5.0, "requests": [9]})
    monkeypatch.setattr(C, "characters_tool", lambda inp, ctx: {"result": {"status": "built", "mod": "etm_kane_neo",
                                                                           "slug": "kane", "game_id": GID}})
    fn = REGISTRY["characters"].fn
    assert fn.__name__ == "characters_tool" and REGISTRY["characters"].description.startswith("gBox's collection")
    ctx = SimpleNamespace(config=cfg)
    out = fn(C.CharIn(op="use", character="kane", game_id=GID, slot="neo"), ctx)
    assert out["result"]["mod"] == "etm_kane_neo"
    meta = json.loads((d / ".gbox-mod.json").read_text())
    assert meta["writer"] == "gbox.etm_swap" and meta["requests"] == [9], "the writer's marker is kept"
    assert {k: v for k, v in meta["recipe"].items() if k != "recorded"} == {"tool": "characters", "input": {
        "op": "use", "character": "kane", "game_id": GID, "slot": "neo", "launch": False, "rebuild": True}}
    assert S.recipe_for(meta, GID) == ({"tool": "characters", "input": meta["recipe"]["input"]}, True)
    stamp = meta["recipe"]["recorded"]
    fn(C.CharIn(op="use", character="kane", game_id=GID, slot="neo"), ctx)       # same recipe: marker left alone
    assert json.loads((d / ".gbox-mod.json").read_text())["recipe"]["recorded"] == stamp
    # a build on another node (no marker here) and a failing build record nothing and never raise
    monkeypatch.setattr(C, "characters_tool", lambda inp, ctx: {"result": {"status": "built", "mod": "elsewhere", "game_id": GID}})
    assert fn(C.CharIn(op="use", character="kane", game_id=GID), ctx)["result"]["mod"] == "elsewhere"
    assert S.record_call(ctx, C.CharIn(op="use", character="kane", game_id=GID), None) is None


@pytest.mark.parametrize("label,spec", [(WRESTLERS, "wrestlers"), ("Jet Grind Radio", "Jet Grind Radio"),
                                        (f"{WRESTLERS} + Sonic Adventure", "wrestlers, Sonic Adventure"),
                                        ("Sonic Adventure / Sonic Adventure DX", "Sonic Adventure")])
def test_cast_source_labels_map_back_to_a_source_spec(label, spec):
    assert S.source_spec(label) == spec
