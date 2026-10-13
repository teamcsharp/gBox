"""Ghost runs (#1098, gbox/ghost_runs.py): SMB1 RAM decoding, run / attempt / split cutting, rewinds and state loads,
the packed track, best flags, the ghost projection, the worker capture loop and the control-plane routes.

Every trace here is synthetic: 2 KiB RAM images built field by field at the SMBDIS addresses (no game data)."""
import threading
import time

import pytest

from gbox import ghost_runs as GR

SMB = GR.PROFILES["smb1"]
A = GR.SMB1


def ram(**f) -> bytes:
    """A synthetic SMB1 RAM image. Fields: fc, oper, task, sub, world, level, ap, x (world), y (abs), scr, small, pw,
    face, st, anim, joy, timer, lives, pause, player, relx, rely."""
    m = bytearray(0x800)
    x, y, scr = int(f.get("x", 40)), int(f.get("y", 256 + 176)), int(f.get("scr", 0))
    m[A["FrameCounter"]] = f.get("fc", 0) & 0xFF
    m[A["OperMode"]], m[A["OperMode_Task"]] = f.get("oper", 1), f.get("task", 3)
    m[A["GameEngineSubroutine"]] = f.get("sub", 8)
    m[A["WorldNumber"]], m[A["LevelNumber"]] = f.get("world", 0), f.get("level", 0)
    m[A["AreaPointer"]] = f.get("ap", 0xC2)
    m[A["Player_PageLoc"]], m[A["Player_X_Position"]] = x // 256, x % 256
    m[A["Player_Y_HighPos"]], m[A["Player_Y_Position"]] = y // 256, y % 256
    m[A["ScreenLeft_PageLoc"]], m[A["ScreenLeft_X_Pos"]] = scr // 256, scr % 256
    m[A["Player_Rel_XPos"]] = f.get("relx", (x - scr) & 0xFF)
    m[A["Player_Rel_YPos"]] = f.get("rely", y % 256)
    m[A["PlayerSize"]], m[A["PlayerStatus"]] = f.get("small", 1), f.get("pw", 0)
    m[A["PlayerFacingDir"]], m[A["Player_State"]], m[A["PlayerGfxOffset"]] = f.get("face", 1), f.get("st", 0), f.get("anim", 0)
    m[A["SavedJoypad1Bits"]] = f.get("joy", 0)
    t = f.get("timer", 400)
    m[A["GameTimerDisplay"]:A["GameTimerDisplay"] + 3] = bytes([t // 100, t // 10 % 10, t % 10])
    m[A["NumberofLives"]], m[A["GamePauseStatus"]], m[A["CurrentPlayer"]] = f.get("lives", 2), f.get("pause", 0), f.get("player", 0)
    return bytes(m)


class Trace:
    """Builds a frame-by-frame synthetic session; feed() runs it through a Recorder."""

    def __init__(self):
        self.frames, self.fc = [], 0
        self.state = dict(oper=0, task=3, sub=8, world=0, level=0, ap=0xC2, x=40, y=256 + 176, scr=0, timer=400, lives=2)

    def step(self, n=1, every=1, **change):
        """n frames (FrameCounter += every each), applying change on the first; x/scr may be callables of i."""
        for i in range(n):
            self.fc += every
            st = dict(self.state)
            for k, v in change.items():
                st[k] = v(i) if callable(v) else v
            if i == n - 1:
                self.state.update({k: st[k] for k in change})
            self.frames.append(ram(fc=self.fc, **st))
        return self

    def run_level(self, n=120, x0=40, speed=2, **kw):
        """In control, running right for n frames; the camera follows at screen x 112."""
        args = dict(task=3, sub=8, oper=1, x=lambda i: x0 + i * speed, scr=lambda i: max(0, x0 + i * speed - 112),
                    timer=lambda i: 400 - i // 24)
        return self.step(n, **(args | kw))

    def screens(self, n=20, **kw):
        """Area init / lives screen: task cycles 0 -> 1 -> 2 (sub 0)."""
        return self.step(n, task=lambda i: (i * 3) // n, sub=0, oper=1, **kw)

    def feed(self, rec):
        out = []
        for m in self.frames:
            out += rec.feed(SMB.decode(m))
        return out


_T = [1000.0]


def recorder():
    def clock():                                   # one clock for every recorder: later runs start later
        _T[0] += 1
        return _T[0]
    return GR.Recorder(SMB, "49b6a2f65aca26a2", "w1-s1", clock=clock)


# ------------------------------------------------------------------------------------------------ decoding / profiles
def test_decode_reads_the_smbdis_addresses():
    s = SMB.decode(ram(fc=77, oper=1, task=3, sub=0x0B, world=3, level=1, ap=0x25, x=3 * 256 + 17, y=256 + 120,
                       scr=2 * 256 + 200, small=0, pw=2, face=2, st=1, anim=0x30, joy=0xC1, timer=287, lives=4))
    assert (s["fc"], s["oper"], s["task"], s["sub"], s["world"], s["level"], s["ap"]) == (77, 1, 3, 0x0B, 3, 1, 0x25)
    assert (s["x"], s["y"], s["scr"], s["relx"]) == (785, 376, 712, (785 - 712) & 0xFF)
    assert (s["small"], s["pw"], s["face"], s["st"], s["anim"], s["joy"], s["timer"], s["lives"]) == (0, 2, 2, 1, 0x30, 0xC1, 287, 4)
    assert A["Player_X_Position"] == 0x86 and A["ScreenLeft_X_Pos"] == 0x71C and A["OperMode"] == 0x770


def test_profile_matches_by_game_id_and_by_title():
    assert GR.profile_for({"game_id": "49b6a2f65aca26a2"}) is SMB
    assert GR.profile_for({"game_id": "x", "title": "Super Mario Bros. (USA)", "platform": "nes"}) is SMB
    assert GR.profile_for({"game_id": "x", "title": "Super Mario Bros.", "platform": "nes"}) is SMB
    assert GR.profile_for({"game_id": "x", "title": "Super Mario Bros. 3", "platform": "nes"}) is None
    assert GR.profile_for({"game_id": "x", "title": "Super Mario Bros.", "platform": "snes"}) is None
    assert GR.profile_for(None) is None


# ------------------------------------------------------------------------------------------------ the recorder
def test_demo_and_title_never_start_a_run():
    rec = recorder()
    Trace().step(300, oper=0, task=3, x=lambda i: 40 + i).feed(rec)          # the attract demo plays in OperMode 0
    assert rec.run is None and rec.live()["in_play"] is False


def test_full_level_death_retry_and_flagpole_split():
    tr = Trace().step(30, oper=0)                                             # title
    tr.screens(20).run_level(200)                                             # 1-1, first try ...
    tr.step(40, sub=0x0B)                                                     # ... dies (PlayerDeath)
    tr.screens(30, lives=1).run_level(300)                                    # second try
    tr.step(1, sub=4).step(60, sub=5)                                         # flagpole, walk to the castle
    tr.step(1, task=0, level=1, sub=0).screens(20, level=1).run_level(100, level=1, ap=0x29)   # 1-2
    rec = recorder()
    assert tr.feed(rec) == []
    live = rec.live()
    assert live["start_level"] == "1-1" and live["attempt_level"] == "1-2" and live["level_frame"] == 99
    assert live["deaths"] == 1 and live["assisted"] is False
    run = rec.finish()
    assert run["outcome"] == "session_end" and run["start_level"] == "1-1" and run["end_level"] == "1-2"
    res = [(a["level"], a["result"]) for a in run["attempts"]]
    assert res == [("1-1", "death"), ("1-1", "clear"), ("1-2", "end")]
    a1, a2 = run["attempts"][:2]
    assert a1["start"] == 0 and a1["end"] == 200 and a2["end"] - a2["start"] == 300
    (sp,) = run["splits"]
    assert sp == {"level": "1-1", "start": 0, "end": a2["end"], "frames": a2["end"], "segment": 300, "deaths": 1}
    rows = GR.unpack_track(run["track"])
    assert len(rows) == run["samples"] == 200 + 300 + 100         # gameplay frames only (not the death, flag walk, screens)
    assert rows[0][1] == 40 and rows[-1][3] == 1 and rows[-1][4] == 0x29      # x, level (1-2 = world 0 * 4 + 1), area


def test_frames_count_missed_polls_and_counter_wrap():
    tr = Trace().step(5, oper=0).screens(5)
    tr.run_level(100, every=3)                                                 # the poller sees every 3rd frame
    rec = recorder()
    tr.feed(rec)
    assert rec.live()["run_frame"] == 99 * 3 and rec.live()["level_frame"] == 99 * 3      # FrameCounter wraps (u8)


def test_paused_game_does_not_advance():
    tr = Trace().step(3, oper=0).screens(3).run_level(50)
    tr.step(100, every=0, pause=1)                                             # FrameCounter stands still while paused
    rec = recorder()
    tr.feed(rec)
    assert rec.live()["run_frame"] == 49


def test_castle_axe_splits_and_world_8_completes():
    tr = Trace().step(5, oper=0).screens(5, world=0, level=3).run_level(200, world=0, level=3, ap=0x65)
    tr.step(90, oper=2, sub=8)                                                 # 1-4 axe: victory mode, then world 2
    tr.step(1, oper=1, task=0, world=1, level=0, sub=0).screens(10, world=1).run_level(100, world=1)
    rec = recorder()
    tr.feed(rec)
    assert rec.run is not None and [s["level"] for s in rec.live()["splits"]] == ["1-4"]
    done = Trace()
    done.fc = tr.fc
    done.state = dict(tr.state)
    done.step(1, task=0, sub=0, world=7, level=3).screens(5, world=7, level=3).run_level(150, world=7, level=3)
    done.step(5, oper=2)
    out = done.feed(rec)
    assert [r["outcome"] for r in out] == ["complete"]
    run = out[0]
    assert run["splits"][-1]["level"] == "8-4" and run["frames"] == run["splits"][-1]["end"]
    assert run["time_s"] == pytest.approx(run["frames"] / GR.NES_FPS, abs=1e-3)


@pytest.mark.parametrize("oper, outcome", [(3, "game_over"), (0, "reset")])
def test_game_over_and_reset_end_the_run(oper, outcome):
    tr = Trace().step(5, oper=0).screens(5).run_level(80).step(1, oper=oper, task=0, sub=0)
    rec = recorder()
    (run,) = tr.feed(rec)
    assert run["outcome"] == outcome and rec.run is None


def test_short_runs_are_not_kept():
    tr = Trace().step(5, oper=0).screens(5).run_level(10).step(1, oper=0)
    assert tr.feed(recorder()) == []


def test_state_load_of_another_level_ends_the_run_and_starts_a_practice_run():
    tr = Trace().step(5, oper=0).screens(5).run_level(100)
    tr.step(1, world=3, level=1, x=500, scr=400, sub=8, task=3)               # in control, then suddenly 4-2
    tr.run_level(60, world=3, level=1, x0=500)
    rec = recorder()
    (old,) = tr.feed(rec)
    assert old["outcome"] == "state_loaded"
    assert rec.run["start_level"] == "4-2" and rec.run["assisted"] is True


def test_rewind_drops_the_undone_frames():
    tr = Trace().step(5, oper=0).screens(5).run_level(240)                   # timer 400 -> 391
    tr.step(1, x=200, scr=88, timer=396)                                       # RetroArch rewind: timer back up to 396
    tr.run_level(10, x0=202, timer=396)
    rec = recorder()
    tr.feed(rec)
    r = rec.run
    timers = r["timers"]
    assert r["rewinds"] == 1 and r["assisted"] is True
    assert all(a >= b for a, b in zip(timers, timers[1:])), "no undone frame survives"
    kept_before = 5 * 24                                                       # rows with timer >= 396 of the first 240
    assert len(r["rows"]) == kept_before + 1 + 10                              # + the frame the rewind landed on


def test_live_view_has_what_the_overlay_needs():
    tr = Trace().step(5, oper=0).screens(5).run_level(50, small=0, pw=1)
    rec = recorder()
    tr.feed(rec)
    v = rec.live()
    assert {"level", "ap", "scr", "x", "y", "relx", "rely", "run_frame", "level_frame", "splits", "fps"} <= set(v)
    assert v["small"] == 0 and v["level"] == "1-1"


# ------------------------------------------------------------------------------------------------ track / annotate
def test_track_round_trip():
    s = SMB.decode(ram(x=70000 % 65536, y=256 + 100, world=7, level=3, ap=0xFE, small=1, pw=2, joy=0x81, scr=999, sub=0x0B))
    rows = [GR.row_of(i * 2, s) for i in range(500)]
    back = GR.unpack_track(GR.pack_track(rows))
    assert back == rows and GR.TRACK_ROW == 18
    cols = GR.track_columns(back)
    assert cols["lv"][0] == 31 and cols["pw"][0] == 2 | 4 and cols["f"][-1] == 998


def meta(rid, start, outcome="session_end", splits=(), assisted=False, frames=1000, level="1-1"):
    return {"run_id": rid, "started_at": start, "outcome": outcome, "assisted": assisted, "frames": frames,
            "start_level": level, "splits": [{"level": l, "start": 0, "end": e, "frames": e, "segment": seg, "deaths": 0}
                                              for l, e, seg in splits]}


def test_annotate_best_progress_and_level_bests():
    runs = [meta("a1", 1, "complete", [("1-1", 500, 500), ("8-4", 9000, 700)], frames=9000),
            meta("a2", 2, "complete", [("1-1", 450, 450), ("8-4", 8800, 900)], frames=8800),
            meta("a3", 3, "game_over", [("1-1", 300, 300)]),
            meta("a4", 4, "game_over", [("1-1", 200, 200)], assisted=True),
            meta("p1", 5, "game_over", [("4-2", 900, 900)], level="4-1"),
            meta("p2", 6, "game_over", [("4-2", 800, 800), ("4-3", 1500, 700)], level="4-1")]
    out, lb = GR.annotate(runs)
    by = {r["run_id"]: r for r in out}
    assert [r["run_id"] for r in out][0] == "p2"                                # newest first
    assert by["a2"]["best"] and not by["a1"]["best"]
    assert by["p2"]["best_progress"] and not by["p1"]["best_progress"]          # further wins over faster
    assert lb["1-1"] == {"run_id": "a3", "frames": 300}                         # the assisted 200 does not count
    assert lb["8-4"]["run_id"] == "a1" and lb["4-3"]["run_id"] == "p2"
    prefs = dict(GR.DEFAULT_PREFS)
    assert GR.chosen(out, prefs | {"pick": "best"}, lb) == ["a2"]
    assert GR.chosen(out, prefs | {"pick": "last", "last_n": 2}, lb) == ["p2", "p1"]
    assert set(GR.chosen(out, prefs | {"pick": "pb_segments"}, lb)) == {"a3", "a1", "p2"}    # 1-1, 8-4, 4-2 + 4-3
    assert GR.chosen(out, prefs | {"pick": "custom", "shown": ["a1", "gone"]}, lb) == ["a1"]
    assert GR.chosen(out, prefs | {"pick": "none"}, lb) == []


# ------------------------------------------------------------------------------------------------ ghosts
def ghost_run():
    tr = Trace().step(5, oper=0).screens(5).run_level(100, speed=3)          # ghost: 3 px / frame
    tr.step(30, sub=0x0B).screens(10, lives=1).run_level(200, speed=2).step(1, sub=4)
    rec = recorder()
    tr.feed(rec)
    run = rec.finish()
    return run, GR.track_columns(GR.unpack_track(run["track"]))


def test_ghost_frame_level_sync_uses_the_clearing_attempt():
    run, cols = ghost_run()
    clear = run["attempts"][1]
    live = {"level": "1-1", "attempt_level": "1-1", "level_frame": 50, "run_frame": 9}
    assert GR.ghost_frame(run, live, "level") == clear["start"] + 50
    assert GR.ghost_frame(run, live, "run") == 9
    assert GR.ghost_frame(run, live | {"attempt_level": "5-1", "level": "5-1"}, "level") is None
    no_clear = {"attempts": [{"level": "3-1", "start": 0, "end": 900, "result": "death"},
                             {"level": "3-1", "start": 1000, "end": 1100, "result": "death"}]}
    assert GR.ghost_frame(no_clear, {"level": "3-1", "level_frame": 10}, "level") == 10    # no clear: its longest try
    row = GR.sample_at(cols, clear["start"] + 50)
    assert row["x"] == 40 + 2 * 50 and row["lv"] == 0


def test_sample_at_interpolates_small_gaps_only():
    cols = {k: [0, 0] for k in GR.TRACK_FIELDS} | {"f": [10, 14], "x": [100, 108], "y": [400, 404]}
    assert GR.sample_at(cols, 12)["x"] == 104 and GR.sample_at(cols, 12)["y"] == 402
    assert GR.sample_at(cols, 9) is None and GR.sample_at(cols, 30)["done"] is True
    far = cols | {"f": [10, 40]}
    assert GR.sample_at(far, 20)["x"] == 100                                   # a gap > 8 frames is not invented


def test_ghost_screen_projects_with_the_live_camera():
    row = {"x": 700, "y": 256 + 160, "lv": 0, "ap": 0xC2, "pw": 4, "face": 2, "anim": 8}
    live = {"level": "1-1", "ap": 0xC2, "scr": 600}
    g = GR.ghost_screen(row, live)
    assert (g["x"], g["y"], g["w"], g["h"], g["small"], g["visible"]) == (100, 176, 16, 16, True, True)
    big = GR.ghost_screen(row | {"pw": 1}, live)
    assert (big["y"], big["h"]) == (160, 32)
    assert GR.ghost_screen(row, live | {"scr": 100})["side"] == "right"
    left = GR.ghost_screen(row, live | {"scr": 800})
    assert left["side"] == "left" and left["distance"] == 100
    assert GR.ghost_screen(row, live | {"ap": 0x25}) is None                   # the ghost is in another room
    assert GR.ghost_screen(row, live | {"level": "1-2"}) is None
    assert GR.ghost_screen(row | {"y": 2 * 256 + 10}, live)["visible"] is False   # fell into a pit


def test_projection_matches_the_games_own_relative_x():
    """Player_Rel_XPos is what the game itself drew; the overlay's x - camera must equal it (checked live in Mesen
    on 2857 gameplay frames, docs/ghost-runs.md); here on a synthetic sweep across page boundaries."""
    for x in range(0, 4000, 37):
        scr = max(0, x - 112)
        s = SMB.decode(ram(x=x, scr=scr))
        row = dict(zip(GR.TRACK_FIELDS, GR.row_of(0, s)))
        g = GR.ghost_screen(row, {"level": "1-1", "ap": s["ap"], "scr": s["scr"]})
        assert g["x"] == s["relx"]


# ------------------------------------------------------------------------------------------------ worker capture
class FakeRetroArch:
    name = "retroarch"
    supported = ("read_memory",)

    def __init__(self, frames):
        self.frames, self.i, self.lock = frames, 0, threading.Lock()

    def _ram_offset(self, a):
        return a

    def cmd(self, text, reply=False, timeout=2.0):
        verb, addr, n = text.split()
        assert verb == "READ_CORE_RAM" and int(addr, 16) == 0 and int(n) == 0x800
        with self.lock:
            m = self.frames[min(self.i, len(self.frames) - 1)]
            self.i += 1
        return "READ_CORE_RAM 0 " + " ".join(f"{b:02X}" for b in m)

    def read_memory(self, a, n):
        raise AssertionError("one READ_CORE_RAM round trip per frame")


def test_read_block_falls_back_to_256_byte_reads():
    class Chunky:
        supported = ("read_memory",)
        calls = []

        def read_memory(self, a, n):
            self.calls.append((a, n))
            return bytes([a // 256]) * n
    ad = Chunky()
    m = GR.read_block(ad, 0, 0x800)
    assert len(m) == 0x800 and len(ad.calls) == 8 and m[0x7FF] == 7


def test_capture_posts_live_state_and_runs():
    tr = Trace().step(5, oper=0).screens(5).run_level(120).step(1, oper=3, task=0, sub=0)
    tr.step(10, oper=0)
    ad = FakeRetroArch(tr.frames)
    posts = []

    def post(method, path, body):
        posts.append((method, path, body))
        return {"ok": True}
    cap = GR.Capture("w1-s1", ad, {"game_id": "49b6a2f65aca26a2", "title": "Super Mario Bros."}, SMB, post, lambda: True)
    cap.start()
    end = time.time() + 10
    while ad.i < len(tr.frames) + 5 and time.time() < end:
        time.sleep(0.01)
    st = cap.stop()
    runs = [b for m, p, b in posts if p == "/api/ghosts/runs"]
    lives = [b for m, p, b in posts if p == "/api/ghosts/live/w1-s1"]
    assert [r["outcome"] for r in runs] == ["game_over"] and runs[0]["track"]
    assert lives and lives[-1] == {"on": False, "ended": True} and any(v.get("run_id") for v in lives)
    assert st["runs_posted"] == 1 and st["state"] == "stopped"


def test_start_only_for_profiled_games():
    assert GR.start("w1-x", object(), {"game_id": "x", "title": "Tetris", "platform": "nes"}, None, None, lambda: True)["state"] == "unsupported"
    ad = FakeRetroArch([ram(oper=0)])
    out = GR.start("w1-y", ad, {"game_id": "49b6a2f65aca26a2"}, None, None, lambda: True)
    try:
        assert out == {"state": "recording", "profile": "smb1"} and GR.get("w1-y") is not None
    finally:
        GR.stop("w1-y")
    assert GR.get("w1-y") is None


def test_ghost_runs_tool_is_registered():
    from gbox.registry import REGISTRY
    t = REGISTRY["ghost_runs"]
    assert "op=list" in t.description and t.In is GR.GhostRunsIn


# ------------------------------------------------------------------------------------------------ control plane
@pytest.fixture
def client(tmp_path):
    from fastapi import FastAPI, Header, HTTPException
    from fastapi.testclient import TestClient
    from gbox.store import Store
    app, store = FastAPI(), Store(tmp_path / "data")

    def auth(authorization: str = Header("")):
        if authorization != "Bearer t":
            raise HTTPException(401)
        return "operator"
    GR._LIVE.clear()
    GR.register(app, auth, store)
    c = TestClient(app)
    c.headers["authorization"] = "Bearer t"
    return c


def recorded(outcome="game_over", n=120, level_kw=None):
    tr = Trace().step(5, oper=0).screens(5).run_level(n, **(level_kw or {})).step(1, sub=4).step(5, sub=5)
    tr.step(1, oper=3 if outcome == "game_over" else 0, task=0, sub=0)
    (run,) = tr.feed(recorder())
    return run


def test_routes_store_list_rename_delete(client):
    gid = "49b6a2f65aca26a2"
    slow, fast = recorded(n=200), recorded(n=100)
    for r in (slow, fast):
        assert client.post("/api/ghosts/runs", json=r).status_code == 200
    g = client.get(f"/api/ghosts/game/{gid}").json()
    assert g["profile"]["key"] == "smb1" and g["profile"]["overlay"] == "projection"
    assert [r["run_id"] for r in g["runs"]] == [fast["run_id"], slow["run_id"]]
    assert all("track" not in r for r in g["runs"]) and g["runs"][0]["number"] == 2
    assert g["level_bests"]["1-1"]["run_id"] == fast["run_id"] and g["showing"]
    one = client.get(f"/api/ghosts/runs/{fast['run_id']}").json()
    assert len(one["track"]["f"]) == fast["samples"] and set(one["track"]) == set(GR.TRACK_FIELDS)
    assert client.patch(f"/api/ghosts/runs/{fast['run_id']}", json={"name": "  warpless  "}).json()["name"] == "warpless"
    client.post("/api/ghosts/runs", json=fast)                                 # a re-upload keeps the name
    assert client.get(f"/api/ghosts/runs/{fast['run_id']}").json()["name"] == "warpless"
    client.post(f"/api/ghosts/game/{gid}/prefs", json={"pick": "custom", "shown": [fast["run_id"], slow["run_id"]]})
    assert client.delete(f"/api/ghosts/runs/{slow['run_id']}").json() == {"deleted": slow["run_id"]}
    g = client.get(f"/api/ghosts/game/{gid}").json()
    assert [r["run_id"] for r in g["runs"]] == [fast["run_id"]] and g["prefs"]["shown"] == [fast["run_id"]]
    assert client.get(f"/api/ghosts/runs/{slow['run_id']}").status_code == 404
    assert client.post("/api/ghosts/runs", json=fast | {"track": "not base64!"}).status_code == 422
    assert client.post("/api/ghosts/runs", json=fast | {"run_id": "../x"}).status_code == 422


def test_routes_prefs_validate_and_merge_colours(client):
    gid = "49b6a2f65aca26a2"
    p = client.post(f"/api/ghosts/game/{gid}/prefs", json={"colors": {"aa": "#112233"}, "mode": "run"}).json()
    p = client.post(f"/api/ghosts/game/{gid}/prefs", json={"colors": {"bb": "#445566"}, "picture": {"aspect": "8:7"}}).json()
    assert p["colors"] == {"aa": "#112233", "bb": "#445566"} and p["mode"] == "run" and p["picture"]["aspect"] == "8:7"
    assert client.post(f"/api/ghosts/game/{gid}/prefs", json={"mode": "sideways"}).status_code == 422
    assert client.post(f"/api/ghosts/game/{gid}/prefs", json={"colors": {"aa": "red"}}).status_code == 422
    assert client.post(f"/api/ghosts/game/{gid}/prefs", json={"pick": "everything"}).status_code == 422


def test_routes_live_state_goes_stale_and_ends(client, monkeypatch):
    assert client.get("/api/ghosts/live/w1-s1").json()["on"] is False
    client.post("/api/ghosts/live/w1-s1", json={"on": True, "level": "1-1", "scr": 5})
    v = client.get("/api/ghosts/live/w1-s1").json()
    assert v["on"] and v["level"] == "1-1" and v["age"] < 1
    GR._LIVE["w1-s1"]["t"] -= GR.LIVE_STALE_S + 1
    assert client.get("/api/ghosts/live/w1-s1").json()["on"] is False
    client.post("/api/ghosts/live/w1-s1", json={"on": True})
    client.post("/api/ghosts/live/w1-s1", json={"on": False, "ended": True})
    assert "w1-s1" not in GR._LIVE
    assert client.get("/api/ghosts/live/w1-s1", headers={"authorization": "Bearer nope"}).status_code == 401


def test_game_without_profile_lists_no_profile(client):
    g = client.get("/api/ghosts/game/0000000000000000").json()
    assert g["profile"] is None and g["runs"] == []
