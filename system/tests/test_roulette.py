"""Roulette (gbox.roulette): demos launch a built cast (weighted to Sonic / Mario and starred builds, never test builds),
favorites with demo builds join the screensaver's games, and the background builder queues one random cast at a time."""
import random
from types import SimpleNamespace

from gbox import roulette as R
from gbox import screensaver as S
from tests.test_screensaver import Archive, Store, worker

BUILDS = [{"name": "doa2_sonic_vs_mario_hd_random", "kind": "character", "favorite": True},
          {"name": "doa2_roster_59d8ed0e", "kind": "cast"},
          {"name": ".tmp_doa2_sonic_vs_mario_hd_random", "kind": "character"},
          {"name": "doa2_amy_test_weighted", "kind": "file"},
          {"name": "doa2_kte01_sa2_amy_rose_chk", "kind": "character"},
          {"name": "doa2_broken_one", "kind": "cast", "broken": True},
          {"name": "doa2_only_on_jay", "kind": "cast", "local_only": True}]


def test_demo_builds_leave_out_test_broken_and_local_builds():
    assert [b["name"] for b in R.demo_builds(BUILDS)] == ["doa2_sonic_vs_mario_hd_random", "doa2_roster_59d8ed0e"]
    assert R.demo_build([{"name": "x_test_y", "kind": "cast"}]) is None             # nothing fit: the stock game


def test_demo_build_favours_starred_sonic_mario_builds():
    rng = random.Random(3)
    picks = [R.demo_build(BUILDS, rng)["name"] for _ in range(400)]
    assert picks.count("doa2_sonic_vs_mario_hd_random") > 3 * picks.count("doa2_roster_59d8ed0e") > 0


class Jobs:
    def __init__(self, store):
        self.store, self.calls = store, []

    def __call__(self, call):
        j = {"id": f"rj{len(self.calls)}", "state": "queued", **call}
        self.calls.append(j)
        self.store.put("job", j["id"], j)
        return SimpleNamespace(**j)


def builder(store, clock, candidates=None, rng=None):
    jobs = Jobs(store)
    b = R.Builder(store, jobs, lambda gid: [], candidates or (lambda: [{"game_id": "doa2", "title": "DOA2", "favorite": True}]),
                  rng=rng or random.Random(5), clock=lambda: clock[0])
    return b, jobs


def test_builder_queues_one_cast_swap_at_a_time(monkeypatch):
    monkeypatch.setattr(R, "writer_ok", lambda game: True)
    s, clock = Store(), [100_000.0]
    b, jobs = builder(s, clock)
    assert b.tick().startswith("queued")
    call = jobs.calls[0]
    assert call["tool"] == "characters" and call["input"]["op"] == "cast_swap" and call["input"]["launch"] is False
    assert call["input"]["target_game"] == "doa2" and call["input"]["mod_name"].startswith("roulette_")
    assert call["input"]["source"] in [p[0] for p in R.POOLS]
    clock[0] += R.BUILD_EVERY * 2
    assert b.tick().startswith("building")                              # the first one still runs: nothing new
    assert len(jobs.calls) == 1
    s.put("job", "rj0", jobs.calls[0] | {"state": "succeeded"})
    assert b.tick().startswith("queued") and len(jobs.calls) == 2       # done: the next one
    assert [r["state"] for r in b.records() if r["job"] == "rj0"] == ["built"]


def test_builder_stops_at_max_per_game_and_skips_failing_pools(monkeypatch):
    monkeypatch.setattr(R, "writer_ok", lambda game: True)
    s, clock = Store(), [100_000.0]
    b, jobs = builder(s, clock)
    for i in range(R.MAX_PER_GAME):
        assert b.tick().startswith("queued")
        s.put("job", jobs.calls[-1]["id"], jobs.calls[-1] | {"state": "succeeded"})
        clock[0] += R.BUILD_EVERY + 1
    assert b.tick() == "every target has its roulette builds"
    s2, clock2 = Store(), [100_000.0]
    b2, jobs2 = builder(s2, clock2)
    for p in R.POOLS:                                                   # every pool failed twice in this game
        for k in range(R.FAIL_LIMIT):
            s2.put(R.KIND, f"f{p[0]}{k}", {"mod": f"f{p[0]}{k}", "game_id": "doa2", "pool": p[0], "state": "failed"})
    assert b2.plan() is None


def test_builder_leaves_games_without_a_working_writer(monkeypatch):
    monkeypatch.setattr(R, "writer_ok", lambda game: game["game_id"] != "doa3")
    s, clock = Store(), [100_000.0]
    b, jobs = builder(s, clock, lambda: [{"game_id": "doa3", "title": "DOA3", "favorite": True}])
    assert b.tick() == "every target has its roulette builds" and not jobs.calls


def test_screensaver_launches_a_demo_build_and_adds_favorites(monkeypatch):
    s, now = Store(), 10_000.0
    w = worker(now)
    calls = []

    def submit(req, actor, origin):
        j = {"id": f"job{len(calls)}", "state": "queued", "tool": req.tool, "input": req.input}
        calls.append(j)
        return SimpleNamespace(**j)
    builds = {"sc": [{"name": "sc2_sonic_vs_mario_hd_random", "kind": "romhack"}],
              "fav": [{"name": "fav_mario_cast", "kind": "cast"}], "favnoplay": [{"name": "x_cast", "kind": "cast"}]}
    favs = [{"game_id": "fav", "title": "Fav"}, {"game_id": "favnoplay", "title": "Never played"}]
    archive = Archive()
    archive_runs = archive.runs() + [{"id": "r9", "game_id": "fav", "title": "Fav", "events": {"pad": 80}, "updated": 9}]
    archive.runs = lambda limit=200: archive_runs
    saver = S.Screensaver(s, archive, submit, lambda: [w], rng=random.Random(2),
                          builds=lambda gid: builds.get(gid, []), favorites=lambda: favs)
    ids = [g["game_id"] for g in saver.games(S.settings(s))]
    assert "fav" in ids and "favnoplay" not in ids                       # a favorite needs some recorded play (or a playbook)
    saver.games = lambda cfg: [{"game_id": "sc", "title": "SoulCalibur", "pads": 900}]
    out = saver.tick(now)
    assert "sc2_sonic_vs_mario_hd_random" in out["i9-NUC"]
    assert calls[0]["input"]["mod"] == "sc2_sonic_vs_mario_hd_random"
    run = s.get(S.STATE, "i9-NUC")
    assert run["mod"] == "sc2_sonic_vs_mario_hd_random"


def test_roulette_off_plays_stock():
    s, now = Store(), 10_000.0
    s.put("setting", S.SETTING, {"roulette": False})
    w = worker(now)
    calls = []

    def submit(req, actor, origin):
        calls.append(req.input)
        return SimpleNamespace(id="j0", state="queued")
    saver = S.Screensaver(s, Archive(), submit, lambda: [w], rng=random.Random(2),
                          builds=lambda gid: [{"name": "a_cast", "kind": "cast"}], favorites=lambda: [])
    saver.tick(now)
    assert "mod" not in calls[0]



def test_a_game_waiting_for_report_review_is_blocked_not_retried(monkeypatch):
    monkeypatch.setattr(R, "writer_ok", lambda game: True)
    s, clock = Store(), [100_000.0]

    class Gate(Exception):
        detail = {"code": "build_feedback_review_required", "message": "Review the operator reports first",
                  "feedback": [{"id": "r1", "number": 1816, "revision": 1}]}
    calls = []

    def refuse(call):
        calls.append(call)
        raise Gate()
    b = R.Builder(s, refuse, lambda gid: [], lambda: [{"game_id": "doa2", "title": "DOA2", "favorite": True}],
                  rng=random.Random(5), clock=lambda: clock[0])
    assert "#1816" in b.tick()
    assert [(x["game_id"], x["reports"]) for x in b.status()["blocked"]] == [("doa2", [1816])]
    clock[0] += R.BUILD_EVERY + 1
    assert b.tick() == "every target has its roulette builds" and len(calls) == 1     # not retried while blocked
    assert not b.failures()                                                             # and no pool counted as failed
    clock[0] += R.BLOCK_TTL
    b.tick()
    assert len(calls) == 2                                                              # tried again after BLOCK_TTL
