"""Every engine round's run map (gbox.mercs.run_capture): captured 5 times a second, written at the round's end, keyed to
its curriculum row - RE5 / RE6 on Switch first (operator 2026-10-27 20:28)."""
import json
import math
import sqlite3
from types import SimpleNamespace

from gbox.mercs import engine, lessons, run_capture as RC

TITLE = "010018100CD46000"


class Bot:
    doing, why = "none", ""


def snap(x, z, hp=1000, enemies=(), bonuses=None, kills=0, **extra):
    s = {"player": {"ptr": 1, "pos": (x, 50.0, z), "rot": 0.5, "hp": hp, "hp_max": 1000},
         "enemies": [{"slot": k, "pos": p, "hp": 200, "hp_max": 200} for k, p in enumerate(enemies)],
         "timer": 120.0, "score": 100 * kills, "combo": 0, "kills": kills}
    if bonuses is not None:
        s["bonuses"] = bonuses
    s.update(extra)
    return s


def play(cap, rows, bot=None, dt=0.2, t0=1000.0):
    """rows: (where, snapshot, stats, doing) per tick."""
    bot = bot or Bot()
    for k, (where, s, stats, doing) in enumerate(rows):
        bot.doing, bot.why = doing, f"why {doing}"
        cap.observe(t0 + k * dt, where, s, bot, stats)
    return t0 + len(rows) * dt


def test_a_round_is_sampled_cheaply_and_written_as_a_run_map(tmp_path):
    cap = RC.RunCapture(tmp_path / "round_maps", TITLE, "a" * 32,
                        provenance={"source_session_id": "worker-session", "source_autoplay_job_id": "job1"},
                        threaded=False)
    statue_near = {"ptr": 0x10, "pos": (2000.0, 50.0, 0.0), "secs": 30}
    statue_far = {"ptr": 0x20, "pos": (-5000.0, 50.0, 4000.0), "secs": 90}
    rows = []
    for i in range(60):                                   # 12 s: 10 m east at a walk, past a statue (taken)
        bonuses = [statue_far] + ([statue_near] if i < 50 else [])
        stats = {"shots": i // 10, "hits": i // 20, "stage": "Rooftop Mission", "mines_placed": 1 if i >= 30 else 0,
                 "prompt_presses": 1 if i >= 40 else 0, "stuck": 1 if i >= 55 else 0}
        rows.append(("playing", snap(i * 40.0, 0.0, enemies=[(i * 40.0 + 300, 50.0, 0.0)], bonuses=bonuses,
                                     kills=i // 15), stats, "walk" if i < 30 else "fire"))
    rows.append(("playing", snap(2400.0, 0.0, hp=800, enemies=[(2500.0, 50.0, 0.0)], bonuses=[statue_far]),
                 dict(stats), "fire"))
    rows.append(("dead", snap(2400.0, 0.0, hp=0, bonuses=[statue_far]), dict(stats), "dead"))
    end = play(cap, rows)
    out = cap.finish(end, "died")
    assert out["round_map_file"] == f"round_maps/{TITLE}/Rooftop_Mission/" + out["round_map_file"].split("/")[-1]
    assert out["round_map_file"].endswith("-aaaaaaaa.json") and out["round_map_stage"] == "Rooftop Mission"
    assert out["explore_distance_m"] == 24.0 and out["explore_max_from_spawn_m"] == 24.0
    assert out["explore_start_area_s"] == 5.2 and out["explore_samples"] == 62
    d = json.loads((tmp_path / out["round_map_file"]).read_text())
    assert d["format"] == "gbox.run_map/1" and d["round_id"] == "a" * 32 and d["outcome"] == "died"
    assert d["session_id"] == "worker-session" and d["autoplay_job_id"] == "job1"
    assert len(d["route"]) == len(d["hp"]) == len(d["heading"]) == 62 and d["route"][0][1:3] == [0.0, 0.0]
    assert [r[1] for r in d["doing"]] == ["walk", "fire", "dead"] and d["doing"][1][0] == 30
    assert d["doing"][0][3] == "why walk"
    kinds = [e["kind"] for e in d["events"]]
    for k in ("shots", "mine", "prompt", "stuck", "kill", "bonus", "hit", "death"):
        assert k in kinds, k
    hit = next(e for e in d["events"] if e["kind"] == "hit")
    assert hit["loss"] == 200 and hit["attackers"][0][:2] == [2500, 0] and hit["dist"] == 100
    death = next(e for e in d["events"] if e["kind"] == "death")
    assert death["doing"] == "fire"
    taken = {b["id"]: b for b in d["bonuses"]}
    assert taken[str(0x10)]["taken"] and taken[str(0x10)]["gone_d"] == 0
    assert not taken[str(0x20)]["taken"] and taken[str(0x20)]["gone_t"] is None
    assert d["bonuses_taken"] == 1 and d["bonuses_missed"] == 1 and d["deaths"] == 1
    assert d["enemies"][0] == [0, [[300, 0]]] and len(d["enemies"]) == 13
    assert d["clock"][0][0] == 0 and d["clock"][0][1] == 120.0
    assert d["time_by_phase"]["walk"] == 6.0 and d["cells_visited"] == len(d["cells"])
    cov = d["exploration"]["coverage"]
    assert cov["source"].startswith("observed") and cov["runs"] == 1 and 0 < cov["value"] <= 1
    ext = json.loads((tmp_path / "round_maps" / TITLE / "Rooftop_Mission" / "extent" / "extent.json").read_text())
    assert ext["runs"] == 1 and [-20, 16] in ext["seen"]               # the far statue's cell joins the known stage
    svg = (tmp_path / out["round_map_file"]).with_suffix(".svg").read_text()
    assert svg.startswith("<svg") and "Rooftop Mission" in svg and "#ff2d2d" in svg   # the death drawn


def test_the_capture_keeps_5_samples_a_second_and_ignores_menus(tmp_path):
    cap = RC.RunCapture(tmp_path, TITLE, "b" * 32, threaded=False)
    for k in range(120):                                  # 2 s at 60 Hz
        cap.observe(10.0 + k / 60.0, "playing", snap(k * 5.0, 0.0), Bot(), {})
    for k in range(60):
        cap.observe(12.0 + k / 60.0, "results", snap(0.0, 0.0), Bot(), {})
    assert 10 <= len(cap.route) <= 11
    assert cap.observe(20.0, "playing", {"player": {"pos": (math.nan, 0, 0)}}, Bot(), {}) is False
    assert cap.observe(21.0, "playing", None, None, None) is False and not cap.status.get("observe_error")


def test_the_buffers_are_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(RC, "MAX_SAMPLES", 20)
    monkeypatch.setattr(RC, "MAX_EVENTS", 3)
    cap = RC.RunCapture(tmp_path, TITLE, "c" * 32, threaded=False)
    for k in range(50):
        cap.observe(k * 0.2, "playing", snap(k * 10.0, 0.0, hp=1000 - k), Bot(), {})
    assert len(cap.route) == 20 and cap.route[-1][1] == 490.0          # the end keeps moving
    assert cap.dropped["samples"] == 30 and len(cap.events) == 3 and cap.dropped["events"] > 0
    cap.finish(10.0, "ended")
    d = json.loads(next((tmp_path / TITLE / "unknown").glob("*.json")).read_text())
    assert d["truncated"]["samples"] == 30


def test_a_short_round_gets_no_map(tmp_path):
    cap = RC.RunCapture(tmp_path, TITLE, "d" * 32, threaded=False)
    play(cap, [("playing", snap(0.0, 0.0), {}, "walk")] * 5)
    assert cap.finish(5.0, "interrupted") == {} and not list(tmp_path.rglob("*.json"))


def test_a_navmesh_is_the_known_extent(tmp_path):
    mesh = SimpleNamespace(V=[(0.0, 0.0, 0.0), (2000.0, 0.0, 0.0), (2000.0, 0.0, 2000.0), (0.0, 0.0, 2000.0)],
                           T=[(0, 1, 2), (0, 2, 3)])
    floor = RC.floor_cells(mesh, 250.0)
    assert len(floor) >= 64 and (0, 0) in floor and (7, 7) in floor and (9, 9) not in floor
    cap = RC.RunCapture(tmp_path, "01002A000CD48000", "e" * 32, threaded=False)
    play(cap, [("playing", snap(100.0 + k * 50, 100.0, navmesh=mesh), {"stage": "Rooftop Mission"}, "walk")
               for k in range(20)])
    cap.finish(10.0, "completed")
    d = json.loads(next(tmp_path.rglob("*-eeeeeeee.json")).read_text())
    cov = d["exploration"]["coverage"]
    assert cov["source"].startswith("navmesh") and cov["known_cells"] >= 64 and cov["value"] < 0.2


def test_the_newest_maps_are_kept(tmp_path, monkeypatch):
    monkeypatch.setattr(RC, "MAX_KEEP", 2)
    for n, rid in enumerate(("1" * 32, "2" * 32, "3" * 32)):
        cap = RC.RunCapture(tmp_path, TITLE, rid, threaded=False, clock=lambda: 0)
        play(cap, [("playing", snap(k * 50.0, 0.0), {}, "walk") for k in range(12)], t0=1_700_000_000 + n * 100)
        cap.finish(0, "ended")
    kept = sorted(p.name for p in (tmp_path / TITLE / "unknown").glob("*.json"))
    assert len(kept) == 2 and kept[0].endswith("22222222.json") and kept[1].endswith("33333333.json")
    assert len(list((tmp_path / TITLE / "unknown").glob("*.svg"))) == 2
    assert json.loads((tmp_path / TITLE / "unknown" / "extent" / "extent.json").read_text())["runs"] == 3


def test_a_round_spent_by_the_spawn_is_named(tmp_path):
    cap = RC.RunCapture(tmp_path, TITLE, "f" * 32, threaded=False)
    play(cap, [("playing", snap(100.0 + (k % 5) * 20, 0.0), {}, "fire") for k in range(300)])   # 60 s by the spawn
    cap.finish(100.0, "ended")
    d = json.loads(next(tmp_path.rglob("*.json")).read_text()) if False else \
        json.loads(next((tmp_path / TITLE / "unknown").glob("*.json")).read_text())
    assert d["exploration"]["start_area_share"] == 1.0 and d["exploration"]["max_from_spawn_m"] < 1.1
    assert "within 10 m of the spawn" in d["verdict"] and d["standstills"]


# --- the engine feeds it ---------------------------------------------------------------------------------------------
def run_engine(tmp_path, monkeypatch, sequence, map_id=TITLE, brain_cls=None, tactical=None):
    monkeypatch.setattr(lessons, "ROOT", tmp_path / "mercs" / "lessons")
    monkeypatch.setattr(RC, "THREADED", False)                  # write on the engine's thread
    stats, index = {}, [-1]

    class Brain:
        _round_started = None
        marker = None
        doing, why = "none", ""

        def observe_round(self, s, where, now):
            if where == "playing" and self.marker != s["round"]:
                self.marker, self._round_started = s["round"], now

        def tick(self, s):
            self.doing, self.why = ("walk", "to the statue") if s["where"] == "playing" else ("none", "")
            if s["where"] == "playing":
                stats["shots"] = stats.get("shots", 0) + 1
            return {"hold": {"lup"}}

        def prompt_ok(self, *a):
            return True

        def save(self):
            pass

    class Driver:
        frame = None
        solo_p1 = True

        def snapshot(self, m):
            row = sequence[index[0]]
            return dict(row, player={"ptr": 7, "pos": (index[0] * 100.0, 0.0, 0.0), "rot": 0.0,
                                     "hp": 0 if row["where"] == "dead" else 900, "hp_max": 900},
                        enemies=[], bonuses=[])

        def screen(self, m, s):
            return s["where"]

        def progress(self, s):
            return {"score": 1000, "kills": 10, "timer": s.get("timer", 60.0), "stage": "Rooftop Mission",
                    "character": "Chris"}

        def prompt_source(self, *a):
            return lambda: None

        def prompt_keys(self, b):
            return []

    def stopped():
        index[0] += 1
        return index[0] >= len(sequence)
    why = engine.play_round({"map_id": map_id}, object(), lambda rows: None, stopped, stats, lambda row: None,
                            brain=(brain_cls or Brain)(), driver=Driver(), clock=lambda: 1_793_000_000 + index[0] * .2,
                            sleep=lambda _: None, tactical=tactical)
    return why, stats


def test_the_engine_writes_one_run_map_per_round_keyed_to_its_curriculum_row(tmp_path, monkeypatch):
    seq = [{"where": "playing", "round": 1}] * 14 + [{"where": "dead", "round": 1}] + \
          [{"where": "playing", "round": 2}] * 12 + [{"where": "results", "round": 2, "timer": 0.0}] + \
          [{"where": "playing", "round": 3}] * 3
    class Tactical:                                           # the tactical publisher: the session's provenance
        sink = SimpleNamespace(sid="worker-session", client=SimpleNamespace(headers={"x-gbox-parent-job": "job7"}))

        def __call__(self, *a):
            pass
    tactical = Tactical()
    why, stats = run_engine(tmp_path, monkeypatch, seq, tactical=tactical)
    assert why == "stopped"
    with sqlite3.connect(tmp_path / "mercs" / "curriculum" / TITLE / "rounds.sqlite") as db:
        rows = [(r[0], r[1], json.loads(r[2])) for r in db.execute("SELECT id,outcome,data FROM rounds ORDER BY rowid")]
    assert [r[1] for r in rows] == ["died", "completed", "interrupted"]
    mapped = [r for r in rows if r[2].get("round_map_file")]
    assert len(mapped) == 2                                   # the 3-tick stop round is too short for a map
    for rid, outcome, data in mapped:
        path = tmp_path / "mercs" / data["round_map_file"]
        d = json.loads(path.read_text())
        assert d["round_id"] == rid and d["outcome"] == outcome and d["stage"] == "Rooftop Mission"
        assert d["session_id"] == "worker-session" and d["autoplay_job_id"] == "job7"
        assert data["round_map_stage"] == "Rooftop Mission" and data["explore_distance_m"] > 0
        assert data["explore_cells"] == d["exploration"]["cells"] and path.with_suffix(".svg").is_file()
        assert any(r[1] == "walk" for r in d["doing"])
        assert any(e["kind"] == "shots" for e in d["events"])
    died = json.loads((tmp_path / "mercs" / mapped[0][2]["round_map_file"]).read_text())
    assert [e["kind"] for e in died["events"] if e["kind"] == "death"] == ["death"]
    assert stats["last_run_map"] == mapped[1][2]["round_map_file"]


def test_a_brain_with_its_own_round_map_keeps_it_alone(tmp_path, monkeypatch):
    class OwnMap:
        _round_started = None
        marker = None

        def observe_round(self, s, where, now):
            if where == "playing" and self.marker != s["round"]:
                self.marker, self._round_started = s["round"], now

        def tick(self, s):
            return {"hold": set()}

        def prompt_ok(self, *a):
            return True

        def save(self):
            pass

        def trace_finish(self):
            pass
    seq = [{"where": "playing", "round": 1}] * 20 + [{"where": "dead", "round": 1}]
    run_engine(tmp_path, monkeypatch, seq, brain_cls=OwnMap)
    assert not (tmp_path / "mercs" / "round_maps").exists()
