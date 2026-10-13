"""Build notifications (gbox/build_notify.py): the control plane posts a bell-tray entry when a job ends - a build
(mod, launch options, thumbnail, summary), a failed build (reason, retry), a collect - and nothing for launches, frames,
session ops or lists; a pass that queues many jobs shares one entry; new build folders the index finds that no job
reported; the thumbnail redirect. A fake cache, store and worker only: nothing is built, launched or captured."""
import json
import time

from fastapi.testclient import TestClient

from gbox import build_notify as B
from gbox.config import Config
from gbox.server import create_app

GID = "g1"
CAST_ROWS = [{"slot": s, "character": c, "donor": d, "status": "built"}
             for s, c, d in [("sonic", "sonic", "Sonic"), ("knux", "knuckles", "Knuckles"), ("amy", "amy", "Amy"),
                             ("gamma", "gamma", "Gamma")]]


def build_folder(cache, gid, name, meta, pictures=()):
    d = cache / "mods" / gid / name
    d.mkdir(parents=True)
    (d / ".gbox-mod.json").write_text(json.dumps({"name": name, "game_id": gid, **meta}))
    for p in pictures:
        (d / p).write_bytes(b"\x89PNG fake")
    return d


def plane(tmp_path, folders=()):
    cache = tmp_path / "cache"
    cfg = Config(data_dir=tmp_path / "data", cache_dir=cache)
    for gid, name, meta, pics in folders:
        build_folder(cache, gid, name, meta, pics)
    app = create_app(cfg)
    store = app.state.store
    store.upsert_catalog([{"game_id": GID, "title": "Sonic Adventure", "platform": "dreamcast", "source_paths": ["x.gdi"],
                          "format": "gdi", "profile_id": GID}])
    return cfg, app, store, {"Authorization": f"Bearer {cfg.token()}"}


def worker(c, h, wid="spark", os_="linux", tools=("characters", "launch_game", "get_frame", "session_op", "tasks", "file_mod")):
    c.post("/api/workers/register", headers=h, json={"id": wid, "name": wid, "os": os_, "tools": list(tools)}).raise_for_status()


def run(c, h, tool, inp, output=None, ok=True, error=None, wid="spark", submit_extra=None):
    """Submit, claim on the fake worker and post its result -> the job id."""
    j = c.post("/api/jobs", headers=h, json={"tool": tool, "input": inp, **(submit_extra or {})}).json()
    assert j.get("state") == "queued", j
    claimed = c.post(f"/api/workers/{wid}/claim", headers=h)
    assert claimed.status_code == 200 and claimed.json()["id"] == j["id"]
    r = c.post(f"/api/workers/{wid}/result", headers=h, json={"job_id": j["id"], "ok": ok, "output": output, "error": error})
    assert r.status_code == 200, r.text
    return j["id"]


def notes(c, h):
    r = c.get("/api/notify", headers=h)
    assert r.status_code == 200, r.text
    return [n for n in r.json() if n.get("auto") == "build"]


def test_build_job_posts_one_build_notification_with_mod_launch_and_thumbnail(tmp_path):
    cfg, app, store, h = plane(tmp_path, [(GID, "cast_g1_sonic", {"built": time.time(), "cast": CAST_ROWS,
                                                                  "title": "Sonic Adventure: cast as Sonic Heroes"},
                                           ["preview.png"])])
    shot = store.put_artifact(b"\x89PNG running frame", "frame.png", "image/png", {})
    store.put("mod", "card1", {"id": "card1", "title": "SA cast", "game_id": GID, "thumb": shot.sha256, "state_slot": 2,
                               "calls": [{"tool": "@launch", "input": {"mod": "cast_g1_sonic"}}], "ts": 1})
    with TestClient(app) as c:
        assert app.state.built_mods.wait(10)
        worker(c, h)
        worker(c, h, "i9-NUC", "windows", ("launch_game",))
        jid = run(c, h, "characters", {"op": "cast_swap", "target_game": GID, "source": "heroes", "launch": False},
                  {"result": {"status": "built", "mod": "cast_g1_sonic", "game_id": GID, "report": CAST_ROWS,
                              "message": "4/4 slots built into cast_g1_sonic"}})
        got = notes(c, h)
        assert len(got) == 1
        n = got[0]
        assert n["kind"] == "build" and n["mod"] == "cast_g1_sonic" and n["game_id"] == GID and n["job_id"] == jid
        assert n["title"] == "Sonic Adventure: cast as Sonic Heroes is ready" and not n["read"]
        assert n["summary"] == "4/4 slots built · Sonic, Knuckles, Amy, Gamma"
        assert n["text"] == "Sonic Adventure · 4/4 slots built · Sonic, Knuckles, Amy, Gamma"
        assert n["count"] == 1 and len(n["items"]) == 1 and n["items"][0]["node"] == "spark"
        # launch options: Play on this PC first (the default), the other PCs, the saved moment, the Spark debugger
        ids = [o["id"] for o in n["launch"]]
        assert ids[0] == "here" and n["launch"][0]["default"] and n["launch"][0]["target"] == "here"
        assert {"pc:i9-NUC", "pc:spark", "moment", "debug"} <= set(ids)
        assert n["launch"][0]["call"]["path"] == f"/api/games/{GID}/launch?node=auto&mod=cast_g1_sonic"
        # thumbnail: the mod card's frame of the build running beats the folder preview; served through a redirect
        assert n["thumbnail_source"] == "capture" and n["thumbnail"].startswith(f"/api/notify/{n['id']}/thumb?i=0")
        r = c.get(n["thumbnail"] + "&token=" + cfg.token(), follow_redirects=False)
        assert r.status_code == 307 and r.headers["location"].startswith(f"/api/artifacts/{shot.sha256}?token=")
        assert c.get(n["thumbnail"], follow_redirects=False).status_code == 401, "the picture needs the token"
        assert c.get(n["thumbnail"] + "&token=" + cfg.token()).content == b"\x89PNG running frame"
        # read / read all; the unread count drops
        assert c.post(f"/api/notify/{n['id']}/read", headers=h).json()["ok"]
        assert notes(c, h)[0]["read"] is True


def test_thumbnail_falls_back_fitting_then_build_preview_then_donor_then_box_art():
    facts = {"game_id": GID, "mod": "m", "shots": [], "folder_images": ["preview.png", "screenshot.png"],
             "artifacts": [{"sha256": "a" * 64, "name": "preview.png", "media_type": "image/png"},
                           {"sha256": "b" * 64, "name": "worker.log", "media_type": "text/plain"}],
             "fitting": ["/api/jobs/j1/fitting/files/sonic.png"], "donors": ["sonic"]}
    got = B.thumb_options(facts)
    assert [s for s, _u in got] == ["capture", "fitting", "preview", "preview", "donor", "boxart"]
    assert got[0][1] == f"/api/mods/built/{GID}/m/image/screenshot.png", "a screenshot in the build folder is a capture"
    assert got[2][1] == f"/api/mods/built/{GID}/m/image/preview.png"
    assert got[3][1] == "/api/artifacts/" + "a" * 64 and got[4][1] == "/api/characters/sonic/preview"
    assert got[-1][1] == f"/api/media/{GID}/best?w=360"
    assert [s for s, _u in B.thumb_options({"game_id": GID, "mod": "m"})] == ["boxart"]
    fit = {"fitting": {"order": ["a", "b"], "models": {"a": {"state": "running", "preview": "/api/jobs/j/fitting/files/a.png"},
                                                       "b": {"state": "done", "preview": "/api/jobs/j/fitting/files/b.png",
                                                             "snapshot": "/api/jobs/j/fitting/files/b.glb"}}}}
    assert B.fitting_previews(fit) == ["/api/jobs/j/fitting/files/b.png", "/api/jobs/j/fitting/files/a.png"]


def test_fitting_preview_is_the_thumbnail_when_nothing_ran_yet(tmp_path):
    cfg, app, store, h = plane(tmp_path)
    with TestClient(app) as c:
        worker(c, h)
        j = c.post("/api/jobs", headers=h, json={"tool": "characters", "input": {"op": "use", "character": "kane",
                                                                                 "game_id": GID, "launch": False}}).json()
        c.post("/api/workers/spark/claim", headers=h).raise_for_status()
        ev = {"model": "player", "stage": "write", "state": "done", "preview": f"/api/jobs/{j['id']}/fitting/files/kane.png"}
        c.post(f"/api/jobs/{j['id']}/progress", headers=h, json={"pct": 90, "msg": "Kane -> player: write #fit" + json.dumps(ev)})
        c.post("/api/workers/spark/result", headers=h, json={"job_id": j["id"], "ok": True, "output": {"result": {
            "status": "built", "mod": "g1_kane", "game_id": GID, "character": "Kane", "slug": "kane", "slot": "player"}}})
        n = notes(c, h)[0]
        assert n["thumbnail_source"] == "fitting" and n["summary"] == "Kane → player"
        assert n["items"][0]["thumbnail_target"] == f"/api/jobs/{j['id']}/fitting/files/kane.png"
        # no picture of any kind: the game's box art
        run(c, h, "file_mod", {"op": "build", "game_id": GID, "name": "patch1", "changes": {"a.bin": {"bytes": "x"}}},
            {"result": {"mod": "patch1", "dir": str(cfg.cache / "mods" / GID / "patch1"), "files": ["a.bin"]}})
        got = notes(c, h)
        assert len(got) == 1 and got[0]["count"] == 2, "two builds finishing within a minute share an entry"
        it = next(x for x in got[0]["items"] if x["mod"] == "patch1")
        assert it["thumbnail_source"] == "boxart" and it["thumbnail_target"] == f"/api/media/{GID}/best?w=360"
        assert it["summary"] == "1 file changed" and it["thumbnail"].startswith(f"/api/notify/{got[0]['id']}/thumb?i=1")


def test_failed_build_is_an_error_with_the_reason_and_a_retry(tmp_path):
    cfg, app, store, h = plane(tmp_path)
    with TestClient(app) as c:
        worker(c, h)
        jid = run(c, h, "characters", {"op": "use", "character": "kane", "game_id": GID, "slot": "player", "launch": False},
                  ok=False, error="writer crashed: too many bones")
        n = notes(c, h)[0]
        assert n["kind"] == "error" and n["job_id"] == jid
        assert n["title"].startswith("Build failed") and "too many bones" in n["text"] and "too many bones" in n["error"]
        assert n["retry"] == {"tool": "characters", "require_os": "linux", "input": {
            "op": "use", "character": "kane", "game_id": GID, "slot": "player", "launch": False, "rebuild": True}}
        assert n["launch"] == [], "nothing to play"
        # a build that answers a failure status (no writer for that slot) is an error too, with the tool's message
        run(c, h, "characters", {"op": "use", "character": "amy", "game_id": GID, "slot": "boss", "launch": False},
            {"result": {"status": "unsupported", "message": "no writer for the boss slot", "game_id": GID}})
        got = notes(c, h)
        assert len(got) == 1 and got[0]["title"] == "2 failed", "two failures within a minute share an entry"
        assert got[0]["items"][1]["error"] == "no writer for the boss slot" and got[0]["items"][1]["kind"] == "error"


def test_collect_posts_characters_collected(tmp_path):
    cfg, app, store, h = plane(tmp_path)
    with TestClient(app) as c:
        worker(c, h)
        run(c, h, "characters", {"op": "collect", "game_id": GID},
            {"result": {"status": "complete", "collected": 3, "total": 3, "game_id": GID, "entries": [
                {"slug": "sonic", "name": "Sonic", "verified": True}, {"slug": "tails", "name": "Tails", "verified": True},
                {"slug": "amy", "name": "Amy", "verified": True}]}})
        n = notes(c, h)[0]
        assert n["kind"] == "collect" and n["title"] == "3 characters collected from Sonic Adventure"
        assert n["summary"] == "3 collected · Sonic, Tails, Amy" and n["launch"] == []


def test_non_build_jobs_post_nothing(tmp_path):
    cfg, app, store, h = plane(tmp_path)
    game = store.catalog_get(GID)
    with TestClient(app) as c:
        worker(c, h)
        c.post("/api/character-collection/policy", headers=h, json={"enabled": False}).raise_for_status()
        run(c, h, "launch_game", {"game": game, "mod": "cast_g1_sonic"},
            {"session_id": "spark-1", "adapter": "retroarch", "capabilities": {}, "detail": {}})
        run(c, h, "characters", {"op": "list"}, {"result": {"characters": [], "mod": "nope"}})
        run(c, h, "characters", {"op": "use", "character": "kane", "game_id": GID, "launch": True},
            {"result": {"status": "launched", "mod": "g1_kane", "game_id": GID}})     # an existing build reused
        run(c, h, "characters", {"op": "cast_swap", "target_game": GID, "plan_only": True},
            {"result": {"status": "planned", "game_id": GID}})
        run(c, h, "tasks", {"op": "list"}, {"result": {"tasks": []}})
        assert notes(c, h) == []
    for tool, inp, out in [("get_frame", {"session_id": "w-1"}, {"mod": "x"}),
                           ("session_op", {"session_id": "w-1", "op": "load_state"}, {"result": {"mod": "x"}}),
                           ("re_mods", {"session_id": "w-1", "op": "apply"}, {"result": {"applied": True}})]:
        assert B.classify({"tool": tool, "input": inp, "output": out, "state": "succeeded"}) is None, tool
    assert B.classify({"tool": "launch_game", "input": {"mod": "m"}, "state": "failed", "error": "boom"}) is None
    assert B.classify({"tool": "characters", "input": {"op": "use"}, "state": "failed",
                       "error": "cancelled by the operator"}) is None


def test_generic_detection_by_result_fields_covers_new_builders():
    # a builder nobody listed: its result names a mod folder in the cache, or its op is a build op
    assert B.classify({"tool": "zz_new_writer", "input": {"op": "anything"}, "state": "succeeded",
                       "output": {"result": {"dir": "/c/mods/g9/zz_mod"}}}) == "build"
    assert B.mod_of({"dir": "/c/mods/g9/zz_mod"}) == ("g9", "zz_mod")
    assert B.classify({"tool": "rom_export", "input": {"op": "export", "game_id": "g"}, "state": "succeeded",
                       "output": {"result": {"name": "exp", "dir": "/d/exports/g/exp"}}}) == "build"
    assert B.classify({"tool": "um_mod", "input": {"op": "stage"}, "state": "failed", "error": "disk full"}) == "error"
    assert B.classify({"tool": "pso_mods", "input": {}, "state": "invalid", "error": "schema"}) == "error"
    assert B.classify({"tool": "mystery", "input": {"op": "frobnicate"}, "state": "succeeded",
                       "output": {"result": {"ok": True}}}) is None


class FakeStore:
    def __init__(self):
        self.docs, self.audits = {}, []

    def put(self, kind, id, body):
        self.docs[(kind, id)] = json.loads(json.dumps(body))

    def get(self, kind, id):
        return self.docs.get((kind, id))

    def all(self, kind, **_):
        return [v for (k, _i), v in self.docs.items() if k == kind]

    def delete(self, kind, id):
        self.docs.pop((kind, id), None)

    def catalog_get(self, gid):
        return {"title": "Game " + gid}

    def jobs(self, states=None, **_):
        return [v for v in self.all("job") if not states or v.get("state") in states]

    def audit(self, *a):
        self.audits.append(a)


def job(jid, created, mod, state="succeeded", req=None):
    return {"id": jid, "tool": "characters", "input": {"op": "use", "character": "kane", "game_id": GID}, "state": state,
            "created": created, "parent_request_id": req,
            "output": {"result": {"status": "built", "mod": mod, "game_id": GID}} if state == "succeeded" else None,
            "error": None if state == "succeeded" else "broke"}


def test_a_pass_that_queues_many_jobs_shares_one_entry():
    now = [10_000.0]
    st = FakeStore()
    nt = B.Notifier(st, clock=lambda: now[0])
    # "Rebuild all": four jobs queued together, finishing minutes apart, one failing -> one entry with the list
    for i in range(4):
        now[0] += 300
        nt.job_ended(job(f"j{i}", 9_000.0 + i * 0.01, f"mod{i}", "failed" if i == 2 else "succeeded"))
    entries = st.all("notify")
    assert len(entries) == 1
    e = entries[0]
    assert e["count"] == 4 and [i["job_id"] for i in e["items"]] == ["j0", "j1", "j2", "j3"]
    assert e["kind"] == "build" and e["title"] == "3 builds ready, 1 failed" and not e["read"]
    assert e["items"][2]["kind"] == "error" and e["items"][2]["error"] == "broke"
    # the same result again: still one item
    nt.job_ended(job("j3", 9_000.03, "mod3"))
    assert len(st.all("notify")) == 1 and st.all("notify")[0]["count"] == 4
    # one parent request's jobs, queued far apart, share an entry while it keeps finishing jobs
    now[0] += 10_000
    nt.job_ended(job("r1", now[0] - 500, "ra", req="req-1"))
    now[0] += 900
    nt.job_ended(job("r2", now[0] - 50, "rb", req="req-1"))
    assert sorted(e["count"] for e in st.all("notify")) == [2, 4]
    # unrelated builds finishing within a minute of each other share one; later ones get their own
    now[0] += 10_000
    nt.job_ended(job("a", now[0] - 900, "x1"))
    now[0] += 30
    nt.job_ended(job("b", now[0] - 400, "x2"))
    now[0] += 600
    nt.job_ended(job("c", now[0] - 100, "x3"))
    assert sorted(e["count"] for e in st.all("notify")) == [1, 2, 2, 4]
    # a non-build job posts nothing
    nt.job_ended({"id": "l", "tool": "launch_game", "input": {"mod": "x"}, "state": "succeeded", "output": {"session_id": "s"}})
    assert len(st.all("notify")) == 4


def test_new_build_folders_the_index_finds_notify_once():
    now = [50_000.0]
    st = FakeStore()
    nt = B.Notifier(st, clock=lambda: now[0])
    old = {"game_id": GID, "name": "old", "meta": {"built": 1_000.0}}
    assert nt.index_changed([old]) == [], "a cold index's first pass is old news"
    fresh = {"game_id": GID, "name": "fresh", "meta": {"built": now[0] - 60, "character": "kane", "slot": "player"}}
    stale = {"game_id": GID, "name": "copied_in", "meta": {"built": 2_000.0}}
    made = nt.index_changed([old, fresh, stale])
    assert len(made) == 1 and made[0]["mod"] == "fresh" and made[0]["items"][0]["source"] == "index"
    assert made[0]["summary"] == "kane → player"
    assert nt.index_changed([old, fresh, stale]) == []
    # the job that built it reports later: its item replaces the index's, no second entry
    nt.job_ended(job("jf", now[0] - 200, "fresh"))
    assert len(st.all("notify")) == 1 and st.all("notify")[0]["items"][0]["job_id"] == "jf"
    # a folder whose build job is still running is left to that job
    st.put("job", "run1", {"id": "run1", "tool": "characters", "state": "running",
                           "input": {"op": "cast_swap", "target_game": GID}})
    assert nt.index_changed([old, fresh, stale, {"game_id": GID, "name": "busy", "meta": {"built": now[0]}}]) == []


def test_notify_in_stays_backward_compatible(tmp_path):
    cfg, app, store, h = plane(tmp_path)
    with TestClient(app) as c:
        r = c.post("/api/notify", headers=h, json={"title": "Mario Mercenaries is ready on this PC",
                                                   "text": "RE4 with Mario", "session_id": "w-1", "kind": "ready"})
        nid = r.json()["id"]
        got = c.get("/api/notify", headers=h).json()
        assert got[0]["id"] == nid and got[0]["title"].startswith("Mario") and got[0]["session_id"] == "w-1"
        assert "auto" not in got[0]
        # a builder may post its own build entry: launch options are filled in
        c.post("/api/notify", headers=h, json={"title": "Built", "kind": "build", "game_id": GID, "mod": "m1"})
        n = c.get("/api/notify", headers=h).json()[0]
        assert n["launch"][0]["call"]["path"] == f"/api/games/{GID}/launch?node=auto&mod=m1"
        assert c.post("/api/notify/read_all", headers=h).json()["marked"] == 2
        assert all(x["read"] for x in c.get("/api/notify", headers=h).json())


def test_a_renamed_build_shows_its_official_name_in_the_tray(tmp_path):
    """#1656: the operator's display name (PATCH /api/builds/...) wins in the bell tray, older entries too; the stored
    entry keeps the writer's title, so clearing the name restores it."""
    cfg, app, store, h = plane(tmp_path, [(GID, "cast_g1_sonic", {"built": time.time(), "cast": CAST_ROWS,
                                                                  "title": "Sonic Adventure: cast as Sonic Heroes"}, [])])
    with TestClient(app) as c:
        assert app.state.built_mods.wait(10)
        worker(c, h)
        run(c, h, "characters", {"op": "cast_swap", "target_game": GID, "source": "heroes", "launch": False},
            {"result": {"status": "built", "mod": "cast_g1_sonic", "game_id": GID, "report": CAST_ROWS}})
        assert notes(c, h)[0]["title"] == "Sonic Adventure: cast as Sonic Heroes is ready"
        assert c.patch(f"/api/builds/{GID}/cast_g1_sonic", headers=h, json={"display_name": "TTS Sonic Full Cast"}).status_code == 200
        n = notes(c, h)[0]
        assert n["title"] == "TTS Sonic Full Cast is ready" and n["mod_title"] == "TTS Sonic Full Cast"
        assert n["items"][0]["mod_title"] == "TTS Sonic Full Cast"
        assert store.get("notify", n["id"])["items"][0]["mod_title"] == "Sonic Adventure: cast as Sonic Heroes"
        c.patch(f"/api/builds/{GID}/cast_g1_sonic", headers=h, json={"display_name": ""})
        assert notes(c, h)[0]["title"] == "Sonic Adventure: cast as Sonic Heroes is ready"
