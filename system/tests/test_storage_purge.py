"""storage_purge (gbox/storage_purge.py, operator 2026-10-26): a PC's cache keeps favorites, games played there within
unplayed_days, builds the operator downloaded / played / built there, and anything a running game or a save holds;
the rest (unplayed games, builds sent automatically) is listed by the dry run and deleted only from its reviewed list.
Plus the control plane's facts, the route, the job's permit at claim, and the build-download receipt. Synthetic files."""
import json
import os
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from gbox import built_mods, filemods, storage_policy as SP, storage_purge as SPG
from gbox.config import Config
from gbox.models import CatalogEntry
from gbox.server import create_app

DAY = 86400
G_FAV, G_RECENT, G_OLD, G_NEVER, G_RUN, G_SAVE, G_KEEP, G_RB = (f"{'a' * 15}{i}" for i in range(1, 9))
HOST = "I9-NUC"


class Ctx(SimpleNamespace):
    def progress(self, pct, msg):
        self.log.append((pct, msg))


def write(p: Path, data: bytes = b"x" * 1000) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def build(cache: Path, gid: str, name: str, *, arrived: float, files=None, meta=None, staged_of: str = "") -> Path:
    d = cache / "mods" / gid / name
    for rel, data in (files or {"game.iso": b"b" * 2000}).items():
        write(d / rel, data)
    if staged_of:
        (d / filemods.STAGED_MARK).write_text(staged_of)
    marker = d / ".gbox-mod.json"
    marker.write_text(json.dumps({"name": staged_of or name, "game_id": gid, **(meta or {})}))
    os.utime(marker, (arrived, arrived))
    return d


def rig(tmp_path, now):
    cache = tmp_path / "cache"
    for gid in (G_FAV, G_RECENT, G_NEVER, G_RUN):
        write(cache / gid / "game.iso")
    write(cache / G_OLD / "game.iso", b"o" * 5000)
    write(cache / G_SAVE / "game.iso")
    write(cache / G_SAVE / "saves" / "slot.srm", b"s")
    write(cache / "g1" / "Game (USA).iso")                                    # a staged copy known to the stage db
    (cache / ".gbox-staged.json").write_text(json.dumps({str(cache / "g1" / "Game (USA).iso"): {"sha1": "x"}}))
    write(cache / "research" / "notes.txt")                                   # not a game: never listed
    write(cache / "characters" / "kane" / "meta.json")
    write(cache / "dc" / G_OLD / "disc.gdi", b"d" * 100)
    base = write(cache / "modbase" / G_OLD / "disc.iso", b"B" * 4000)
    write(cache / "modbase" / G_KEEP / "disc.iso", b"K" * 3000)
    old = now - 30 * DAY
    cast_old = build(cache, G_OLD, "cast_old", arrived=old, files={"game.iso": b"c" * 1500})
    os.link(base, cast_old / "disc.iso")                                      # a folder mod hard-links its base copy
    (cast_old.parent / ".cast_old.sha256.json").write_text("{}")
    build(cache, G_OLD, "cast_old~ab12", arrived=old, staged_of="cast_old")
    for name in ("cast_fav", "cast_dl", "cast_local_receipt", "cast_played", "local_only"):
        build(cache, G_KEEP, name, arrived=old)
    build(cache, G_KEEP, "built_here", arrived=old, meta={"built_on": {"host": HOST.lower(), "os": "windows"}})
    build(cache, G_KEEP, "cast_new", arrived=now - 2 * DAY)
    build(cache, G_RB, "cast_running", arrived=old)
    build(cache, G_RB, "cast_running~zz", arrived=old, staged_of="cast_running")
    cfg = SimpleNamespace(cache=cache, cold_cache=None, data_dir=tmp_path / "data", runtime=tmp_path / "runtime",
                          builds=SimpleNamespace(auto_send=False))
    SP.write_local_receipt(cfg, G_KEEP, "cast_local_receipt")
    facts = SPG.PurgeFacts(
        pc="i9-NUC", sources=["central"], favorite_games=[G_FAV], favorite_builds=[f"{G_KEEP}/cast_fav"],
        receipts=[f"{G_KEEP}/cast_dl"], played={G_RECENT: now - 2 * DAY, G_OLD: now - 30 * DAY},
        played_builds={f"{G_KEEP}/cast_played": now - 3 * DAY},
        collection=[f"{G_OLD}/cast_old"] + [f"{G_KEEP}/{n}" for n in ("cast_fav", "cast_dl", "cast_local_receipt",
                                                                      "cast_played", "built_here", "cast_new")]
                   + [f"{G_RB}/cast_running"], titles={G_OLD: "Old Game"})
    sessions = {"w1-j1": (None, {"game_id": G_RUN, "mod": "", "_rom_path": str(cache / G_RUN / "game.iso")}),
                "w1-j2": (None, {"game_id": G_RB, "mod": "cast_running~zz"})}
    return cfg, facts, sessions


def folders(rows):
    return {r["folder"]: r for r in rows}


def run(cfg, facts, sessions, now, **kw):
    ctx = Ctx(config=cfg, log=[], job_id="j", server=None)
    inp = SPG.StoragePurgeIn(facts=facts, **kw)
    return SPG.run(inp, ctx, sessions=sessions, copies=[], now=now, host=HOST, os_name="windows"), ctx


def test_dry_run_lists_unplayed_games_and_automatically_sent_builds_and_why_the_rest_stays(tmp_path):
    now = time.time()
    cfg, facts, sessions = rig(tmp_path, now)
    out, ctx = run(cfg, facts, sessions, now)
    items, kept = folders(out["items"]), folders(out["kept"])
    assert set(items) == {G_OLD, f"dc/{G_OLD}", f"modbase/{G_OLD}", G_NEVER, "g1",
                          f"mods/{G_OLD}/cast_old", f"mods/{G_OLD}/cast_old~ab12"}
    assert items[G_OLD]["title"] == "Old Game" and items[G_OLD]["kind"] == "game"
    assert items[G_OLD]["last_played"] == pytest.approx(now - 30 * DAY)
    assert "not played on i9-NUC for 14+ days (last played" in items[G_OLD]["reason"]
    assert "never played there" in items[G_NEVER]["reason"]
    assert items[f"mods/{G_OLD}/cast_old"]["kind"] == "build" and items[f"mods/{G_OLD}/cast_old"]["build"] == "cast_old"
    assert items[f"mods/{G_OLD}/cast_old"]["reason"].startswith("sent automatically (no operator download)")
    assert items[f"mods/{G_OLD}/cast_old~ab12"]["part"] == "staged copy of the build"
    assert items[f"dc/{G_OLD}"]["part"] == "Dreamcast disc extract"
    reasons = {k: v["reason"] for k, v in kept.items()}
    assert reasons[G_FAV] == "favorite"
    assert reasons[G_RECENT].startswith("played on i9-NUC 2 days ago")
    assert reasons[G_RUN] == "a running game uses it"
    assert reasons[G_SAVE].startswith("holds save data (saves")
    assert reasons[f"modbase/{G_KEEP}"] == "the base copy of builds kept on this PC"
    assert reasons[f"mods/{G_KEEP}/cast_fav"] == "favorite build"
    assert reasons[f"mods/{G_KEEP}/cast_dl"] == reasons[f"mods/{G_KEEP}/cast_local_receipt"] == "downloaded by the operator"
    assert reasons[f"mods/{G_KEEP}/cast_played"].startswith("played on i9-NUC 3 days ago")
    assert reasons[f"mods/{G_KEEP}/built_here"] == "built on this PC (the only copy)"
    assert reasons[f"mods/{G_KEEP}/local_only"].startswith("not in the Spark collection")
    assert "newer than 14 days" in reasons[f"mods/{G_KEEP}/cast_new"]
    assert reasons[f"mods/{G_RB}/cast_running"] == reasons[f"mods/{G_RB}/cast_running~zz"] == "a running game uses it"
    assert not any("research" in f or "characters" in f for f in list(items) + list(kept)), "not games: never listed"
    t = out["totals"]
    assert t["items"] == 7 and t["bytes"] == sum(r["size"] for r in out["items"])
    assert t["freed_bytes"] == t["bytes"] - 4000, "the base disc hard-linked into the build is freed once"
    assert t["by_kind"]["build"]["items"] == 2 and t["by_kind"]["game"]["items"] == 5
    assert out["dry_run"] and all(Path(r["path"]).exists() for r in out["items"]), "a dry run deletes nothing"
    assert out["pc"] == "i9-NUC" and out["roots"]["cache"] == str(cfg.cache) and not out["warnings"]
    assert ctx.log[-1][0] == 100 and "can be freed (dry run)" in ctx.log[-1][1]


def test_a_shared_base_is_not_counted_as_freed_unless_every_link_goes(tmp_path):
    now = time.time()
    cfg, facts, sessions = rig(tmp_path, now)
    plan = SPG.plan(cfg, facts, sessions=sessions, copies=[], now=now, host=HOST, os_name="windows")
    mod = [c for c in plan["items"] if c.folder == f"mods/{G_OLD}/cast_old"]
    base = [c for c in plan["items"] if c.folder == f"modbase/{G_OLD}"]
    assert SPG.freed_bytes(mod) == mod[0].size - 4000 and SPG.freed_bytes(mod + base) == mod[0].size + base[0].size - 4000


def test_delete_removes_only_the_reviewed_paths_that_are_still_eligible(tmp_path):
    now = time.time()
    cfg, facts, sessions = rig(tmp_path, now)
    dry, _ = run(cfg, facts, sessions, now)
    keep_never = str(cfg.cache / G_NEVER)
    reviewed = [r["path"] for r in dry["items"] if r["path"] != keep_never]
    out, ctx = run(cfg, facts, sessions, now, dry_run=False,
                   paths=reviewed + [str(cfg.cache / G_FAV), str(cfg.cache / "nothing-here")])
    gone = folders(out["items"])
    assert set(gone) == set(folders(dry["items"])) - {G_NEVER} and all(r["deleted"] for r in out["items"])
    for r in out["items"]:
        assert not os.path.lexists(r["path"]), r["path"]
    assert (cfg.cache / G_NEVER / "game.iso").exists(), "not in the reviewed list: stays"
    skipped = {Path(s["path"]).name: s["reason"] for s in out["skipped"]}
    assert skipped == {G_FAV: "favorite", "nothing-here": "not found in this PC's cache any more"}
    for kept in (G_FAV, G_RECENT, G_RUN, G_SAVE, f"modbase/{G_KEEP}", f"mods/{G_KEEP}/cast_dl", f"mods/{G_RB}/cast_running"):
        assert (cfg.cache / kept).exists(), kept
    assert json.loads((cfg.cache / ".gbox-staged.json").read_text()) == {}, "the stage db forgets the deleted copy"
    assert not (cfg.cache / "mods" / G_OLD / ".cast_old.sha256.json").exists(), "the build's hash sidecar went with it"
    assert not any((cfg.cache / SPG.TRASH).iterdir()) if (cfg.cache / SPG.TRASH).exists() else True
    assert out["totals"]["deleted"] == len(gone) and not out["dry_run"]
    assert (cfg.cache / "research" / "notes.txt").exists() and (cfg.cache / "characters" / "kane").exists()


def test_deleting_needs_a_reviewed_list_and_the_sparks_facts(tmp_path):
    now = time.time()
    cfg, facts, sessions = rig(tmp_path, now)
    with pytest.raises(ValueError, match="reviewed list"):
        run(cfg, facts, sessions, now, dry_run=False)
    local = facts.model_copy(update={"sources": ["local"], "collection": []})
    with pytest.raises(ValueError, match="Spark's facts"):
        run(cfg, local, sessions, now, dry_run=False, paths=[str(cfg.cache / G_NEVER)])
    preview, _ = run(cfg, local, sessions, now)
    assert any("preview only" in w for w in preview["warnings"])
    assert not [r for r in preview["items"] if r["kind"] == "build"], "no build is provably a copy without the Spark"


def test_a_game_started_after_the_plan_is_left_whole(tmp_path):
    now = time.time()
    cfg, facts, sessions = rig(tmp_path, now)
    live = dict(sessions)

    class Late(dict):
        calls = 0

        def values(self):
            Late.calls += 1                                                   # 1st call: the plan; then a game starts
            return list(live.values()) + ([(None, {"game_id": G_NEVER})] if Late.calls > 1 else [])
    out, _ = run(cfg, facts, Late(live), now, dry_run=False, paths=[str(cfg.cache / G_NEVER)])
    assert out["items"] == [] and out["skipped"] == [{"path": str(cfg.cache / G_NEVER), "reason": "a running game uses it"}]
    assert (cfg.cache / G_NEVER / "game.iso").exists()


def test_an_open_file_keeps_its_folder(tmp_path):
    now = time.time()
    cfg, facts, sessions = rig(tmp_path, now)
    with open(cfg.cache / G_NEVER / "game.iso", "rb"):
        out = SPG.run(SPG.StoragePurgeIn(facts=facts, dry_run=False, paths=[str(cfg.cache / G_NEVER)]),
                      Ctx(config=cfg, log=[], job_id="j", server=None), sessions=sessions, copies=[], now=now, host=HOST)
    if os.name != "nt" and not os.path.isdir("/proc"):
        pytest.skip("no open-file probe on this platform")
    assert out["items"] == [] and out["skipped"][0]["reason"].startswith("in use")
    assert (cfg.cache / G_NEVER / "game.iso").exists()


def test_linux_nodes_never_purge_builds_and_the_cold_tier_is_followed(tmp_path):
    now = time.time()
    cfg, facts, sessions = rig(tmp_path, now)
    cold = tmp_path / "cold"
    write(cold / G_NEVER.replace("4", "b") / "game.iso", b"z" * 700)        # a cold-only copy ("unlinked")
    linked = G_NEVER.replace("4", "c")
    write(cold / linked / "game.iso", b"y" * 600)
    try:
        os.symlink(str(cold / linked), str(cfg.cache / linked), target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("this machine cannot create directory symlinks")
    cfg.cold_cache = cold
    p = SPG.plan(cfg, facts, sessions=sessions, copies=[], now=now, host="lilspark", os_name="linux")
    rows = {c.folder: c for c in p["items"]}
    assert not [c for c in p["items"] + p["kept"] if c.kind == "build"]
    assert any("central collection" in w for w in p["warnings"])
    assert rows[linked].tier == "cold" and rows[linked].size == 600 and rows[G_NEVER.replace("4", "b")].tier == "unlinked"
    assert f"modbase/{G_OLD}" not in rows, "the base builds link to stays where builds are not purged"
    assert SPG.delete(rows[linked], windows=os.name == "nt", hot=cfg.cache, busy=[]) is None
    assert not os.path.lexists(cfg.cache / linked) and not (cold / linked).exists(), "the cold copy and its link"


# ------------------------------------------------------------------------------------------------ control plane

def fresh():
    return {"sampled_at": time.time(), "cpu_percent": 10, "memory_percent": 40, "memory_available_bytes": 32 << 30, "gpus": []}


def app_with_pc(tmp_path, tools=("storage_purge", "echo_artifact")):
    cfg = Config(data_dir=tmp_path / "data", cache_dir=tmp_path / "cache")
    app = create_app(cfg)
    store = app.state.store
    store.upsert_catalog([CatalogEntry(game_id=g, title=t, platform="ps2", source_paths=[], format="iso", profile_id=g).model_dump()
                          for g, t in ((G_FAV, "Fav Game"), (G_OLD, "Old Game"), (G_RECENT, "Recent Game"))])
    store.set_favorite(G_FAV, True)
    store.put(built_mods.FAV_KIND, f"{G_KEEP}/cast_fav", {"key": f"{G_KEEP}/cast_fav", "by": "operator", "ts": 1})
    store.put("worker", "wnew", {"id": "wnew", "name": "i9-NUC", "os": "windows", "last_seen": time.time(),
                                 "tools": list(tools), "unavailable": {}, "idle_seconds": 3600, "resources": fresh()})
    store.put("worker_alias", "wold", {"to": "wnew", "name": "i9-NUC"})
    return cfg, app, store, {"Authorization": f"Bearer {cfg.token()}"}


def test_facts_come_from_the_operators_sessions_on_that_pc(tmp_path):
    cfg, app, store, h = app_with_pc(tmp_path)
    now = time.time()

    def played(sid, gid, started, actor=None, agent_use=False, **kw):
        store.put("session", sid, {"session_id": sid, "game_id": gid, "title": gid, "started": started, "state": "ended", **kw})
        if actor:
            jid = sid.split("-", 1)[1]
            store.put("job", jid, {"id": jid, "actor": actor, "agent_use": agent_use, "tool": "launch_game"})
    played("wold-j1", G_OLD, now - 30 * DAY, "operator")                         # an earlier worker id of this PC
    played("wnew-j2", G_RECENT, now - DAY, "operator", collection_mod="cast_x~ab")
    played("wnew-j3", "agentgame", now, "mcp", agent_use=True)                    # an agent's test session
    played("wnew-j4", "autorelaunch", now, "gbox-auto")                           # a launch-failure relaunch
    played("other-j5", "elsewhere", now, "operator", detail={"worker_name": "JAYBUILTFINALE"})
    played("zz-j6", G_SAVE, now - 5, detail={"worker_name": "i9-NUC"})            # its launch job is gone: still counts
    SP.record_receipt(store, "i9-NUC", G_KEEP, "cast_dl")
    store.put("job", "j7", {"id": "j7", "tool": "build_local", "input": {"op": "download", "game_id": G_KEEP, "name": "old_dl"},
                            "state": "succeeded", "worker_id": "wold", "actor": "operator", "agent_use": False})
    store.put("job", "j8", {"id": "j8", "tool": "build_local", "input": {"op": "download", "game_id": G_KEEP, "name": "agent_dl"},
                            "state": "succeeded", "worker_id": "wnew", "actor": "mcp", "agent_use": True})
    f = SPG.compute_facts(store, {"id": "wnew", "name": "i9-NUC"}, central=True, collection=[f"{G_OLD}/cast_old"])
    assert f["pc"] == "i9-NUC" and f["sources"] == ["central"] and f["collection"] == [f"{G_OLD}/cast_old"]
    assert f["favorite_games"] == [G_FAV] and f["favorite_builds"] == [f"{G_KEEP}/cast_fav"]
    assert f["receipts"] == [f"{G_KEEP}/cast_dl", f"{G_KEEP}/old_dl"], "receipts + the operator's earlier downloads"
    assert set(f["played"]) == {G_OLD, G_RECENT, G_SAVE}, "agents, automatic relaunches and other PCs do not count"
    assert f["played"][G_OLD] == pytest.approx(now - 30 * DAY)
    assert f["played_builds"] == {f"{G_RECENT}/cast_x": pytest.approx(now - DAY)}
    assert f["titles"][G_FAV] == "Fav Game"
    local = SPG.compute_facts(store, {"id": "wnew", "name": "i9-NUC"}, central=False, collection=["x/y"])
    assert local["sources"] == ["local"] and local["collection"] == []


def test_the_spark_replaces_client_facts_and_a_desktop_adds_its_own(tmp_path):
    cfg, app, store, h = app_with_pc(tmp_path)
    w = store.get("worker", "wnew")
    evil = {"facts": {"favorite_games": ["planted"], "collection": ["planted/build"], "sources": ["central"]}}
    central = SPG.prepare_input(app, store, dict(evil), w, {})["facts"]
    assert central["favorite_games"] == [G_FAV] and "planted/build" not in central["collection"]
    assert central["sources"] == ["central"]
    app.state.desktop_worker = object()                                         # now a desktop's local authority
    relayed = SPG.prepare_input(app, store, {"facts": {"favorite_games": ["cfav"], "collection": ["k/b"], "sources": ["central"],
                                                       "pc": "i9-NUC", "played": {"x": 5}}},
                                w, {"central_parent_request_id": None})["facts"]
    assert relayed["collection"] == ["k/b"] and set(relayed["favorite_games"]) == {"cfav", G_FAV}
    assert relayed["sources"] == ["central", "local"] and relayed["played"]["x"] == 5
    asked_here = SPG.prepare_input(app, store, dict(evil), w, {"via": "http"})["facts"]
    assert asked_here["sources"] == ["local"] and asked_here["collection"] == [], "a local request never allows deleting"
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as e:
        SPG.prepare_input(app, store, {}, None, {})
    assert e.value.status_code == 422


def test_route_queues_the_tool_on_the_named_pc_and_returns_its_newest_result(tmp_path):
    cfg, app, store, h = app_with_pc(tmp_path)
    with TestClient(app) as c:
        assert c.post("/api/workers/ghost/storage-purge", headers=h, json={}).status_code == 404
        r = c.post("/api/workers/i9-NUC/storage-purge", headers=h, json={"dry_run": False})
        assert r.status_code == 422 and "reviewed list" in r.json()["detail"]
        r = c.post("/api/workers/i9-NUC/storage-purge", headers=h, json={"unplayed_days": 21})
        assert r.status_code == 200, r.text
        job = store.get("job", r.json()["job_id"])
        assert job["tool"] == "storage_purge" and job["require_worker"] == "wnew" and job["state"] == "queued"
        assert job["input"]["dry_run"] is True and job["input"]["unplayed_days"] == 21
        assert job["input"]["facts"]["pc"] == "i9-NUC" and job["input"]["facts"]["favorite_games"] == [G_FAV]
        assert job["input"]["facts"]["sources"] == ["central"]
        # the generic job API (MCP job_storage_purge) gets the same facts, and must name a PC
        r = c.post("/api/jobs", headers=h, json={"tool": "storage_purge", "input": {"dry_run": True}})
        assert r.status_code == 422 and "require_worker" in r.json()["detail"]
        r = c.post("/api/jobs", headers=h, json={"tool": "storage_purge", "input": {"dry_run": True}, "require_worker": "i9-NUC"})
        assert r.status_code == 200 and store.get("job", r.json()["id"])["input"]["facts"]["pc"] == "i9-NUC"
        assert c.get("/api/workers/i9-NUC/storage-purge", headers=h).status_code == 404
        # the worker claims the dry run and answers: the PC's newest result is remembered for the menu
        claimed = c.post("/api/workers/wnew/claim", headers=h, json={"idle_seconds": 0, "active_jobs": 0}).json()
        assert claimed["tool"] == "storage_purge" and claimed["build_permit"]["operator"] is True
        out = {"dry_run": True, "pc": "i9-NUC", "unplayed_days": 14, "include": ["games", "builds"],
               "items": [{"kind": "game", "game": G_OLD, "title": "", "path": "D:/gBox/cache/" + G_OLD, "size": 7 << 30}],
               "kept": [], "skipped": [], "totals": {"items": 1, "bytes": 7 << 30, "freed_bytes": 7 << 30}, "roots": {},
               "system_drive": [], "warnings": []}
        r = c.post("/api/workers/wnew/result", headers=h, json={"job_id": claimed["id"], "ok": True, "output": out})
        assert r.status_code == 200, r.text
        assert store.get("job", claimed["id"])["state"] == "succeeded"
        got = c.get("/api/workers/i9-NUC/storage-purge", headers=h).json()
        assert got["job_id"] == claimed["id"] and got["items"][0]["title"] == "Old Game" and got["deletable"] is True
        assert c.get(f"/api/workers/i9-NUC/storage-purge?job_id={claimed['id']}", headers=h).json()["job_id"] == claimed["id"]
        row = next(w for w in c.get("/api/testing/workers", headers=h).json()["workers"] if w["name"] == "i9-NUC")
        assert row["storage"]["freed_bytes"] == 7 << 30 and row["storage"]["dry_run"] is True
        assert row["storage"]["job_id"] == claimed["id"]
        store.put("worker", "wnew", store.get("worker", "wnew") | {"tools": ["echo_artifact"]})   # not updated yet
        r = c.post("/api/workers/i9-NUC/storage-purge", headers=h, json={})
        assert r.status_code == 409 and "rebuild & relaunch" in r.json()["detail"]
        store.put("worker", "wnew", store.get("worker", "wnew") | {"last_seen": 1.0})
        assert c.post("/api/workers/i9-NUC/storage-purge", headers=h, json={}).status_code == 409


def test_claim_hands_the_worker_its_build_permit(tmp_path):
    cfg, app, store, h = app_with_pc(tmp_path)
    SP.record_receipt(store, "i9-NUC", "g1", "b1")
    with TestClient(app) as c:
        for actor, operator in ((None, True), ("hermes", False), ("gbox-auto", False), ("gbox-agent", True)):
            hh = h | ({"x-gbox-actor": actor} if actor else {})
            store.put("worker", "wnew", store.get("worker", "wnew") | {"resources": fresh(), "last_seen": time.time()})
            jid = c.post("/api/jobs", headers=hh, json={"tool": "echo_artifact", "input": {"message": "hi"},
                                                        "require_worker": "wnew"}).json()["id"]
            got = c.post("/api/workers/wnew/claim", headers=h, json={"idle_seconds": 9999, "active_jobs": 0})
            assert got.status_code == 200, got.text
            body = got.json()
            assert body["id"] == jid and body["build_permit"] == {"operator": operator, "auto_send": False,
                                                                   "receipts": ["g1/b1"]}, actor
            assert "build_permit" not in store.get("job", jid), "handed over, never stored"
            store.put("job", jid, store.get("job", jid) | {"state": "succeeded"})


def test_the_operators_download_leaves_a_receipt_and_a_deletion_takes_it_away(tmp_path):
    from tests.test_builds import GID, fixture
    cfg, app, store, h = fixture(tmp_path)
    w = store.get("worker", "w1")
    store.put("worker", "w1", w | {"tools": ["characters", "build_local", "file_mod"]})
    with TestClient(app) as c:
        assert app.state.built_mods.wait(10)
        r = c.post(f"/api/builds/{GID}/g1_patch/local", headers=h, json={"op": "download", "node": "i9-NUC"})
        assert r.status_code == 200 and r.json()["receipt"] is True
        assert SP.receipt_keys(store, "i9-NUC") == [f"{GID}/g1_patch"]
        r = c.post(f"/api/builds/{GID}/cast_g1_wrestlers/local", headers=h | {"x-gbox-actor": "mcp"},
                   json={"op": "download", "node": "i9-NUC"})
        assert r.status_code == 200 and r.json()["receipt"] is False, "an agent's call is no opt-in"
        r = c.post(f"/api/builds/{GID}/g1_patch/local", headers=h, json={"op": "locate", "node": "i9-NUC"})
        assert r.json()["receipt"] is False
        assert SP.receipt_keys(store, "i9-NUC") == [f"{GID}/g1_patch"]
        r = c.post(f"/api/builds/{GID}/g1_patch/delete", headers=h, json={"scope": "node", "node": "i9-NUC"})
        assert r.status_code == 200, r.text
        assert SP.receipt_keys(store, "i9-NUC") == []


def test_build_local_download_writes_the_pc_receipt_only_for_the_operator(tmp_path, monkeypatch):
    from gbox import tools as T
    from tests.test_build_local import build as mk_build, cfg as mk_cfg

    def fake_stage(config, server, headers, gid, name, progress=None):
        mk_build(tmp_path, {"game.iso": b"x" * 64}, {"image": "game.iso"}, name=name)
        return name
    monkeypatch.setattr(filemods, "stage", fake_stage)
    c = mk_cfg(tmp_path)
    ctx = SimpleNamespace(config=c, server="http://spark", headers={}, job_id="j1", actor="operator", agent_use=False,
                          build_permit={"operator": True, "auto_send": False, "receipts": []}, progress=lambda *a: None)
    out = T.build_local(T.BuildLocalIn(op="download", game_id="g1", name="b1"), ctx)["result"]
    assert out["receipt"] is True and SP.has_local_receipt(c, "g1", "b1")
    agent = SimpleNamespace(**{**vars(ctx), "actor": "hermes", "agent_use": True,
                               "build_permit": {"operator": False, "auto_send": False, "receipts": []}})
    out = T.build_local(T.BuildLocalIn(op="download", game_id="g1", name="b2"), agent)["result"]
    assert out["receipt"] is False and not SP.has_local_receipt(c, "g1", "b2")


def test_cache_tiers_never_move_units_for_the_purge():
    from gbox import cache_tiers
    t = cache_tiers.Tiers.__new__(cache_tiers.Tiers)
    t.keys_in = lambda raw: pytest.fail("the purge's facts must not name units to move")
    assert cache_tiers.Tiers.promote_for(t, "storage_purge", {"facts": {"favorite_games": [G_FAV]}}) == []


def test_launch_failures_skip_storage_policy_refusals():
    from gbox import launch_failures as LF
    led = LF.Ledger.__new__(LF.Ledger)
    led.store = SimpleNamespace(get=lambda *a: None)
    job = {"tool": "launch_game", "state": "failed",
           "error": "BuildNotOptedIn: build cast_a would have to be copied onto i9-NUC, but the operator has not downloaded it there."}
    assert "storage policy" in led.skip_reason(job)


def test_an_agents_dry_run_skips_idle_admission_but_its_deletion_waits_for_it():
    from gbox import background_testing as B
    assert not B.requires_admission({"tool": "storage_purge", "agent_use": True, "input": {"dry_run": True}})
    assert B.requires_admission({"tool": "storage_purge", "agent_use": True, "input": {"dry_run": False, "paths": ["x"]}})
    assert not B.requires_admission({"tool": "storage_purge", "agent_use": False, "input": {"dry_run": False}})
