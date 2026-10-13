"""The Sonic showcase (gbox/sonic_showcase.py): title selection, idle gating, plan-hash reuse, the disk budget's LRU
eviction (showcase builds only), the writer-missing path into Hermes's readiness queue, dedupe, rate / pause / storage
limits, and the API. Everything runs on fakes: no worker, no writer, no disc."""
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from gbox import cast_swap as CS, hermes_work_queue as Q, sonic_showcase as SS
from gbox.config import HOST_OS, ShowcaseConfig
from gbox.store import Store

SPARK = {"id": "spark1", "name": "lilspark", "os": "linux"}
PC = {"id": "pc1", "name": "JAYPC", "os": "windows"}


def gid(n: int) -> str:
    return f"{n:016x}"


def entry(n, title, platform="dreamcast"):
    return {"game_id": gid(n), "library": "lib", "title": title, "platform": platform, "system": "", "collections": []}


SONIC_CHARS = [
    {"slug": "sa1_sonic", "name": "Sonic", "kind": "character",
     "source": {"game_title": "Sonic Adventure", "platform": "dreamcast", "game_id": gid(900)}},
    {"slug": "sa2_shadow", "name": "Shadow", "kind": "character",
     "source": {"game_title": "Sonic Adventure 2", "platform": "dreamcast", "game_id": gid(901)}},
]


class Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOX_HERMES_DISPATCH_STATE", str(tmp_path / "hermes"))
    store = Store(tmp_path / "data")
    hdd = tmp_path / "hdd"
    cache = hdd / "gbox-cache"
    (cache / "mods").mkdir(parents=True)
    cfg = SimpleNamespace(cache=cache, data_dir=tmp_path / "data",
                          showcase=ShowcaseConfig(enabled=True, hdd_root={HOST_OS: str(hdd)}, min_free_gb=0))
    submitted = []

    def submit(req):
        job = {"id": f"job{len(submitted)}", "state": "queued", "created": clock(), **req}
        submitted.append(job)
        store.put("job", job["id"], job)
        return job
    clock = Clock()
    svc = SS.Showcase(store, cfg, submit, lambda: [SPARK, PC], clock=clock)
    svc.is_mount = lambda p: True
    svc.disk_free = lambda p: 10 ** 13
    writers = {}
    svc.writer_of = lambda g: writers.get(g["game_id"])
    svc.slot_rows = lambda g: [{"slot": "player", "kind": "player"}, {"slot": "beat", "kind": "character"}]
    svc.chars = lambda: SONIC_CHARS
    plans = {}

    def planner(g, spec):
        rows = plans.get(g["game_id"]) or [("player", "sa1_sonic"), ("beat", "sa2_shadow")]
        return {"status": "planned", "strategy": "chain", "refused": [],
                "assignments": [{"slot": s, "slot_name": s, "character": c, "donor": c.split("_")[1].title(),
                                 "preview_url": f"/api/characters/{c}/preview"} for s, c in rows]}
    svc.planner = planner
    svc.fingerprint = lambda g: {"summary": f"engine of {g['title']}", "source": "files", "start_from": "gbox.jgr"}
    return SimpleNamespace(store=store, cfg=cfg, svc=svc, submitted=submitted, clock=clock, writers=writers,
                           plans=plans, mods=cache / "mods", tmp=tmp_path)


def finish_job(env, job, game_id, mod, rows=None, plan=None):
    """What the Spark worker + cast_swap.build leave behind: the mod folder with its marker, the finished job."""
    rows = rows or [("player", "sa1_sonic"), ("beat", "sa2_shadow")]
    d = env.mods / game_id / mod
    d.mkdir(parents=True, exist_ok=True)
    (d / "disc.gdi").write_bytes(b"x" * 1000)
    digest = plan or CS.plan_digest([{"slot": s, "character": c} for s, c in rows])
    (d / ".gbox-mod.json").write_text(json.dumps({"name": mod, "game_id": game_id, "cast_plan": digest,
                                                  "built": env.clock(), "showcase": {"source": "sonic", "plan": digest}}))
    j = env.store.get("job", job["id"])
    j.update(state="succeeded", started=env.clock() - 40, finished=env.clock(),
             output={"result": {"status": "built", "mod": mod,
                                "report": [{"slot": s, "slot_name": s, "character": c, "donor": c, "status": "built"}
                                           for s, c in rows]}},
             fitting={"order": ["player"], "models": {"player": {"label": "Sonic -> player", "preview": "/api/artifacts/" + "a" * 64,
                                                                 "state": "done"}}})
    env.store.put("job", j["id"], j)


# ------------------------------------------------------------------------------------------------- selection

def test_favorites_first_then_recently_played_with_caps(env):
    s = env.store
    s.upsert_catalog([entry(1, "Jet Grind Radio"), entry(2, "Crazy Taxi"), entry(3, "Phantasy Star Online"),
                      entry(4, "Def Jam Vendetta", "ps2"), entry(5, "Shenmue"), entry(6, "Soul Calibur")])
    s.set_favorite(gid(1), True)
    s.set_favorite(gid(2), True)
    s.catalog_update(gid(2), last_played=500)       # the favorite played last comes first
    s.catalog_update(gid(1), last_played=100)
    for n, t in ((3, 900), (4, 800), (5, 700), (6, 600)):
        s.catalog_update(gid(n), last_played=t)
    picked = SS.select_titles(s, {"favorites": 25, "recent": 2})
    assert [g["game_id"] for g in picked] == [gid(2), gid(1), gid(3), gid(4)]
    assert [g["origin"] for g in picked] == ["favorite", "favorite", "recent", "recent"]
    assert [g["game_id"] for g in SS.select_titles(s, {"favorites": 1, "recent": 0})] == [gid(2)]


def test_donor_games_are_never_swapped(env):
    env.store.upsert_catalog([entry(7, "Sonic Adventure 2"), entry(8, "Sonic Adventure")])
    env.store.set_favorite(gid(7), True)
    env.store.set_favorite(gid(8), True)
    env.writers[gid(7)] = env.writers[gid(8)] = {"writer": "gbox.jgr_swap", "routed": True}
    st = env.svc.tick()
    assert {q["stage"] for q in st["queue"]} == {"donor_game"} and not env.submitted


# ------------------------------------------------------------------------------------------------- idle gating

def test_idle_reason_follows_the_spark_session_rule_and_launches():
    s = {"pause_while_playing_anywhere": False}
    run = lambda sid: {"session_id": sid, "state": "running"}
    assert SS.idle_reason([run("spark1-1")], [], [SPARK, PC], s) == "Waiting for the Spark game session to finish."
    assert SS.idle_reason([run("pc1-1")], [], [SPARK, PC], s) == ""                   # the operator's PC: build on
    assert "pause_while_playing_anywhere" in SS.idle_reason([run("pc1-1")], [], [SPARK, PC],
                                                            {"pause_while_playing_anywhere": True})
    assert SS.idle_reason([run("ghost-1")], [], [SPARK, PC], s)                          # unknown worker: wait
    assert SS.idle_reason([{"session_id": "spark1-0", "state": "ended"}], [], [SPARK], s) == ""
    assert SS.idle_reason([], [{"tool": "launch_game", "state": "queued"}], [SPARK], s) == "Waiting for a game launch to finish."
    assert SS.idle_reason([], [{"tool": "characters", "state": "running"}], [SPARK], s) == ""


def test_nothing_is_queued_while_the_operator_plays_on_the_spark_and_a_queued_build_is_deferred(env):
    env.store.upsert_catalog([entry(1, "Jet Grind Radio")])
    env.store.set_favorite(gid(1), True)
    env.writers[gid(1)] = {"writer": "gbox.jgr_swap", "routed": True}
    env.store.put("session", "spark1-1", {"session_id": "spark1-1", "state": "running", "game_id": gid(9)})
    st = env.svc.tick()
    assert st["phase"] == "waiting" and "Spark game session" in st["message"] and not env.submitted
    env.store.put("session", "spark1-1", {"session_id": "spark1-1", "state": "ended"})
    st = env.svc.tick()
    assert st["phase"] == "building" and len(env.submitted) == 1
    job = env.submitted[0]
    assert job["low_priority"] and job["require_os"] == "linux"
    assert job["input"]["launch"] is False and job["input"]["showcase"] is True
    assert job["input"]["mod_name"] == "showcase_sonic_jet_grind_radio" and job["input"]["source"] == "sonic"
    # the operator launches on the Spark before the worker claimed it: the queued build is dropped, not counted
    env.store.put("job", "launch", {"id": "launch", "tool": "launch_game", "state": "queued"})
    st = env.svc.tick()
    assert env.store.get("job", job["id"])["state"] == "failed"
    assert env.store.get("job", job["id"])["error"].startswith("showcase deferred")
    assert env.svc.record(gid(1))["stage"] == "deferred" and st.get("builds") == []
    # a running build is asked to stop instead
    env.store.put("job", "launch", {"id": "launch", "tool": "launch_game", "state": "succeeded"})
    env.svc.tick()
    second = env.submitted[-1]
    env.store.put("job", second["id"], env.store.get("job", second["id"]) | {"state": "running"})
    env.store.put("session", "spark1-2", {"session_id": "spark1-2", "state": "running"})
    st = env.svc.tick()
    assert st["phase"] == "deferring" and env.store.get("job", second["id"])["cancel"] is True


# ------------------------------------------------------------------------------------------------- plan-hash reuse

def test_an_unchanged_plan_is_never_built_again(env):
    env.store.upsert_catalog([entry(1, "Jet Grind Radio")])
    env.store.set_favorite(gid(1), True)
    env.writers[gid(1)] = {"writer": "gbox.jgr_swap", "routed": True}
    env.svc.tick()
    assert len(env.submitted) == 1
    mod = env.submitted[0]["input"]["mod_name"]
    finish_job(env, env.submitted[0], gid(1), mod)
    env.clock.t += 60
    env.svc.tick()                                                  # the result is folded into the record
    rec = env.svc.record(gid(1))
    assert rec["stage"] == "built" and rec["mod"] == mod and rec["build_time"] == 40
    assert [r["slot"] for r in rec["slots_replaced"]] == ["player", "beat"]
    assert rec["previews"][0]["preview"].startswith("/api/artifacts/")
    assert rec["previews"][0]["donor_preview"] == "/api/characters/sa1_sonic/preview"
    marker = json.loads((env.mods / gid(1) / mod / ".gbox-mod.json").read_text())
    assert marker["showcase"]["previews"] and marker["showcase"]["slots"]
    env.clock.t += 7 * 3600                                          # past recheck_hours: planned again
    env.svc.tick()
    assert len(env.submitted) == 1 and env.svc.record(gid(1))["stage"] in ("built", "unchanged")
    assert "unchanged" in env.svc.record(gid(1))["message"]
    # the plan changes (a new donor): one rebuild, the old showcase build is replaced
    env.plans[gid(1)] = [("player", "sa2_shadow"), ("beat", "sa1_sonic")]
    env.clock.t += 7 * 3600
    env.svc.tick()
    assert len(env.submitted) == 2 and not (env.mods / gid(1) / mod).exists()
    assert env.svc.record(gid(1))["plan_hash"] == CS.plan_digest(
        [{"slot": "player", "character": "sa2_shadow"}, {"slot": "beat", "character": "sa1_sonic"}])


def test_a_failed_plan_waits_before_it_is_tried_again(env):
    env.store.upsert_catalog([entry(1, "Jet Grind Radio")])
    env.store.set_favorite(gid(1), True)
    env.writers[gid(1)] = {"writer": "gbox.jgr_swap", "routed": True}
    env.svc.tick()
    j = env.store.get("job", "job0")
    env.store.put("job", "job0", j | {"state": "failed", "error": "PLAYER.AFS too big", "finished": env.clock()})
    env.svc.tick()
    assert env.svc.record(gid(1))["stage"] == "failed"
    env.clock.t += 7 * 3600
    env.svc.tick()
    assert len(env.submitted) == 1 and "PLAYER.AFS" in env.svc.record(gid(1))["message"]
    env.clock.t += 20 * 3600                                         # past retry_failed_hours
    env.svc.tick()
    assert len(env.submitted) == 2


# ------------------------------------------------------------------------------------------------- budget

def make_build(root: Path, game: str, name: str, size: int, built: float, showcase=True, data=None):
    d = root / game / name
    d.mkdir(parents=True)
    (d / "track03.bin").write_bytes(data if data is not None else os.urandom(size))
    meta = {"name": name, "game_id": game, "built": built}
    if showcase:
        meta["showcase"] = {"source": "sonic"}
    (d / ".gbox-mod.json").write_text(json.dumps(meta))
    return d


def test_budget_eviction_picks_only_older_showcase_builds(env):
    root = env.mods
    old = make_build(root, gid(1), "showcase_sonic_old", 4000, 100)
    mid = make_build(root, gid(2), "showcase_sonic_mid", 4000, 200)
    new = make_build(root, gid(3), "showcase_sonic_new", 4000, 300)
    kept = make_build(root, gid(4), "showcase_sonic_kept", 4000, 50)          # oldest, but the operator saved a card
    other = make_build(root, gid(1), "cast_jet_grind_radio_sonic_1234abcd", 9000, 1, showcase=False)
    fake = make_build(root, gid(2), "showcase_sonic_unmarked", 9000, 1, showcase=False)   # a prefix alone is not ours
    env.store.put("mod", "card-kept", {"id": "card-kept", "game_id": gid(4), "calls": [{"tool": "@launch", "input": {"mod": "showcase_sonic_kept"}}]})
    env.store.put("mod", "card-old", {"id": "card-old", "game_id": gid(1), "auto_registered": True,
                                      "calls": [{"tool": "@launch", "input": {"mod": "showcase_sonic_old"}}]})
    env.store.put(SS.KIND, gid(1), {"game_id": gid(1), "mod": "showcase_sonic_old", "stage": "built"})
    # a running game uses the "mid" build: never evicted while it runs
    env.store.put("session", "pc1-1", {"session_id": "pc1-1", "state": "running", "game_id": gid(2), "mod": "showcase_sonic_mid"})
    markers = sum((d / ".gbox-mod.json").stat().st_size for d in (old, mid, new, kept))
    assert SS.usage(SS.showcase_folders(root))["total"] == 16000 + markers     # the other two folders are not ours
    out = env.svc.evict(5000, 18000 + markers, keep={(gid(3), "showcase_sonic_new")})
    assert [e["mod"] for e in out["evicted"]] == ["showcase_sonic_old"]
    assert out["fits"] and not old.exists()
    assert kept.exists() and mid.exists() and new.exists() and other.exists() and fake.exists()
    assert env.store.get("mod", "card-old") is None and env.store.get("mod", "card-kept")
    assert env.svc.record(gid(1))["stage"] == "evicted"
    # nothing else may go: the budget can't be met, and no other folder is touched
    out = env.svc.evict(50000, 18000 + markers, keep={(gid(3), "showcase_sonic_new")})
    assert not out["fits"] and not out["evicted"]
    assert kept.exists() and mid.exists() and new.exists() and other.exists() and fake.exists()


def test_usage_counts_bytes_only_showcase_builds_hold(env):
    root = env.mods
    base = env.tmp / "hdd" / "gbox-cache" / "modbase" / gid(1)
    base.mkdir(parents=True)
    (base / "track01.bin").write_bytes(os.urandom(3000))
    d = make_build(root, gid(1), "showcase_sonic_a", 1000, 1)
    os.link(base / "track01.bin", d / "track01.bin")                # shared with the base copy: frees nothing
    e = make_build(root, gid(2), "showcase_sonic_b", 1000, 1)
    os.link(d / "track03.bin", e / "shared.bin")                    # shared between two showcase builds: counted once
    u = SS.usage(SS.showcase_folders(root))
    markers = (d / ".gbox-mod.json").stat().st_size + (e / ".gbox-mod.json").stat().st_size
    assert u["total"] == 2000 + markers and u["linked"] == 3000


def test_a_build_that_does_not_fit_is_not_queued(env):
    env.store.upsert_catalog([entry(1, "Jet Grind Radio")])
    env.store.set_favorite(gid(1), True)
    env.writers[gid(1)] = {"writer": "gbox.jgr_swap", "routed": True}
    env.store.put("setting", SS.SETTING, {"budget_gb": 1})
    make_build(env.mods, gid(5), "showcase_sonic_big", 10, 1)
    env.store.put("session", "pc1-1", {"session_id": "pc1-1", "state": "running", "game_id": gid(5), "mod": "showcase_sonic_big"})
    env.store.put(SS.KIND, gid(1), {"game_id": gid(1), "size": 3 << 30})   # its last build was 3 GB
    st = env.svc.tick()
    assert not env.submitted and env.svc.record(gid(1))["stage"] == "over_budget" and st["phase"] == "over_budget"


# ------------------------------------------------------------------------------------------------- no writer

def test_a_title_without_a_writer_goes_to_the_readiness_queue_with_its_fingerprint(env):
    env.store.upsert_catalog([entry(1, "Shenmue"), entry(2, "Skies of Arcadia")])
    env.store.set_favorite(gid(1), True)
    env.store.catalog_update(gid(2), last_played=900)                # recently played, not a favorite
    st = env.svc.tick()
    assert not env.submitted
    for n in (1, 2):
        rec = env.svc.record(gid(n))
        assert rec["stage"] == "readiness_queued", rec
        assert any(m.startswith("writer:") for m in rec["missing"]) and any(m.startswith("readiness:") for m in rec["missing"])
        assert rec["readiness"]["next_stage"] == "inventory" and "engine of" in rec["readiness"]["fingerprint"]
    data = Q._read()
    item = data["items"]["favorite:" + gid(2)]
    assert item["showcase"] and not item["favorite"] and item["fingerprint"]["summary"] == "engine of Skies of Arcadia"
    # Hermes works it (after the starred favorites): candidates() admits the showcase-only title
    picked = {k for k, _i in Q.candidates(data, [], [], set(), set(), now=10)}
    assert {"favorite:" + gid(1), "favorite:" + gid(2)} <= picked
    # a favorite sync never drops the showcase flag; stages and the fingerprint are kept on the next pass
    Q.sync(data, {"count": 1, "items": [{"game_id": gid(1), "title": "Shenmue", "platform": "dreamcast", "in_catalog": True}]},
           [], now=20)
    assert data["items"]["favorite:" + gid(2)]["showcase"]
    assert [q["stage"] for q in st["queue"]] == ["readiness_queued", "readiness_queued"]


def test_readiness_ranks_showcase_only_titles_after_favorites():
    data = {"items": {}, "last_lane": "inbox"}
    fav = ("favorite:" + gid(1), {"lane": "favorite", "game_id": gid(1), "favorite": True, "created": 5})
    extra = ("favorite:" + gid(2), {"lane": "favorite", "game_id": gid(2), "favorite": False, "showcase": True, "created": 1})
    assert Q.choose([extra, fav], data)[0] == fav[0]


# ------------------------------------------------------------------------------------------------- limits

def test_rate_cap_pause_and_storage_gate(env):
    env.store.upsert_catalog([entry(1, "Jet Grind Radio"), entry(2, "Crazy Taxi")])
    env.store.set_favorite(gid(1), True)
    env.store.set_favorite(gid(2), True)
    env.writers[gid(1)] = env.writers[gid(2)] = {"writer": "gbox.jgr_swap", "routed": True}
    env.svc.update({"builds_per_hour": 1})
    env.svc.tick()
    finish_job(env, env.submitted[0], env.submitted[0]["input"]["target_game"], env.submitted[0]["input"]["mod_name"])
    st = env.svc.tick()
    assert len(env.submitted) == 1 and st["phase"] == "rate_limited"
    env.clock.t += 3601
    env.svc.update({"paused": True})
    assert env.svc.tick()["phase"] == "paused" and len(env.submitted) == 1
    env.svc.update({"paused": False})
    env.svc.is_mount = lambda p: False                               # the HDD went away: never build elsewhere
    st = env.svc.tick()
    assert len(env.submitted) == 1 and st["phase"] == "storage" and "not mounted" in st["message"]
    env.svc.is_mount = lambda p: True
    env.cfg.cache = env.tmp / "nvme" / "gbox-cache"                   # the cache is not on the HDD
    st = env.svc.tick()
    assert len(env.submitted) == 1 and "not on the HDD" in st["message"]
    with pytest.raises(ValueError):
        env.svc.update({"hdd_root": "/"})                             # safety limits are gbox.toml only


def test_disabled_does_nothing(env):
    env.store.put("setting", SS.SETTING, {"enabled": False})
    env.store.upsert_catalog([entry(1, "Jet Grind Radio")])
    env.store.set_favorite(gid(1), True)
    env.writers[gid(1)] = {"writer": "gbox.jgr_swap", "routed": True}
    assert env.svc.tick()["phase"] == "disabled" and not env.submitted


def test_donors_are_collected_first(env):
    env.store.upsert_catalog([entry(1, "Jet Grind Radio"), entry(900, "Sonic Adventure"), entry(901, "Sonic Adventure 2")])
    env.store.set_favorite(gid(1), True)
    env.writers[gid(1)] = {"writer": "gbox.jgr_swap", "routed": True}
    env.svc.chars = lambda: SONIC_CHARS[1:]                          # SA2 collected, SA1 not yet
    st = env.svc.tick()
    assert env.submitted[0]["input"] == {"op": "collect", "game_id": gid(900)} and st["phase"] == "collecting_donors"
    env.store.put("character_collection", gid(900), {"state": "queued", "job_id": "job0"})
    env.svc.tick()
    assert len(env.submitted) == 1                                   # one job at a time: waits for the collection
    env.store.put("job", "job0", env.store.get("job", "job0") | {"state": "succeeded"})
    env.svc.tick()                                                   # collected without entries: build with SA2
    assert env.submitted[-1]["input"]["op"] == "cast_swap"


# ------------------------------------------------------------------------------------------------- disk helpers

def test_dedupe_links_identical_files_to_the_base_copy(env):
    base = env.tmp / "hdd" / "gbox-cache" / "modbase" / gid(1)
    base.mkdir(parents=True)
    data = os.urandom(5 << 20)
    (base / "track01.bin").write_bytes(data)
    d = make_build(env.mods, gid(1), "showcase_sonic_a", 0, 1, data=data)
    out = SS.dedupe(d, [base], 1 << 20)
    assert out == {"linked": 1, "saved": 5 << 20}
    assert os.stat(d / "track03.bin").st_ino == os.stat(base / "track01.bin").st_ino
    assert os.stat(d / ".gbox-mod.json").st_nlink == 1


def test_link_tree_and_fixed_names(env):
    src = make_build(env.mods, gid(1), "doa2_roster_1234", 100, 1, showcase=False)
    dst = CS.link_tree(src, env.mods / gid(1) / "showcase_sonic_doa2")
    assert os.stat(dst / "track03.bin").st_ino == os.stat(src / "track03.bin").st_ino
    assert os.stat(dst / ".gbox-mod.json").st_nlink == 1             # the record is the copy's own
    assert CS._named(SimpleNamespace(mod_name="showcase_sonic_jgr")) == "showcase_sonic_jgr"
    with pytest.raises(ValueError):
        CS._named(SimpleNamespace(mod_name="../escape"))
    plan = [{"slot": "player", "character": "x"}]
    assert CS.mod_name({"title": "Jet Grind Radio"}, "Sonic", plan).endswith(CS.plan_digest(plan))
    assert SS.mod_name_for({"title": "Jet Grind Radio (USA)", "game_id": gid(1)}) == "showcase_sonic_jet_grind_radio_usa"


# ------------------------------------------------------------------------------------------------- API + gallery

def test_api_status_and_settings(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from gbox.config import Config
    from gbox.server import create_app
    monkeypatch.setenv("GBOX_HERMES_DISPATCH_STATE", str(tmp_path / "hermes"))
    cfg = Config(data_dir=tmp_path / "data")
    app = create_app(cfg)
    with TestClient(app) as client:
        client.headers["Authorization"] = f"Bearer {cfg.token()}"
        r = client.get("/api/showcase").json()
        assert r["enabled"] is False and r["settings"]["budget_gb"] == 50 and r["disk"]["budget"] == 50 << 30
        r = client.put("/api/showcase", json={"enabled": True, "budget_gb": 20, "builds_per_hour": 2}).json()
        assert r["enabled"] and r["settings"]["budget_gb"] == 20 and r["rate"]["cap"] == 2
        assert client.post("/api/showcase", json={"paused": True}).json()["paused"] is True
        assert client.put("/api/showcase", json={"builds_per_hour": 9999}).json()["settings"]["builds_per_hour"] == 60
        assert client.get(f"/api/showcase/{gid(1)}").json() == {"game_id": gid(1), "record": None, "readiness": None,
                                                                 "mod_exists": False}
        assert client.get("/api/showcase/nope").status_code == 404


def test_gallery_marks_showcase_builds_and_filters_them():
    from gbox import built_mods as B
    rec = {"name": "showcase_sonic_jgr", "game_id": gid(1), "images": [], "donor_previews": [],
           "meta": {"showcase": {"previews": [{"slot": "player", "label": "Sonic", "preview": "/api/artifacts/" + "b" * 64},
                                              {"slot": "x", "preview": "http://elsewhere/evil.png"}]}}}
    e = B.entry(rec, None, None, None, {}, None)
    assert e["showcase"] and e["fit_previews"] == [{"slot": "player", "label": "Sonic", "url": "/api/artifacts/" + "b" * 64}]
    plain = B.entry({"name": "cast_x", "game_id": gid(1), "images": [], "donor_previews": [], "meta": {}}, None, None, None, {}, None)
    assert not plain["showcase"]
    assert [m["name"] for m in B.select([e, plain], kind="showcase")] == ["showcase_sonic_jgr"]
    assert [m["name"] for m in B.select([e, plain], kind="other")] == ["cast_x"]
    assert B.facets([e, plain])["showcase"] == 1
