"""Background gameplay ring recording (#1084): the pad gate, the segment index with ffmpeg's wrap, the range -> segment
selection, the size math, the encoder choice and fallback, the export and the recording tool, with a fake ffmpeg
(tests/fake_ffmpeg.py) and a fake Popen. GBOX_LIVE_FFMPEG=1 adds a run against the real ffmpeg (lavfi test picture)."""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from gbox import padstate, ring_record as rr
from gbox.config import Config, RecordingConfig
from gbox.registry import Ctx

FAKE = [sys.executable, str(Path(__file__).with_name("fake_ffmpeg.py"))]


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    rr.ACTIVE.clear(), rr.ENDED.clear(), rr.TOUCH.clear(), rr._ENCODERS.clear()
    for k in ("FAKE_ENCODERS", "FAKE_NVENC_BROKEN", "FAKE_NVENC_EXPORT_FAIL", "FAKE_OVERSHOOT", "FAKE_DIE_AFTER", "FAKE_HWND",
              "FAKE_TIME_SCALE", "FAKE_SEG_BYTES"):
        monkeypatch.delenv(k, raising=False)
    yield
    for ring in list(rr.ACTIVE.values()):
        ring.delete()
    rr.ACTIVE.clear(), rr.ENDED.clear()


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


class FakeStdin:
    def __init__(self):
        self.data, self.closed = b"", False

    def write(self, b):
        self.data += b

    def flush(self):
        pass

    def close(self):
        self.closed = True


class FakeProc:
    def __init__(self, argv, **kw):
        self.argv, self.kw, self.code, self.stdin = argv, kw, None, FakeStdin()

    def poll(self):
        return self.code

    def wait(self, timeout=None):
        if self.code is None:
            self.code = 0
        return self.code

    def kill(self):
        self.code = -9


class Popen:
    def __init__(self):
        self.procs = []

    def __call__(self, argv, **kw):
        p = FakeProc(argv, **kw)
        self.procs.append(p)
        return p


def ok_run(listing="h264_nvenc libx264", probe_rc=0, probe_err=""):
    calls = []

    def run(argv, **kw):
        calls.append(argv)
        if "-encoders" in argv:
            return subprocess.CompletedProcess(argv, 0, "\n".join(f" V....D {e}  x" for e in listing.split()), "")
        if any(str(a).startswith("color=") for a in argv):
            return subprocess.CompletedProcess(argv, probe_rc, "", probe_err)
        return subprocess.CompletedProcess(argv, 0, "", "")
    run.calls = calls
    return run


def make_ring(tmp_path, clock=None, touch=None, popen=None, run=None, **cfg):
    rc = RecordingConfig(**({"seconds": 20, "segment_s": 5, "idle_s": 20, "max_mb": 64, "bitrate_kbps": 1000, "fps": 30} | cfg))
    clock = clock or Clock()
    touch = touch if touch is not None else [0.0]
    src = {"kind": "x11grab", "size": [640, 480], "note": "test", "args": ["-f", "x11grab", "-i", ":91"]}
    ring = rr.SessionRing("w-1", tmp_path / "ring", rc, source_fn=lambda enc, fps: src, ffmpeg=FAKE,
                          activity=lambda: touch[0], clock=clock, popen=popen or Popen(), run=run or ok_run(),
                          meta={"game_id": "g1", "title": "Game"})
    return ring, clock, touch


def emit(ring, idx, dur, end, size=188 * 50):
    """What ffmpeg does when it finishes a segment: the file, its mtime, one csv line."""
    cur = ring.cur
    path = ring.dir / f"{cur['prefix']}{idx:03d}.ts"
    path.write_bytes(b"\x47" * size)
    os.utime(path, (end, end))
    n = sum(1 for _ in open(cur["list"], encoding="utf-8")) if cur["list"].exists() else 0
    with open(cur["list"], "a", encoding="utf-8") as f:
        f.write(f"{path.name},{n * dur:.6f},{(n + 1) * dur:.6f}\n")
    return path


# --- pad activity ---

def test_touch_counts_only_the_operators_pad():
    assert not rr.touch("s", [{"key": "a", "down": True}])                 # agent / autoplay / on-screen button
    assert not rr.touch("s", [{"rpc": 1, "op": "info", "player": 1}])
    assert rr.last_touch("s") == 0
    assert rr.touch("s", [{"key": "a", "down": True, "player": 1}], now=50.0)
    assert rr.last_touch("s") == 50.0


def test_last_touch_reuses_the_xinput_glyph_poll(monkeypatch):
    monkeypatch.setitem(padstate.PLAYER_TOUCH, "win-1", 77.0)                # set by padstate.watch_xinput on Windows
    assert rr.last_touch("win-1") == 77.0
    rr.TOUCH["win-1"] = 80.0
    assert rr.last_touch("win-1") == 80.0


# --- the idle gate ---

def test_records_only_while_the_pad_was_used_in_the_last_20_s(tmp_path):
    popen = Popen()
    ring, clock, touch = make_ring(tmp_path, popen=popen)
    ring.tick(1000.0)
    assert ring.proc is None and ring.status(1000.0)["state"] == "waiting"
    touch[0] = 1001.0
    ring.tick(1001.5)
    assert ring.proc is popen.procs[0] and ring.status(1001.5)["recording"]
    argv = popen.procs[0].argv
    assert argv[argv.index("-f", argv.index("-an")) + 1] == "segment" and "-segment_wrap" in argv
    assert argv[argv.index("-segment_time") + 1] == "5" and argv[argv.index("-c:v") + 1] == "h264_nvenc"
    assert argv[-1].endswith("r001-%03d.ts")
    ring.tick(1020.5)                                                         # 19.5 s after the last press: still on
    assert ring.proc is not None and ring.status(1020.5)["stops_in_s"] == 0.5
    ring.tick(1021.2)                                                         # 20 s idle: ffmpeg is asked to quit
    assert ring.proc is None and popen.procs[0].stdin.data == b"q"
    touch[0] = 1100.0
    ring.tick(1100.2)
    assert len(popen.procs) == 2 and popen.procs[1].argv[-1].endswith("r002-%03d.ts")


def test_disabled_ring_never_starts_and_disable_stops_a_run(tmp_path):
    popen = Popen()
    ring, clock, touch = make_ring(tmp_path, popen=popen, enabled=False)
    touch[0] = 1000.0
    ring.tick(1000.5)
    assert ring.proc is None and ring.status(1000.5)["state"] == "off"
    ring.set_enabled(True)
    ring.tick(1000.6)
    assert ring.proc is not None
    ring.set_enabled(False)
    assert ring.proc is None and popen.procs[0].stdin.data == b"q"


# --- the segment index, ffmpeg's wrap and the bounds ---

def test_rotation_follows_the_wrap_and_keeps_the_reach(tmp_path):
    ring, clock, touch = make_ring(tmp_path)
    touch[0] = 1000.0
    ring.tick(1000.0)
    wrap = ring.cur["wrap"]
    assert wrap == 7                                                          # 20 s / 5 s + 3 margin, well under max_mb
    t = 1000.0
    for n in range(12):                                                       # 60 s of play: the wrap comes round
        t += 5
        touch[0] = t
        emit(ring, n % wrap, 5.0, t)
        ring.tick(t + 0.2)
        files = [Path(s["file"]).name for s in ring.segments]
        assert len(files) == len(set(files)), "a rewritten file is listed once"
        assert f"r001-{(n + 1) % wrap:03d}.ts" not in files, "the file ffmpeg reopened next is not offered"
    st = ring.status(t + 0.2)
    assert [Path(s["file"]).name for s in ring.segments] == [f"r001-{i % wrap:03d}.ts" for i in range(8, 12)]
    assert st["span_s"] == 20.0 and st["segments"][0] == [5.0, 0.0] and st["segments"][-1] == [20.0, 15.0]
    assert ring.segments[-1]["end"] == t and ring.segments[-1]["start"] == pytest.approx(t - 5)


def test_runs_across_idle_gaps_and_the_disk_cap(tmp_path):
    ring, clock, touch = make_ring(tmp_path, seconds=60, max_mb=16)
    touch[0] = 1000.0
    ring.tick(1000.0)
    for i in range(3):
        emit(ring, i, 5.0, 1005.0 + 5 * i, size=4 * 2**20)
    ring.tick(1015.5)
    ring.tick(1040.0)                                                         # idle: run 1 stops
    assert ring.proc is None and len(ring.segments) == 3
    touch[0] = 2000.0
    ring.tick(2000.0)                                                         # run 2, a different file prefix
    for i in range(3):
        emit(ring, i, 5.0, 2005.0 + 5 * i, size=4 * 2**20)
    ring.tick(2015.5)
    assert sum(s["bytes"] for s in ring.segments) <= 16 * 2**20               # 6 x 4 MB > 16 MB: the oldest went
    assert [s["run"] for s in ring.segments] == [1, 2, 2, 2]
    assert not (ring.dir / "r001-000.ts").exists() and not (ring.dir / "r001-001.ts").exists()
    tl = ring.status(2015.5)["segments"]
    assert tl[0] == [5.0, 0.0] and tl[-1] == [20.0, 15.0]                     # the 985 s idle gap is not on the timeline


def test_ffmpeg_dying_backs_off_and_nvenc_falls_back_to_libx264(tmp_path):
    popen = Popen()
    ring, clock, touch = make_ring(tmp_path, popen=popen)
    touch[0] = 10**6
    ring.tick(1000.0)
    (ring.dir / "r001.log").write_text("[h264_nvenc] Error: encode session lost\n")
    popen.procs[0].code = 1
    ring.tick(1001.0)
    assert ring.proc is None and "encode session lost" in ring.error and ring.retry_at == 1011.0
    assert ring.status(1001.0)["state"] == "retrying"
    ring.tick(1011.0)
    popen.procs[1].code = 1
    ring.tick(1012.0)
    assert ring.encoder["encoder"] == "libx264" and "stopped twice" in ring.encoder["note"]
    ring.tick(1100.0)
    argv = popen.procs[2].argv
    assert argv[argv.index("-c:v") + 1] == "libx264" and "ultrafast" in argv


def test_live_segment_is_part_of_the_timeline(tmp_path):
    ring, clock, touch = make_ring(tmp_path)
    touch[0] = 1000.0
    ring.tick(1000.0)
    emit(ring, 0, 5.0, 1005.0)
    ring.tick(1005.1)
    live = ring.dir / "r001-001.ts"
    live.write_bytes(b"\x47" * (188 * 20 + 77))                               # mid-write: not a whole TS packet
    os.utime(live, (1007.0, 1007.0))
    clock.t = 1007.5
    st = ring.status()
    assert st["span_s"] == 7.0 and st["segments"][0] == [2.0, 0.0]
    work = tmp_path / "work"
    work.mkdir()
    sel = ring.snapshot(3.0, 0.0, work)
    assert [f.name for f in sel["files"]] == ["p000.ts", "p001.ts"] and sel["offset"] == 4.0
    assert (work / "p001.ts").stat().st_size == 188 * 20                      # cut at a whole packet


# --- range -> segments ---

def segs(*spans):
    return [{"file": f"s{i}.ts", "start": a, "end": b} for i, (a, b) in enumerate(spans)]


def test_select_range_maps_in_out_to_segments_and_trims():
    s = segs((0, 5), (5, 10), (100, 105), (105, 110))                         # an idle gap between 10 and 100
    r = rr.select_range(s, 12, 3)
    assert [p["file"] for p in r["pieces"]] == ["s1.ts", "s2.ts", "s3.ts"]
    assert r["offset"] == 3.0 and r["seconds"] == 9.0
    assert (r["pieces"][0]["from"], r["pieces"][-1]["to"]) == (3.0, 2.0)
    whole = rr.select_range(s, None)
    assert whole["seconds"] == 20.0 and len(whole["pieces"]) == 4 and whole["offset"] == 0
    assert rr.select_range(s, 500, 0)["in_s"] == 20.0                        # more than recorded: all of it
    last = rr.select_range(s, 4, 0)
    assert [p["file"] for p in last["pieces"]] == ["s3.ts"] and last["offset"] == 1.0
    with pytest.raises(ValueError, match="empty"):
        rr.select_range(s, 3, 3)
    with pytest.raises(ValueError, match="nothing recorded"):
        rr.select_range([], 30)


def test_timeline_runs_back_from_the_newest_moment():
    assert rr.timeline(segs((0, 5), (100, 104))) == [[4.0, 0.0], [9.0, 4.0]]


# --- size math ---

def test_bitrate_math_hits_the_file_size():
    k = rr.video_kbps(20, 60)
    assert k == int(20 * 8 * 2**20 * 0.97 / 60 / 1000) == 2712
    assert k * 1000 / 8 * 60 <= 20 * 2**20 * 0.98                            # leaves the container's share free
    assert rr.video_kbps(200, 30, cap_kbps=8000) == 8000                      # never above what the ring holds
    assert rr.video_kbps(1, 120) == rr.MIN_KBPS
    assert rr.fit_height(8000, 1920, 1080, 30) == 1080
    assert rr.fit_height(1500, 1920, 1080, 30) == 720                        # 1500k cannot carry 1080p30
    assert rr.fit_height(300, 1920, 1080, 30) == 360
    assert rr.fit_height(50, 640, 480, 30) == 240
    assert rr.fit_height(5000, 640, 480, 30) == 480                          # never upscaled


def test_wrap_count_respects_the_disk_cap():
    assert rr.wrap_count(120, 5, 8000, 512) == 27
    assert rr.wrap_count(120, 5, 8000, 16) == 3                               # 16 MB holds 3 segments at 8 Mb/s
    assert rr.wrap_count(30, 5, 1000, 512) == 9


# --- encoder choice ---

def test_encoder_choice_and_fallback_are_reported():
    run = ok_run()
    e = rr.pick_encoder("auto", FAKE, run)
    assert e == {"encoder": "h264_nvenc", "requested": "auto", "gpu": True, "note": "h264_nvenc (NVIDIA GPU)"}
    assert rr.pick_encoder("auto", FAKE, run) == e and len(run.calls) == 2       # cached: one test encode per worker run
    broken = rr.pick_encoder("auto", FAKE, ok_run(probe_rc=1, probe_err="x\nNo capable devices found"), cache=False)
    assert broken["encoder"] == "libx264" and not broken["gpu"] and "No capable devices found" in broken["note"]
    missing = rr.pick_encoder("hevc_nvenc", FAKE, ok_run(listing="libx264"), cache=False)
    assert missing["encoder"] == "libx264" and "hevc_nvenc is not in this ffmpeg build" in missing["note"]
    assert rr.pick_encoder("libx264", FAKE, ok_run(), cache=False)["note"] == "libx264 (CPU), as configured"


def test_encoder_choice_through_the_fake_ffmpeg(monkeypatch):
    assert rr.pick_encoder("auto", FAKE, cache=False)["encoder"] == "h264_nvenc"
    monkeypatch.setenv("FAKE_NVENC_BROKEN", "1")
    e = rr.pick_encoder("auto", FAKE, cache=False)
    assert e["encoder"] == "libx264" and "no capable devices" in e["note"]


def test_encoder_args():
    nv = rr.encoder_args("h264_nvenc", 8000, 30, 60, live=True)
    assert nv[:2] == ["-c:v", "h264_nvenc"] and "-pix_fmt" not in nv            # RGB in: converted on the GPU
    assert nv[nv.index("-b:v") + 1] == "8000k" and nv[nv.index("-rc") + 1] == "cbr"
    x = rr.encoder_args("libx264", 8000, 30, 60, live=True)
    assert x[x.index("-threads") + 1] == "2" and x[x.index("-pix_fmt") + 1] == "yuv420p"


# --- capture source ---

def test_capture_source_per_platform(monkeypatch):
    rc = RecordingConfig()
    ad = SimpleNamespace(display=SimpleNamespace(name=":91", w=641, h=480), proc=None)
    monkeypatch.setattr(rr, "HOST_OS", "linux")
    s = rr.resolve_source(ad, rc, "h264_nvenc", 30)
    assert s["kind"] == "x11grab" and s["size"] == [640, 480] and s["args"][-1] == ":91"
    monkeypatch.setattr(rr, "HOST_OS", "windows")
    win = SimpleNamespace(proc=SimpleNamespace(pid=42))
    screen = lambda: ((0, 0, 3840, 1080), (1920, 1080))
    s = rr.resolve_source(win, rc, "h264_nvenc", 30, rect_fn=lambda pid: (0x1234, 101, 50, 902, 651), screen_fn=screen)
    assert s["kind"] == "gdigrab" and s["size"] == [800, 600]
    assert s["args"][s["args"].index("-offset_x") + 1] == "101" and s["args"][-1] == "desktop"
    dda = rr.resolve_source(win, RecordingConfig(capture="ddagrab"), "h264_nvenc", 30,
                            rect_fn=lambda pid: (1, 100, 50, 900, 650), screen_fn=screen)
    assert dda["kind"] == "ddagrab" and "offset_x=100:offset_y=50:video_size=800x600" in dda["args"][-1]
    cpu = rr.resolve_source(win, RecordingConfig(capture="ddagrab"), "libx264", 30,
                            rect_fn=lambda pid: (1, 100, 50, 900, 650), screen_fn=screen)
    assert cpu["kind"] == "gdigrab" and "needs NVENC" in cpu["note"]
    monkeypatch.setenv("FAKE_HWND", "1")
    off = rr.resolve_source(win, rc, "h264_nvenc", 30, rect_fn=lambda pid: (0x1234, -32000, -32000, -31200, -31400),
                            screen_fn=screen, ffmpeg=FAKE)
    assert off["kind"] == "gdigrab-window" and off["args"][-1] == f"hwnd={0x1234}"
    with pytest.raises(RuntimeError, match="isn't open"):
        rr.resolve_source(win, rc, "libx264", 30, rect_fn=lambda pid: None, screen_fn=screen)


# --- export ---

def filled_ring(tmp_path, n=6, **cfg):
    ring, clock, touch = make_ring(tmp_path, seconds=60, **cfg)
    touch[0] = 1000.0
    ring.tick(1000.0)
    for i in range(n):
        emit(ring, i, 5.0, 1005.0 + 5 * i)
    clock.t = 1000.0 + 5 * n + 0.1
    ring.tick(clock.t)
    ring.ffmpeg = FAKE
    return ring, clock, touch


def calls(log):
    return [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []


def test_export_concatenates_trims_and_encodes_to_the_size(tmp_path, monkeypatch):
    log = tmp_path / "ffmpeg.jsonl"
    monkeypatch.setenv("FAKE_LOG", str(log))
    ring, clock, touch = filled_ring(tmp_path)
    ring.run = subprocess.run
    seen = {}
    real = rr._run

    def spy(run, argv, timeout=20):
        if "concat" in argv:
            lst = Path(argv[argv.index("-i") + 1])
            seen["list"] = lst.read_text(encoding="utf-8")
        return real(run, argv, timeout)
    monkeypatch.setattr(rr, "_run", spy)
    res = ring.export(22, 2, 2.0, out_dir=tmp_path / "out")
    exp = [c for c in calls(log) if "concat" in c][-1]
    assert seen["list"] == "".join(f"file 'p{i:03d}.ts'\n" for i in range(5))   # 22 s back from the end: 5 segments
    assert exp[exp.index("-ss") + 1] == "3.000" and exp[exp.index("-t") + 1] == "20.000"
    k = rr.video_kbps(2.0, 20, cap_kbps=1000)
    assert k == 813 and exp[exp.index("-b:v") + 1] == f"{k}k" and exp[exp.index("-c:v") + 1] == "h264_nvenc"
    assert res["bytes"] <= 2 * 2**20 and res["fits"] and res["seconds"] == 20.0 and res["encoder"] == "h264_nvenc"
    assert res["file"].read_bytes()[4:8] == b"ftyp" and res["height"] == 480
    assert not list(ring.dir.glob("ring-export-*")), "the copied segments are cleaned up"


def test_export_retries_smaller_when_it_overshoots(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_LOG", str(tmp_path / "log.jsonl"))
    monkeypatch.setenv("FAKE_OVERSHOOT", "1.3")
    ring, clock, touch = filled_ring(tmp_path)
    ring.run = subprocess.run
    res = ring.export(20, 0, 1.0, out_dir=tmp_path / "out")
    a, b = res["attempts"]
    assert b["kbps"] < a["kbps"] and a["bytes"] > 2**20 and res["kbps"] == b["kbps"]


def test_export_falls_back_to_libx264_when_nvenc_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_LOG", str(tmp_path / "log.jsonl"))
    monkeypatch.setenv("FAKE_NVENC_EXPORT_FAIL", "1")
    ring, clock, touch = filled_ring(tmp_path)
    ring.run = subprocess.run
    res = ring.export(10, 0, 5, out_dir=tmp_path / "out")
    assert res["encoder"] == "libx264" and "failed on the export" in res["encoder_note"]
    assert res["attempts"][0]["encoder"] == "h264_nvenc" and "out of memory" in res["attempts"][0]["error"]


# --- the real subprocess: rotation through ffmpeg's wrap and the 'q' stop ---

def test_fake_ffmpeg_process_rotates_and_stops_on_q(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_TIME_SCALE", "0.04")                           # a 5 s segment every 0.2 s
    monkeypatch.setattr(rr, "_low_priority", lambda level="low": {})                   # a busy test PC starves a below-normal start
    rc = RecordingConfig(seconds=10, segment_s=5, idle_s=20, max_mb=64, bitrate_kbps=1000)
    touch = [time.time()]
    ring = rr.SessionRing("w-2", tmp_path / "ring", rc, source_fn=lambda e, f: {"kind": "x11grab", "size": [320, 240],
                          "note": "", "args": ["-f", "x11grab", "-i", ":9"]}, ffmpeg=FAKE, activity=lambda: touch[0],
                          run=ok_run())
    ring.tick()
    assert ring.proc is not None
    wrap = ring.cur["wrap"]
    deadline = time.time() + 40
    while time.time() < deadline:
        time.sleep(0.25)
        ring.tick()
        if ring.cur["list"].exists() and sum(1 for _ in open(ring.cur["list"])) > wrap + 2:
            break                                                            # the wrap came round at least once
    names = [Path(s["file"]).name for s in ring.segments]
    # the fake writes 5 s segments every 0.2 s: wall time decides the span, so the wrap (not the reach) bounds the list here
    assert len(names) == len(set(names)) and 2 <= len(ring.segments) < wrap
    assert len(list(ring.dir.glob("r001-*.ts"))) <= wrap
    ring.set_enabled(False)                                                  # 'q': the last segment is closed and listed
    assert ring.proc is None and ring.cur is None


# --- the module hooks and the worker tool ---

def test_start_stop_keep_the_ended_ring_for_a_late_export(tmp_path, monkeypatch):
    monkeypatch.setattr(rr, "HOST_OS", "linux")
    cfg = Config(data_dir=tmp_path, runtime_dirs={rr.HOST_OS: str(tmp_path / "rt"), "windows": str(tmp_path / "rt"),
                                                  "linux": str(tmp_path / "rt")})
    ad = SimpleNamespace(display=SimpleNamespace(name=":91", w=640, h=480))
    st = rr.start("w-a", ad, cfg, {"game_id": "g", "title": "T"}, threads=False, ffmpeg=FAKE, run=ok_run())
    assert st["state"] == "waiting" and st["reach_s"] == 120 and st["idle_s"] == 20
    assert rr.start("w-x", SimpleNamespace(display=None), cfg, threads=False, ffmpeg=FAKE)["state"] == "unsupported"
    rr.start("w-b", ad, cfg, threads=False, ffmpeg=FAKE, run=ok_run())
    rr.stop("w-a")
    assert rr.ACTIVE["w-a"].ended and rr.status("w-a")["state"] == "ended"
    rr.stop("w-b")                                                           # keep_ended = 1: w-a's ring is deleted
    assert "w-a" not in rr.ACTIVE and "w-b" in rr.ACTIVE
    assert not (tmp_path / "rt" / "ring_record" / "w-a").exists()


def test_recording_tool_status_export_and_validation(tmp_path, monkeypatch):
    from gbox import tools
    monkeypatch.setenv("FAKE_LOG", str(tmp_path / "log.jsonl"))
    ring, clock, touch = filled_ring(tmp_path)
    ring.run = subprocess.run
    rr.ACTIVE["w-1"] = ring
    ctx = Ctx(Config(data_dir=tmp_path), "job1", "w")
    out = tools.recording(tools.RecordingIn(session_id="w-1"), ctx)
    assert out["op"] == "status" and out["status"]["span_s"] == 30.0 and out["status"]["encoder"] == "h264_nvenc"
    out = tools.recording(tools.RecordingIn(session_id="w-1", op="export", in_s=15, out_s=0, target_mb=3), ctx)
    name, data, mt, prov = ctx.artifacts[-1]
    assert mt == "video/mp4" and prov["session"] == "w-1" and prov["game"] == "g1" and prov["replay"]
    o = tools.RecordingOut(**out)
    assert tools._recording_validate(o, {name: data}) == []
    assert tools._recording_validate(o, {name: data + b"x"}) and tools._recording_validate(o, {})
    assert out["clip"]["seconds"] == 15.0 and "file" not in out["clip"]
    assert not list((tmp_path / "ring").glob("replay-*.mp4")), "the clip lives on as the artifact only"
    tools.recording(tools.RecordingIn(session_id="w-1", op="disable"), ctx)
    assert not ring.enabled
    with pytest.raises(KeyError, match="no gameplay ring"):
        tools.recording(tools.RecordingIn(session_id="nope"), ctx)


# --- opt-in: the real ffmpeg (NVENC when this PC has it) ---

@pytest.mark.skipif(os.environ.get("GBOX_LIVE_FFMPEG") != "1" or not shutil.which("ffmpeg"), reason="GBOX_LIVE_FFMPEG=1 runs real ffmpeg")
def test_live_ffmpeg_ring_and_export(tmp_path):
    rc = RecordingConfig(seconds=10, segment_s=2, idle_s=20, max_mb=64, bitrate_kbps=4000, priority="normal")
    touch = [time.time()]
    src = {"kind": "lavfi", "size": [640, 360], "note": "test picture",
           "args": ["-re", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30"]}
    ring = rr.SessionRing("live", tmp_path / "ring", rc, source_fn=lambda e, f: src, activity=lambda: touch[0])
    ring.tick()
    t0 = time.time()
    while time.time() - t0 < 12:
        time.sleep(1)
        touch[0] = time.time()                                               # the operator keeps playing
        ring.tick()
    st = ring.status()
    assert st["recording"] and st["span_s"] >= 5, st
    res = ring.export(5, 0, 1.0, out_dir=tmp_path)
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(res["file"])],
                           capture_output=True, text=True)
    assert abs(float(probe.stdout.strip()) - 5.0) < 0.5 and res["bytes"] <= 1.02 * 2**20, (res, probe.stdout)
    ring.delete()
    print(json.dumps({k: v for k, v in res.items() if k != "file"}), st["encoder_note"])
