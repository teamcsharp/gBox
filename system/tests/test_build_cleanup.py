"""#1656 follow-ups on the build cards: "What this changes" (recorded, compared with the game's base copy, inferred from
the name and the writer's docs, or not recorded), 🗑 Delete (the Spark collection copy and every PC's, staged copies,
sidecars and store records; refused while a game runs it; never the base copy or another build; a recently deleted
log) and ⚑ Report (the issue flow, the build's facts and pictures, the investigation queue, "Reported #N").
A fake cache, store and workers only: nothing is built, launched or captured."""
import json
import os
import time

import pytest
from fastapi.testclient import TestClient

from gbox import build_summary as S
from gbox import built_mods as BM
from gbox import filemods
from tests.test_builds import GID, OTHER, by_name, fixture, get, mk


# ------------------------------------------------------------------------------------------------- What this changes

def test_summary_recorded_cast_codes_files_and_where():
    cast = S.summarize("cast_x", GID, {"cast": [{"slot": "neo", "character": "kane", "status": "built"},
                                                 {"slot": "smith", "character": "rock", "status": "failed"}],
                                        "cast_source": "Wrestlers"})
    assert cast["status"] == "recorded" and not cast["badge"]
    assert cast["lines"] == ["Replaces the game's cast with Wrestlers: 1 character swapped (kane → neo); 1 not swapped"]
    assert cast["where"] == "slots: neo, smith"
    patch = S.summarize("p", GID, {"files": ["data/a.bin", "@image: Mario model (gbox.sm64_writer)"], "image": "game.z64",
                                   "cheats": ["8001 0063"], "where_to_look": "Castle grounds, first star"})
    assert patch["lines"][0] == "Applies 1 code (cheat): 8001 0063" and patch["lines"][1].startswith("Changes 2 files: a.bin")
    assert patch["where"] == "Castle grounds, first star"
    noted = S.summarize("n", GID, {"description": "Sonic replaces Bond in every multiplayer level"})
    assert noted["lines"] == ["Sonic replaces Bond in every multiplayer level"] and noted["sources"] == ["marker description"]
    card = S.summarize("c", GID, {}, {"desc": "Infinite ammo and all gadgets", "auto_registered": False})
    assert card["lines"] == ["Infinite ammo and all gadgets"] and card["sources"] == ["mod card"]
    auto = S.summarize("zz_c", GID, {}, {"desc": "Built by x (registered from the built mod folder)", "auto_registered": True})
    assert auto["status"] == "unknown" and auto["badge"] == "Changes not recorded" and auto["lines"] == []


def test_summary_compared_no_changes_and_inferred_from_the_name():
    same = S.summarize("auf_dm1_bondcombat_uwbthug", "65b7187589166b26", {},
                       diff={"base": True, "changed_n": 0, "new_n": 0, "unverified_n": 0, "same_n": 12})
    assert same["status"] == "no_changes"
    assert same["badge"] == "No changes from the original game found: this looks like a test build"
    assert same["lines"][0].startswith("Inferred from the name: 007 Agent Under Fire: multiplayer map dm1; characters Bond (combat)")
    assert same["where"] == "Multiplayer > map dm1 > play as Bond (combat)" and same["where_inferred"]
    diff = S.summarize("x", GID, {}, diff={"base": True, "changed": ["data/a.bin"], "new": ["data/b.bin"], "changed_n": 1,
                                          "new_n": 1, "unverified": ["big.iso"], "unverified_n": 1})
    assert diff["status"] == "compared"
    assert diff["lines"] == ["Differs from the original game in 2 files: a.bin (changed), b.bin (new)",
                             "1 file may differ (the same size as the original, too large to compare): big.iso"]
    guess = S.summarize("auf_dm1_bondcombat_uwbthug", "65b7187589166b26", {}, writer="auf_swap")
    assert guess["status"] == "inferred" and guess["inferred"]
    assert guess["lines"][1].startswith("Inferred from the writer (auf_swap): 007: Agent Under Fire (GameCube")
    assert S.summarize("tmp_thing", GID, {}, diff={"base": False})["badge"] == "Changes not recorded"
    assert S.writer_doc("../etc") == "" and S.writer_doc("no_such_writer_module") == ""


def test_base_diff_same_changed_new_and_unverified(tmp_path, monkeypatch):
    base, mod = tmp_path / "modbase" / GID, tmp_path / "mods" / GID / "m"
    (base / "data").mkdir(parents=True)
    (mod / "data").mkdir(parents=True)
    (base / "data" / "linked.bin").write_bytes(b"L" * 10)
    os.link(base / "data" / "linked.bin", mod / "data" / "linked.bin")
    (base / "data" / "copy.bin").write_bytes(b"C" * 10)
    (mod / "data" / "copy.bin").write_bytes(b"C" * 10)
    (base / "data" / "edit.bin").write_bytes(b"E" * 10)
    (mod / "data" / "edit.bin").write_bytes(b"X" * 10)
    (base / "data" / "grow.bin").write_bytes(b"G" * 10)
    (mod / "data" / "grow.bin").write_bytes(b"G" * 11)
    (mod / "data" / "new.bin").write_bytes(b"N")
    (base / "big.iso").write_bytes(b"B" * 64)
    (mod / "big.iso").write_bytes(b"b" * 64)
    (mod / BM.MARKER).write_text("{}")
    (mod / "preview.png").write_bytes(b"\x89PNG")
    monkeypatch.setattr(BM, "DIFF_BYTES", 32)
    d = BM.base_diff(mod, base)
    assert d["same_n"] == 2 and sorted(d["changed"]) == ["data/edit.bin", "data/grow.bin"] and d["new"] == ["data/new.bin"]
    assert d["unverified"] == ["big.iso"], "equal size, too big to compare here"
    assert BM.base_diff(mod, tmp_path / "nope") == {"base": False}
    for f in ("big.iso", "data/edit.bin", "data/grow.bin", "data/new.bin"):
        (mod / f).unlink()
    assert {k: d2 for k, d2 in BM.base_diff(mod, base).items() if k.endswith("_n")} == {
        "changed_n": 0, "new_n": 0, "unverified_n": 0, "same_n": 2}


def test_the_listing_carries_what_this_changes_and_the_no_changes_badge(tmp_path):
    cfg, app, store, h = fixture(tmp_path)
    base = cfg.cache / "modbase" / OTHER
    base.mkdir(parents=True)
    (base / "game.iso").write_bytes(b"stock")
    d = mk(cfg.cache, OTHER, "g2_test_build", {"built": 900.0})
    os.link(base / "game.iso", d / "game.iso")
    with TestClient(app) as c:
        assert app.state.built_mods.wait(10)
        rows = by_name(get(c, h, "/api/builds")["items"])
        mods = by_name(get(c, h, "/api/mods/built")["items"])
        sb = {b["name"]: b for g in get(c, h, f"/api/games/{GID}/special_builds")["groups"] for b in g["builds"]}
    t = rows["g2_test_build"]["what"]
    assert t["status"] == "no_changes" and t["badge"].startswith("No changes from the original game found")
    assert mods["g2_test_build"]["what"]["status"] == "no_changes"
    assert rows["cast_g1_wrestlers"]["what"]["lines"][0].startswith("Replaces the game's cast with Wrestlers")
    assert rows["g1_patch"]["what"]["status"] == "recorded"
    assert sb["cast_g1_wrestlers"]["what"]["status"] == "recorded"
    assert rows["g1_local_only"]["what"]["badge"] == "Changes not recorded", "a PC-only build: nothing on the Spark to read"


# ------------------------------------------------------------------------------------------------- 🗑 Delete

def _sidecar(cfg, gid, name):
    p = cfg.cache / "mods" / gid / f".{name}.sha256.json"
    p.write_text("{}")
    return p


def test_delete_everywhere_removes_the_collection_copy_and_queues_every_pc(tmp_path):
    cfg, app, store, h = fixture(tmp_path)
    base = cfg.cache / "modbase" / GID
    base.mkdir(parents=True)
    (base / "keep.bin").write_bytes(b"base")
    staged = mk(cfg.cache, GID, "cast_g1_wrestlers~abc123", {"built": 3001.0})
    (staged / filemods.STAGED_MARK).write_text("cast_g1_wrestlers")
    side = _sidecar(cfg, GID, "cast_g1_wrestlers")
    store.put("mod", "auto1", {"id": "auto1", "title": "G1 cast", "game_id": GID, "auto_registered": True,
                               "calls": [{"tool": "@launch", "input": {"mod": "cast_g1_wrestlers"}}]})
    with TestClient(app) as c:
        assert app.state.built_mods.wait(10)
        assert c.patch(f"/api/builds/{GID}/cast_g1_wrestlers", headers=h, json={"display_name": "Wrestle"}).status_code == 200
        assert c.put(f"/api/builds/{GID}/cast_g1_wrestlers/favorite", headers=h, json={}).status_code == 200
        r = c.delete(f"/api/builds/{GID}/cast_g1_wrestlers", headers=h)
        assert r.status_code == 200, r.text
        out = r.json()
        assert out["scope"] == "all" and out["spark"]["removed"] == ["cast_g1_wrestlers", "cast_g1_wrestlers~abc123"]
        assert [j["node"] for j in out["jobs"]] == ["i9-NUC"], "the PC with a (staged) copy gets a delete job"
        job = store.get("job", out["jobs"][0]["job_id"])
        assert job["tool"] == "file_mod" and job["input"] == {"game_id": GID, "op": "delete_build", "name": "cast_g1_wrestlers",
                                                              "changes": {}} and job["require_worker"] == "w1"
        assert {"build_name", "build_favorite", "mod card auto1"} <= set(out["cleared"])
        names = [x["name"] for x in get(c, h, "/api/builds")["items"]]
        assert "cast_g1_wrestlers" not in names or by_name(get(c, h, "/api/builds")["items"])["cast_g1_wrestlers"]["local_only"]
        assert "cast_g1_wrestlers" not in [m["name"] for m in get(c, h, "/api/mods/built")["items"]]
        deleted = get(c, h, "/api/builds/deleted")["items"]
        assert deleted[0]["key"] == f"{GID}/cast_g1_wrestlers" and deleted[0]["meta"]["writer"] == "gbox.etm_swap"
        assert deleted[0]["label"] == "Wrestle"
        assert c.get(f"/api/builds/deleted", headers={}).status_code == 401
    assert not (cfg.cache / "mods" / GID / "cast_g1_wrestlers").exists() and not staged.exists() and not side.exists()
    assert (base / "keep.bin").read_bytes() == b"base", "the base copy is never touched"
    for other in ("g1_patch", "g1_hack", "showcase_sonic_g1"):
        assert (cfg.cache / "mods" / GID / other / ".gbox-mod.json").is_file(), f"{other} is another build"
    assert store.get("build_name", f"{GID}/cast_g1_wrestlers") is None and store.get("mod", "auto1") is None
    assert store.get("mod", "card1") is not None
    assert [a for a in store.audit_log(0, 500) if a["action"] == "build.delete"]


def test_delete_is_refused_while_a_running_game_uses_the_build_and_one_pc_only(tmp_path):
    cfg, app, store, h = fixture(tmp_path)
    store.put("session", "w1-s1", {"session_id": "w1-s1", "game_id": GID, "state": "running", "title": "G1",
                                   "mod": "g1_patch~zz", "collection_mod": "g1_patch"})
    with TestClient(app) as c:
        assert app.state.built_mods.wait(10)
        r = c.delete(f"/api/builds/{GID}/g1_patch", headers=h)
        assert r.status_code == 409 and "in use by a running game (w1-s1)" in r.json()["detail"]
        assert (cfg.cache / "mods" / GID / "g1_patch").is_dir()
        store.put("session", "w1-s1", store.get("session", "w1-s1") | {"state": "ended"})
        assert c.delete(f"/api/builds/{GID}/g1_patch?scope=node&node=nobody", headers=h).status_code == 422
        assert c.delete(f"/api/builds/{GID}/g1_patch?scope=sideways", headers=h).status_code == 422
        assert c.delete(f"/api/builds/{GID}/nope", headers=h).status_code == 404
        # only this PC: its copy goes, the Spark collection and the names stay
        out = c.post(f"/api/builds/{GID}/g1_patch/delete", headers=h, json={"scope": "node", "node": "i9-NUC"}).json()
        assert out["scope"] == "node" and out["spark"]["removed"] == [] and [j["node"] for j in out["jobs"]] == ["i9-NUC"]
        assert (cfg.cache / "mods" / GID / "g1_patch").is_dir()
        assert "g1_patch" in [m["name"] for m in get(c, h, "/api/mods/built")["items"]]


def test_offline_pcs_are_skipped_with_a_reason(tmp_path):
    cfg, app, store, h = fixture(tmp_path)
    store.put("worker", "w1", store.get("worker", "w1") | {"last_seen": time.time() - 3600})
    with TestClient(app) as c:
        assert app.state.built_mods.wait(10)
        out = c.delete(f"/api/builds/{GID}/g1_patch", headers=h).json()
    assert out["jobs"] == [] and out["skipped"][0]["node"] == "i9-NUC" and "offline" in out["skipped"][0]["reason"]
    assert not (cfg.cache / "mods" / GID / "g1_patch").exists()


def test_worker_delete_build_removes_staged_copies_and_refuses_in_use(tmp_path):
    from gbox.config import Config
    cfg = Config(data_dir=tmp_path / "data", cache_dir=tmp_path / "cache")
    root = cfg.cache / "mods" / GID
    for n in ("b", "b~1", "bb", "other"):
        (root / n).mkdir(parents=True)
        (root / n / ".gbox-mod.json").write_text("{}")
    (root / "alias").mkdir()
    (root / "alias" / filemods.STAGED_MARK).write_text("b")
    _sidecar(cfg, GID, "b")
    (cfg.cache / "modbase" / GID).mkdir(parents=True)
    with pytest.raises(filemods.ModInUse, match="in use by a running game"):
        filemods.delete_build(cfg, GID, "b", in_use=["b~1"])
    assert (root / "b").is_dir()
    assert filemods.delete_build(cfg, GID, "b", in_use=["other"]) == {"removed": ["b", "alias", "b~1"], "errors": []}
    assert sorted(p.name for p in root.iterdir()) == ["bb", "other"], "bb shares a prefix but is another build"
    assert (cfg.cache / "modbase" / GID).is_dir()


# ------------------------------------------------------------------------------------------------- ⚑ Report

def test_report_files_through_the_issue_flow_with_the_build_facts_and_pictures(tmp_path, monkeypatch):
    from gbox import hermes_task_mode
    from gbox.agent import ChatHub
    monkeypatch.setenv("GBOX_HERMES_DISPATCH_STATE", str(tmp_path / "dispatch"))     # the work queue lives here
    monkeypatch.setenv("GBOX_HERMES_HOME", str(tmp_path / "hermes"))
    monkeypatch.setattr(hermes_task_mode, "_job", lambda: {"no_agent": True, "enabled": True})
    monkeypatch.setattr(ChatHub, "post", lambda *a: (_ for _ in ()).throw(AssertionError("queued for Hermes, not a chat")))
    cfg, app, store, h = fixture(tmp_path)
    shot = store.put_artifact(b"\x89PNG in-game frame", "frame.png", "image/png", {})
    store.put("mod", "card1", store.get("mod", "card1") | {"shots": [shot.sha256]})
    (cfg.cache / "mods" / GID / "cast_g1_wrestlers" / "preview.png").write_bytes(b"\x89PNG fit")
    with TestClient(app) as c:
        assert app.state.built_mods.wait(10)
        c.post("/api/mods/built/refresh", headers=h)
        assert app.state.built_mods.wait(10)
        r = c.post(f"/api/builds/{GID}/g1_patch/report", headers=h, json={"reason": "broken", "note": "unrecognizable"})
        assert r.status_code == 200, r.text
        out = r.json()
        assert out["title"] == "Build report: g1_patch (g1): character looks broken or garbled"
        assert out["dispatch"] == "hermes_queue"
        from gbox import hermes_work_queue                       # the launch failure reports' investigation queue (#318)
        assert hermes_work_queue.get_priority()[0] == out["id"], "the report goes to the top of the Hermes work queue"
        assert any("Build report queued for Hermes" in m.get("text", "") for m in store.get("request", out["id"])["messages"])
        req = store.get("request", out["id"])
        assert req["context"]["build_report"] and req["context"]["build"] == f"{GID}/g1_patch" and req["context"]["reason"] == "broken"
        assert req["image"], "the newest in-game frame is the report's screenshot"
        body = req["body"]
        for s in ("Build: Patch card (folder g1_patch)", "unrecognizable", "Writer: ", "What this changes", "Build recipe: ", "Last launch: never launched"):
            assert s in body, s
        names = [a["name"] for m in req["messages"] for a in m.get("attachments") or []]
        assert "in-game-frame.png" in names
        row = by_name(get(c, h, "/api/builds")["items"])["g1_patch"]
        assert row["reported"]["number"] == out["number"]
        assert by_name(get(c, h, "/api/mods/built")["items"])["g1_patch"]["reported"]["id"] == out["id"]
        cast = c.post(f"/api/builds/{GID}/cast_g1_wrestlers/report", headers=h, json={"reason": "no_change"}).json()
        creq = store.get("request", cast["id"])
        assert "build-preview.png" in [a["name"] for m in creq["messages"] for a in m.get("attachments") or []]
        assert "Slots and donors: kane -> neo [built]" in creq["body"]
        assert c.post(f"/api/builds/{GID}/g1_patch/report", headers=h, json={"reason": "meh"}).status_code == 422
        assert c.post(f"/api/builds/{GID}/nope/report", headers=h, json={}).status_code == 404
    assert [a for a in store.audit_log(0, 500) if a["action"] == "build.report"]
