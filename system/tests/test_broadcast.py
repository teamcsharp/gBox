"""Broadcast feeds for Pine Box and media sources (gbox/broadcast.py, docs/broadcast.md).

Covers the program's choice (auto follows what the operator watches, pins, relaunches, session ends), the feed state
machine (live, hold, slate) with a fake clock, Windows game crops and stills, broadcast tokens and the route rules
(never the api_token in a URL; automation never switches the program), the MJPEG feed's constant rate across a switch
and a session end over a real HTTP server, the MPEG-TS GOP cutter, the H.264 encoder's supervision with a fake ffmpeg,
and the PipeWire sound tap. GBOX_LIVE_FFMPEG=1 adds a run of the real ffmpeg (MPEG-TS and HLS, ffprobed).
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import queue
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient
from PIL import Image

from gbox import broadcast as B
from gbox import live_stream, server
from gbox.config import BroadcastConfig, Config
from gbox.store import Store


def jpg(w: int = 64, h: int = 48, color=(200, 0, 0), quality: int = 80) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (w, h), color).save(out, "JPEG", quality=quality)
    return out.getvalue()


def color_of(data: bytes) -> tuple[int, int, int]:
    with Image.open(io.BytesIO(data)) as im:
        return im.convert("RGB").resize((1, 1)).getpixel((0, 0))


# --- pure helpers ------------------------------------------------------------------------------------------------

def test_jpeg_size_reads_the_frame_header_without_decoding():
    assert B.jpeg_size(jpg(640, 480)) == (640, 480)
    out = io.BytesIO()
    Image.new("RGB", (321, 123)).save(out, "JPEG", progressive=True)
    assert B.jpeg_size(out.getvalue()) == (321, 123)
    assert B.jpeg_size(b"\x89PNG\r\n\x1a\n...") is None and B.jpeg_size(b"") is None and B.jpeg_size(None) is None
    assert B.jpeg_size(b"\xff\xd8\xff\xda" + bytes(40)) is None


def test_part_slug_size_fps_and_paths():
    p = B.part(b"\xff\xd8x\xff\xd9")
    assert p.startswith(b"--gboxframe\r\nContent-Type: image/jpeg\r\nContent-Length: 5\r\n\r\n") and p.endswith(b"\r\n")
    assert B.slug("i9-NUC") == "i9nuc" and B.slug("JAYBUILTFINALE") == "jaybuiltfinale"
    assert B.parse_size("1280x720") == (1280, 720) and B.parse_size("963x541") == (962, 540)
    assert B.parse_size("bogus") == (1280, 720) and B.parse_size("10x10") == (1280, 720)
    assert B.clamp_fps("12", 30) == 12 and B.clamp_fps(0, 30) == 30 and B.clamp_fps(500, 30) == 60
    assert B.clamp_fps("x", 25) == 25
    assert B.feed_key({}) == "program" and B.feed_key({"pc": "i9-NUC"}) == "pc:i9nuc"
    assert B.feed_key({"sid": "w-1"}) == "session:w-1"
    assert B.feed_paths("pc:lilspark")["ts"] == "/api/broadcast/pc/lilspark.ts"
    assert B.feed_paths("session:w-1")["hls"] == "/api/broadcast/session/w-1/hls/index.m3u8"
    assert B.absolute(B.feed_paths("program"), "http://h:1/", "gbb_x")["mjpeg"] == \
        "http://h:1/api/broadcast/program.mjpg?token=gbb_x"
    assert B.absolute({"a": "/x"}, "") == {}


def test_live_stream_meter_marks_the_path_and_smooths_the_rate():
    lv = {"ts": 0}
    live_stream.meter(lv, 100.0, "still")
    assert lv["source"] == "still" and "fps" not in lv
    lv["ts"] = 100.0
    live_stream.meter(lv, 104.0, "still")
    assert lv["fps"] == pytest.approx(0.25)
    live_stream.meter(lv, 104.0, "stream")
    assert lv["source"] == "stream"
    live_stream.meter(lv, 105.0, "still")
    assert lv["source"] == "stream", "a streamed session stays streamed"
    lv2 = {"ts": 10.0}
    for i in range(1, 200):
        live_stream.meter(lv2, 10.0 + i / 60, "stream")
        lv2["ts"] = 10.0 + i / 60
    assert lv2["fps"] == pytest.approx(60, rel=0.05)


# --- MPEG-TS: joining at a GOP ------------------------------------------------------------------------------------

def pkt(pid: int, pusi: bool = False, rai: bool = False, fill: int = 0xFF) -> bytes:
    b1 = (0x40 if pusi else 0) | ((pid >> 8) & 0x1F)
    if rai:
        af = bytes([7, 0x40]) + b"\xff" * 6
        return bytes([0x47, b1, pid & 0xFF, 0x30]) + af + bytes([fill]) * (184 - len(af))
    return bytes([0x47, b1, pid & 0xFF, 0x10]) + bytes([fill]) * 184


SDT, PAT, PMT, VID, AUD = 0x11, 0, 0x1000, 0x100, 0x101


def stream():
    gop = [pkt(PAT), pkt(PMT), pkt(VID, True, True), pkt(VID), pkt(VID), pkt(AUD, True, True), pkt(VID)]
    return [pkt(SDT)] + gop + gop + [pkt(PAT), pkt(PMT), pkt(VID, True, True)]


def test_ts_gop_cuts_at_the_pat_before_each_video_keyframe():
    data = b"".join(stream())
    g = B.TsGop()
    pieces = g.feed(data) + g.flush()
    assert b"".join(p for p, _ in pieces) == data
    keyed = [p for p, k in pieces if k]
    starts = [p[:4] for p, k in pieces if k]
    assert len(starts) == 3 and all(s == pkt(PAT)[:4] for s in starts), "each GOP piece opens on its PAT"
    assert pieces[0] == (pkt(SDT), False)
    assert sum(len(p) for p in keyed[:2]) == 2 * 7 * B.TS, "an audio keyframe never cuts"


@pytest.mark.parametrize("chunk", [1, 7, 188, 200, 1000, 4096])
def test_ts_gop_gives_the_same_cuts_for_any_read_size(chunk):
    data = b"".join(stream())
    g, pieces = B.TsGop(), []
    for i in range(0, len(data), chunk):
        pieces += g.feed(data[i:i + chunk])
    pieces += g.flush()
    assert b"".join(p for p, _ in pieces) == data
    offsets, at = [], 0
    for p, k in pieces:
        if k:
            offsets.append(at)
        at += len(p)
    assert offsets == [B.TS, 8 * B.TS, 15 * B.TS], "a PAT just before a keyframe opens its piece across reads"


def test_ts_gop_resyncs_after_garbage():
    g = B.TsGop()
    out = g.feed(b"junk" + b"".join(stream())) + g.flush()
    assert b"".join(p for p, _ in out) == b"".join(stream())


# --- broadcast tokens -------------------------------------------------------------------------------------------------

def test_tokens_store_only_a_hash_check_touch_and_revoke(tmp_path):
    store = Store(tmp_path / "data")
    now = [1000.0]
    t = B.Tokens(store, clock=lambda: now[0])
    made = t.create("  Pine   Box ", "view")
    secret = made["token"]
    assert secret.startswith("gbb_") and made["name"] == "Pine Box" and "hash" not in made
    stored = store.get(B.TOKEN_KIND, made["id"])
    assert secret not in json.dumps(stored) and stored["hash"] == B._digest(secret)
    assert t.check(secret, "10.0.0.5")["name"] == "Pine Box"
    assert store.get(B.TOKEN_KIND, made["id"])["uses"] == 1
    now[0] += 5
    t.check(secret)
    assert store.get(B.TOKEN_KIND, made["id"])["uses"] == 1, "use is recorded at most once a minute"
    assert t.check("gbb_nope") is None and t.check("") is None and t.check("x" * 300) is None
    assert t.check(secret.removeprefix("gbb_")) is None
    with pytest.raises(ValueError):
        t.create("x", "admin")
    assert t.revoke(made["id"])["revoked"] and t.check(secret) is None
    assert "hash" not in store.get(B.TOKEN_KIND, made["id"])
    assert t.revoke("missing") is None
    assert [r["name"] for r in t.list()] == ["Pine Box"]


# --- which session is on air ----------------------------------------------------------------------------------------

def rows(*specs):
    return [{"session_id": sid, "pc": pc, "fresh": fresh, "agent_owned": agent, "started": started}
            for sid, pc, fresh, agent, started in specs]


def test_choose_follows_what_the_operator_watches_then_sticks():
    rs = rows(("a", "lilspark", True, False, 1), ("b", "i9-NUC", True, True, 2))
    pin = {"mode": "auto"}
    assert B.choose(pin, {"session_id": "b", "at": 100}, rs, current="a", now=110, watch_ttl_s=60) == \
        ("b", "following what you watch")
    assert B.choose(pin, {"session_id": "b", "at": 0}, rs, current="a", now=110, watch_ttl_s=60) == ("a", "still on air")
    assert B.choose(pin, {"session_id": None, "at": 100}, rs, current="a", now=110, watch_ttl_s=60)[0] == "a"
    assert B.choose(pin, None, rs, current=None, now=0, watch_ttl_s=60) == ("a", "newest game with a picture"), \
        "an operator game before an agent's"
    assert B.choose(pin, None, rs, current=None, now=0, watch_ttl_s=60, auto_agents=False)[0] == "a"
    assert B.choose(pin, None, rows(("b", "x", True, True, 1)), current=None, now=0, watch_ttl_s=60,
                    auto_agents=False) == (None, "no game is running")
    assert B.choose(pin, None, [], current="a", now=0, watch_ttl_s=60) == (None, "no game is running")
    stale = rows(("a", "lilspark", False, False, 5), ("c", "lilspark", True, True, 1))
    assert B.choose(pin, None, stale, current=None, now=0, watch_ttl_s=60)[0] == "c", "a picture beats none"
    assert B.choose(pin, None, stale, current="a", now=0, watch_ttl_s=60) == ("c", "newest game with a picture"), \
        "auto leaves a game that lost its picture for one that has one"
    dark = rows(("a", "lilspark", False, False, 5), ("c", "lilspark", False, True, 1))
    assert B.choose(pin, None, dark, current="c", now=0, watch_ttl_s=60) == ("c", "still on air"), \
        "...but never hops between games that all lack a picture"
    assert B.choose(pin, {"session_id": "a", "at": 0}, stale, current="c", now=1, watch_ttl_s=60) == \
        ("a", "following what you watch"), "what the operator watches goes on air, picture or not"


def test_choose_pins_and_follows_a_relaunch():
    rs = rows(("a", "lilspark", True, False, 1), ("b2", "i9-NUC", True, False, 2))
    succ = {"b": "b2"}.get
    assert B.choose({"mode": "session", "target": "a"}, {"session_id": "b2", "at": 9}, rs, current=None, now=10,
                    watch_ttl_s=60, successor=succ) == ("a", "pinned")
    assert B.choose({"mode": "session", "target": "b"}, None, rs, current=None, now=10, watch_ttl_s=60,
                    successor=succ) == ("b2", "pinned (its relaunch)")
    sid, why = B.choose({"mode": "session", "target": "gone"}, {"session_id": "a", "at": 9}, rs, current=None, now=10,
                        watch_ttl_s=60, successor=succ)
    assert sid == "a" and why == "the pinned session ended; following what you watch"
    match = lambda r, want: B.slug(r["pc"]) == B.slug(want)    # noqa: E731
    assert B.choose({"mode": "pc", "target": "i9nuc"}, None, rs, current="a", now=0, watch_ttl_s=60,
                    pc_match=match) == ("b2", "pinned to i9-NUC")
    assert B.choose({"mode": "pc", "target": "jaybuilt"}, None, rs, current="a", now=0, watch_ttl_s=60,
                    pc_match=match) == (None, "jaybuilt is not running a game")
    assert B.choose({"mode": "auto"}, {"session_id": "b", "at": 9}, rs, current="a", now=10, watch_ttl_s=60,
                    successor=succ)[0] == "b2", "a watched game that was swapped: its relaunch"


# --- the hub with a fake clock ----------------------------------------------------------------------------------------

class Clock:
    def __init__(self):
        self.t, self.w = 1000.0, 1_800_000_000.0

    def mono(self):
        return self.t

    def wall(self):
        return self.w

    def advance(self, s):
        self.t += s
        self.w += s


@pytest.fixture
def rig(tmp_path):
    store = Store(tmp_path / "data")
    clock = Clock()
    logs = []
    hub = B.Hub(store, BroadcastConfig(), live={}, desktop_frames={}, desktop_watch={}, host="lilspark",
                clock=clock.mono, wall=clock.wall, tmp_root=tmp_path / "enc", log=logs.append, autostart=False,
                agent_owned=lambda sid: sid.endswith("-bot"))
    store.put("worker", "spark", {"id": "spark", "name": "lilspark", "os": "linux", "last_seen": clock.w})
    store.put("worker", "jay", {"id": "jay", "name": "JAYBUILTFINALE", "os": "windows", "last_seen": clock.w})

    def session(sid, title, **more):
        store.put("session", sid, {"session_id": sid, "title": title, "game_id": title, "state": "running",
                                   "started": clock.w, **more})

    def frame(sid, data, source="stream"):
        lv = hub.live.setdefault(sid, {"seq": 0})
        lv.update(frame=data, ts=clock.w, seq=lv["seq"] + 1, source=source, fps=60.0)

    def tick():
        hub._rows_at = -1e9
        return hub.tick()
    return hub, store, clock, session, frame, tick, logs


def test_first_slate_is_not_ready_until_its_picture_exists(rig,monkeypatch):
    hub,store,clock,session,frame,tick,_=rig
    feed=hub.attach('pc:jaybuilt')
    entered,released=threading.Event(),threading.Event()
    picture=jpg(1280,720)
    def render(*args,**kwargs):
        entered.set()
        assert released.wait(2.)
        return picture
    monkeypatch.setattr(B,'render_slate',render)
    task=threading.Thread(target=tick)
    task.start()
    try:
        assert entered.wait(1.)
        assert not feed.resolved
    finally:
        released.set();task.join(2.)
    assert feed.resolved and feed.read()==picture


def test_program_goes_live_holds_through_a_stall_then_shows_a_slate(rig):
    hub, store, clock, session, frame, tick, _ = rig
    session("spark-a", "Dead or Alive 2", detail={"display": ":91"})
    red = jpg(640, 480, (200, 0, 0))
    frame("spark-a", red)
    f = hub.attach("program")
    tick()
    assert (f.resolved, f.sid, f.kind, f.mode) == (True, "spark-a", "spark_capture", "live")
    assert f.read() == red and f.why == "newest game with a picture"
    clock.advance(hub.s.hold_s - 1)
    tick()
    assert f.mode == "live" and f.read() == red, "a quiet source repeats its picture"
    clock.advance(2)
    tick()
    assert f.mode == "slate"
    slate = f.read()
    assert B.jpeg_size(slate) == (640, 480), "the slate keeps the picture's size"
    assert slate != red and max(color_of(slate)) < 120, "the last picture, dimmed"
    tick()
    assert f.read() is slate, "a slate is drawn once"
    blue = jpg(640, 480, (0, 0, 200))
    frame("spark-a", blue)
    tick()
    assert f.mode == "live" and f.read() == blue


def test_switching_holds_the_old_picture_until_the_new_one_comes(rig):
    hub, store, clock, session, frame, tick, _ = rig
    session("spark-a", "A")
    session("spark-b", "B")
    red, blue = jpg(color=(200, 0, 0)), jpg(color=(0, 0, 200))
    frame("spark-a", red)
    f = hub.attach("program")
    hub.set_program("session", "spark-a")
    tick()
    assert f.read() == red
    hub.set_program("session", "spark-b")
    tick()
    assert (f.sid, f.mode, f.read()) == ("spark-b", "hold", red)
    clock.advance(B.SWITCH_WAIT_S + 0.5)
    tick()
    assert f.mode == "slate" and f.read() != red
    frame("spark-b", blue)
    tick()
    assert f.mode == "live" and f.read() == blue
    assert store.get("setting", B.PROGRAM_SETTING)["target"] == "spark-b", "the pin is kept across restarts"


def test_a_session_end_holds_its_last_frame_then_the_program_moves_on(rig):
    hub, store, clock, session, frame, tick, _ = rig
    session("spark-a", "A")
    session("spark-b", "B")
    red, blue = jpg(color=(200, 0, 0)), jpg(color=(0, 0, 200))
    frame("spark-a", red)
    frame("spark-b", blue)
    f = hub.attach("program")
    hub.report_watch("spark-b")
    tick()
    assert f.sid == "spark-b" and f.read() == blue and f.why == "following what you watch"
    store.put("session", "spark-b", store.get("session", "spark-b") | {"state": "ended"})
    tick()
    assert f.mode == "hold" and f.read() == blue
    clock.advance(hub.s.end_hold_s + 0.1)
    tick()
    assert f.sid == "spark-a" and f.read() == red
    store.put("session", "spark-a", store.get("session", "spark-a") | {"state": "ended"})
    tick()
    clock.advance(hub.s.end_hold_s + 0.1)
    tick()
    assert f.sid is None and f.mode == "slate" and f.why == "no game is running"
    assert B.jpeg_size(f.read()) == B.jpeg_size(red)


def test_a_pinned_session_that_is_relaunched_stays_on_air(rig):
    hub, store, clock, session, frame, tick, _ = rig
    session("spark-a", "A")
    session("spark-x", "X")
    frame("spark-a", jpg(color=(200, 0, 0)))
    frame("spark-x", jpg(color=(0, 200, 0)))
    f = hub.attach("program")
    hub.set_program("session", "spark-a")
    tick()
    red = f.read()
    store.put("session", "spark-a", store.get("session", "spark-a") | {"state": "ended", "replaced_by": "spark-a2"})
    session("spark-a2", "A (swapped)")
    frame("spark-a2", jpg(color=(0, 0, 200)))
    tick()
    assert f.mode == "hold" and f.read() == red, "the swap's moment: the last picture holds"
    clock.advance(hub.s.end_hold_s + 0.1)
    tick()
    assert f.sid == "spark-a2" and f.why == "pinned (its relaunch)" and color_of(f.read())[2] > 150
    assert hub.pin["target"] == "spark-a2" and hub.pin["by"] == "gbox-broadcast"
    tick()
    assert f.sid == "spark-a2" and f.why == "pinned"


def test_pc_and_session_feeds(rig):
    hub, store, clock, session, frame, tick, _ = rig
    session("spark-a", "A")
    frame("spark-a", jpg(color=(200, 0, 0)))
    pc = hub.attach("pc:spark1")                                # Pine Box's name for the Spark
    one = hub.attach("session:spark-a")
    tick()
    assert pc.sid == "spark-a" and pc.why == "what lilspark runs now" and one.sid == "spark-a"
    store.put("session", "spark-a", store.get("session", "spark-a") | {"state": "ended", "replaced_by": "spark-a2"})
    session("spark-a2", "A again")
    frame("spark-a2", jpg(color=(0, 0, 200)))
    clock.advance(hub.s.end_hold_s + 0.1)
    tick()
    tick()
    assert pc.sid == "spark-a2" and one.sid == "spark-a2" and one.why == "its relaunch"
    nobody = hub.attach("pc:jaybuilt")
    tick()
    assert nobody.sid is None and nobody.mode == "slate" and nobody.why == "jaybuilt is not running a game"


def test_windows_game_crop_renews_the_desktop_watch_then_falls_back_to_stills(rig):
    hub, store, clock, session, frame, tick, _ = rig
    session("jay-x", "Soul Calibur II", detail={"local_window": True, "worker_name": "JAYBUILTFINALE"})
    desk = Image.new("RGB", (1600, 900), (40, 40, 40))
    desk.paste((0, 180, 0), (400, 225, 1200, 675))
    out = io.BytesIO()
    desk.save(out, "JPEG", quality=85)
    hub.desktop_frames["jay"] = {"image": out.getvalue(), "game_rects": {"jay-x": (0.25, 0.25, 0.5, 0.5)},
                                 "app_rect": None, "seq": 1, "ts": clock.w}
    f = hub.attach("program")
    tick()                                                      # the feed learns its session
    tick()                                                      # ...and cuts the desktop frame
    assert hub.desktop_watch["jay"] == pytest.approx(clock.w + B.DESKTOP_RENEW_S)
    assert f.kind == "desktop_crop" and f.mode == "live"
    crop = f.read()
    assert B.jpeg_size(crop) == (800, 450)
    r, g, b = color_of(crop)
    assert g > 150 and r < 40, "only the game window, never the rest of the desktop"
    still = jpg(320, 240, (0, 0, 220))
    clock.advance(B.CROP_STALE_S + 1)
    frame("jay-x", still, source="still")
    tick()
    assert f.kind == "stills" and f.read() == still
    clock.advance(B.STILLS_STALE_S + 1)
    tick()
    assert f.mode == "slate" and f.why


def test_feeds_are_dropped_when_nobody_reads_them(rig):
    hub, store, clock, session, frame, tick, _ = rig
    f = hub.attach("program")
    tick()
    hub.detach(f)
    assert tick() is True
    clock.advance(B.FEED_IDLE_S + 1)
    assert tick() is False and not hub.feeds


def test_refresh_reports_kinds_freshness_and_agent_ownership(rig):
    hub, store, clock, session, frame, tick, _ = rig
    session("spark-a", "A")
    session("spark-bot", "Bot")
    session("jay-x", "Native", detail={"local_window": True})
    frame("spark-a", jpg(320, 240))
    rows = {r["session_id"]: r for r in hub.refresh(force=True)}
    assert rows["spark-a"]["kind"] == "spark_capture" and rows["spark-a"]["fresh"]
    assert rows["spark-bot"]["agent_owned"] and not rows["spark-bot"]["fresh"]
    assert rows["jay-x"]["kind"] == "desktop_crop" and rows["jay-x"]["pc"] == "JAYBUILTFINALE"
    assert hub.resolution_of(rows["spark-a"]) == [320, 240] and hub.fps_of(rows["spark-a"]) == 60.0
    clock.advance(10)
    assert hub.fps_of(rows["spark-a"]) == 0.0, "a stalled source reports 0 fps"


# --- the H.264 encoder with a fake ffmpeg ------------------------------------------------------------------------------

class FakeOut:
    def __init__(self):
        self.q = queue.Queue()

    def read1(self, n):
        try:
            return self.q.get(timeout=10)
        except queue.Empty:
            return b""


class FakeProc:
    def __init__(self, argv, **kw):
        self.argv, self.kw = argv, kw
        self.stdin, self.stdout, self.stderr = io.BytesIO(), FakeOut(), io.BytesIO(b"bad option\n")
        self.code, self.pid, self.killed = None, 4242, False

    def poll(self):
        return self.code

    def kill(self):
        self.killed, self.code = True, -9
        self.stdout.q.put(b"")


def make_encoder(tmp_path, **settings):
    procs = []

    def popen(argv, **kw):
        procs.append(FakeProc(argv, **kw))
        return procs[-1]
    clock = Clock()
    feed = B.Feed("program", clock.mono)
    feed.mode, feed.last = "hold", jpg()
    enc = B.Encoder(feed, BroadcastConfig(audio="off", **settings), tmp_path / "enc", popen=popen, clock=clock.mono,
                    log=lambda m: None, ffmpeg="ffmpeg")
    return enc, procs, clock


def test_encoder_argv_tee_mpegts_and_hls(tmp_path):
    enc, _, _ = make_encoder(tmp_path)
    a = enc.argv()
    joined = " ".join(a)
    assert "-f mjpeg -framerate 30 -i pipe:0" in joined and "-c:v libx264" in joined and "-preset ultrafast" in joined
    assert "scale=1280:720:force_original_aspect_ratio=decrease" in joined and "pad=1280:720" in joined
    assert "-g 30" in joined and "-bf 0" in joined and "-b:v 2500k" in joined
    assert a[a.index("-f", a.index("-bf")) + 1] == "tee"
    assert a[-1].startswith("[f=mpegts:mpegts_flags=+pat_pmt_at_frames") and "]pipe:1|[f=hls:" in a[-1]
    assert a[-1].endswith("]index.m3u8") and "start_number=0" in a[-1] and "discont_start" not in a[-1]
    assert 'hls_list_size=12' in a[-1] and 'hls_delete_threshold=12' in a[-1]
    if os.name == "posix" and shutil.which("nice"):
        assert a[:3] == ["nice", "-n", "10"]
    with_audio = " ".join(enc.argv(audio_fd=7, start_number=12))
    assert '-thread_queue_size 64 -f mjpeg' in with_audio
    assert '-thread_queue_size 256 -f s16le' in with_audio
    assert "-f s16le -ar 48000 -ac 2 -i pipe:7" in with_audio and "-map 1:a" in with_audio and "-c:a aac" in with_audio
    assert "start_number=12" in with_audio and "discont_start" in with_audio
    nv, _, _ = make_encoder(tmp_path, encoder="h264_nvenc", size="960x540", ts_fps=25, video_kbps=1800)
    j = " ".join(nv.argv())
    assert "-c:v h264_nvenc" in j and "scale=960:540" in j and "-framerate 25" in j and "-b:v 1800k" in j


def test_hls_window_and_recently_referenced_segment_grace_are_configured_together(tmp_path):
    enc, _, _ = make_encoder(tmp_path, hls_window_segments=18, hls_retained_segments=24)
    assert 'hls_list_size=18' in enc.argv()[-1]
    assert 'hls_delete_threshold=24' in enc.argv()[-1]
    from pydantic import ValidationError
    for settings in ({'hls_window_segments':0}, {'hls_retained_segments':1},
                     {'hls_window_segments':61}, {'hls_retained_segments':121}):
        with pytest.raises(ValidationError):
            BroadcastConfig(**settings)


def test_encoder_feeds_pictures_and_restarts_a_dead_or_stuck_ffmpeg(tmp_path):
    enc, procs, clock = make_encoder(tmp_path)
    enc.start()
    time.sleep(0.25)
    first = procs[0]
    assert enc.frames_in >= 3 and first.stdin.getvalue().startswith(b"\xff\xd8")
    assert first.kw["cwd"] == str(enc.dir) and enc.state == "running"
    first.code = 1
    first.stdout.q.put(b"")
    assert enc.check(clock.t) == "scheduled" and enc.state == "restarting"
    assert enc.check(clock.t) is None, "backoff"
    (enc.dir / "seg_00007.ts").write_bytes(b"x")
    assert enc.check(clock.t + 1) == "restarted" and len(procs) == 2 and enc.restarts == 1
    assert "start_number=8" in procs[1].argv[-1] and "discont_start" in procs[1].argv[-1], "HLS numbering goes on"
    enc.last_write = clock.t - enc.STALL_S - 1
    assert enc.check(clock.t) == "scheduled" and procs[1].killed, "a stuck ffmpeg is killed"
    enc.stop()
    assert enc.closed and not enc.dir.exists()


def test_late_ts_viewers_start_at_the_newest_gop_and_laggards_skip_to_the_next(tmp_path):
    enc, _, _ = make_encoder(tmp_path)
    loop = asyncio.new_event_loop()
    try:
        early = enc.subscribe(loop)
        g = B.TsGop()
        for piece, key in g.feed(b"".join(stream())) + g.flush():
            enc._deliver(piece, key)
        loop.run_until_complete(asyncio.sleep(0))
        got = b""
        while not early.q.empty():
            got += early.q.get_nowait()
        assert got == b"".join(stream())
        late = enc.subscribe(loop)
        cached = late.q.get_nowait()
        assert cached.startswith(pkt(PAT)[:4]) and len(cached) == 3 * B.TS, "the newest GOP, from its PAT"
        lag = B.Sub(loop)
        for _ in range(B.SUB_QUEUE):
            lag.offer(b"x")
        lag.offer(b"y")
        assert lag.lagging and lag.dropped == 1
        lag.offer(b"z", key=True)
        assert lag.lagging, "still too full"
        while lag.q.qsize() > B.SUB_QUEUE // 2:
            lag.q.get_nowait()
        lag.offer(b"no")
        lag.offer(b"gop", key=True)
        assert not lag.lagging and lag.q.qsize() == B.SUB_QUEUE // 2 + 1
    finally:
        loop.close()


def test_encoder_wanted_while_read_and_for_a_linger_after(tmp_path):
    enc, _, clock = make_encoder(tmp_path)
    loop = asyncio.new_event_loop()
    try:
        sub = enc.subscribe(loop)
        assert enc.wanted(clock.t + 999, 20)
        clock.advance(5)
        enc.unsubscribe(sub)
        assert enc.wanted(clock.t + 19, 20) and not enc.wanted(clock.t + 21, 20)
        enc.touch_hls()
        assert enc.wanted(clock.t + 19, 20)
    finally:
        loop.close()


def test_hub_limits_encoders_and_stops_unwatched_ones(rig, tmp_path):
    hub, store, clock, session, frame, tick, logs = rig
    procs = []
    hub.popen = lambda argv, **kw: procs.append(FakeProc(argv, **kw)) or procs[-1]
    hub.s = BroadcastConfig(max_encoders=1, audio="off")
    enc = hub.encoder("program")
    assert hub.encoder("program") is enc and hub.feeds["program"].encoders == 1
    with pytest.raises(RuntimeError, match="1 H.264 feeds"):
        hub.encoder("pc:lilspark")
    feed = hub.feeds["program"]
    clock.advance(hub.s.linger_s + 1)
    tick()
    assert enc.closed and not hub.encoders and feed.encoders == 0
    assert "program" not in hub.feeds, "...and its feed once nobody reads that either"
    assert any("stopped (nobody reads it)" in m for m in logs)


# --- sound ---------------------------------------------------------------------------------------------------------

def test_sink_input_for_finds_the_emulator_stream_by_its_display():
    items = [{"index": 7, "properties": {"application.name": "Pine Radio"}},
             {"index": 38665, "properties": {"window.x11.display": ":177", "application.name": "Dolphin Emulator"}}]
    run = lambda argv, **kw: subprocess.CompletedProcess(argv, 0, json.dumps(items).encode(), b"")   # noqa: E731
    which = lambda name: "/usr/bin/pactl"                                                          # noqa: E731
    assert B.sink_input_for(":177", run=run, which=which) == 38665
    assert B.sink_input_for(":91", run=run, which=which) is None
    assert B.sink_input_for(":177", run=run, which=lambda n: None) is None
    bad = lambda argv, **kw: subprocess.CompletedProcess(argv, 1, b"not json", b"")              # noqa: E731
    assert B.sink_input_for(":177", run=bad, which=which) is None


def test_audio_stream_pid_isolates_cubeb_and_refuses_ambiguity():
    items = [{"index": 1, "properties": {"application.process.id": "12", "application.name": "radio"}},
             {"index": 2, "properties": {"application.process.id": "34", "application.name": "RPCS3"}},
             {"index": 3, "properties": {"application.process.id": "56", "window.x11.display": ":90"}}]
    run = lambda argv, **kw: subprocess.CompletedProcess(argv, 0, json.dumps(items).encode(), b"")
    which = lambda name: "/usr/bin/pactl"
    assert B.sink_input_for(":90", pid=34, run=run, which=which) == 2
    assert B.sink_input_for(":90", pid=99, run=run, which=which) is None
    items.append({"index": 4, "properties": {"application.process.id": "34"}})
    assert B.sink_input_for(":90", pid=34, run=run, which=which) is None
    items[:] = [{"index": 5, "properties": {"window.x11.display": ":90"}}]
    assert B.sink_input_for(":90", pid=34, run=run, which=which) == 5
    items.append({"index": 6, "properties": {"window.x11.display": ":90"}})
    assert B.sink_input_for(":90", pid=34, run=run, which=which) is None


class PcmProc:
    def __init__(self, argv, **kw):
        self.argv, self.code = argv, None
        self.stdout = FakeOut()

    def poll(self):
        return self.code

    def kill(self):
        self.code = -9
        self.stdout.q.put(b"")


def test_audio_tap_copies_one_stream_and_never_runs_ahead(tmp_path):
    procs = []
    tap = B.AudioTap(38665, popen=lambda argv, **kw: procs.append(PcmProc(argv, **kw)) or procs[-1])
    assert "--monitor-stream=38665" in procs[0].argv and "--format=s16le" in procs[0].argv
    procs[0].stdout.q.put(b"\x01\x00" * 4000)
    procs[0].stdout.q.put(b"\x02\x00" * int(B.AUDIO_BYTES_S))         # a second's backlog: only the newest 0.4 s stay
    deadline = time.time() + 5
    while len(tap.buf) < 16 and time.time() < deadline:
        time.sleep(0.01)
    time.sleep(0.1)
    assert len(tap.buf) <= int(B.AUDIO_BYTES_S * B.AUDIO_BUFFER_S) and len(tap.buf) % 4 == 0
    got = tap.take(10)
    assert len(got) == 8 and got == b"\x02\x00" * 4
    tap.close()
    assert not tap.alive()


def test_retap_follows_the_feed_session(tmp_path):
    enc, procs, clock = make_encoder(tmp_path)
    taps = []
    enc.audio_for = lambda feed: {"spark-a": 11, "spark-b": 22}.get(feed.sid)
    enc.popen = lambda argv, **kw: taps.append(PcmProc(argv, **kw)) or taps[-1]
    enc.feed.sid, enc.feed.mode = "spark-a", "live"
    enc.retap(clock.t)
    assert enc.tap.index == 11
    enc.feed.sid = "spark-b"
    enc.retap(clock.t + 0.1)
    assert enc.tap.index == 22 and taps[0].code == -9
    enc.feed.mode = "slate"
    enc.retap(clock.t + 0.2)
    assert enc.tap is None, "a slate has no sound"
    enc.feed.sid, enc.feed.mode = "spark-x", "live"
    enc.retap(clock.t + 0.3)
    assert enc.tap is None and enc.tap_checked == clock.t + 0.3
    enc.audio_for = lambda feed: 33
    enc.retap(clock.t + 1)
    assert enc.tap is None, "looked for again only every few seconds"
    enc.retap(clock.t + 0.3 + B.AUDIO_RECHECK_S)
    assert enc.tap.index == 33
    enc.stop()
    assert enc.tap is None and taps[-1].code == -9


def test_audio_writer_keeps_time_with_silence_and_the_tap(tmp_path):
    enc, _, _ = make_encoder(tmp_path)
    enc.clock = time.monotonic

    class Tap:
        def take(self, n):
            return b"\x05\x00" * (min(n, 960) // 2)
    r, w = os.pipe()
    sentinel = object()
    enc.proc, enc.tap = sentinel, Tap()
    enc._reset_media(sentinel)
    got = bytearray()

    def drain():
        with os.fdopen(r, "rb", buffering=0) as f:
            while chunk := f.read(65536):
                got.extend(chunk)
    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    writer = threading.Thread(target=enc._write_audio, args=(sentinel, w), daemon=True)
    writer.start()
    def video():
        while not enc.closed:
            enc._accept_video(sentinel)
            time.sleep(1/enc.fps)
    video_writer=threading.Thread(target=video,daemon=True);video_writer.start()
    time.sleep(0.5)
    enc.closed = True
    writer.join(5)
    reader.join(5)
    seconds = len(got) / B.AUDIO_BYTES_S
    assert 0.3 < seconds < 0.75 and len(got) % 4 == 0
    assert b"\x05\x00" in got and b"\x00\x00\x00\x00" in got, "the tap's samples, padded with silence"


def test_media_clock_is_per_process_and_does_not_advance_after_restart(tmp_path):
    enc,_,_=make_encoder(tmp_path)
    old,new=object(),object();enc.proc=old;enc._reset_media(old)
    for _ in range(30):assert enc._accept_video(old)
    assert enc.status()['media_video_s']==1
    enc.proc=new;enc._reset_media(new)
    assert not enc._accept_video(old)
    assert enc.status()['media_video_s']==0 and enc.status()['media_audio_s']==0


@pytest.mark.skipif(os.environ.get('GBOX_LIVE_FFMPEG')!='1' or not shutil.which('ffprobe'),
                    reason='set GBOX_LIVE_FFMPEG=1 for real large-MJPEG/audio starvation regression')
def test_real_large_mjpeg_audio_startup_and_video_only_starvation_recover_on_same_timeline(tmp_path):
    # Deliberately larger than a pipe, so first-frame acceptance cannot merely
    # mean a small JPEG sat in an OS buffer while FFmpeg waited for audio.
    image=Image.frombytes('RGB',(640,480),__import__('random').Random(31).randbytes(640*480*3))
    stream=io.BytesIO();image.save(stream,'JPEG',quality=95);jpeg=stream.getvalue()
    assert len(jpeg)>65536
    trigger,blocked=threading.Event(),threading.Event()
    class Source:
        key='private-av-regression'
        def read(self):
            if trigger.is_set():
                trigger.clear();blocked.set();time.sleep(2.)
            return jpeg
    captured=bytearray();processes=[]
    class Output:
        def __init__(self,raw):self.raw=raw
        def read1(self,n):
            data=self.raw.read1(n);captured.extend(data);return data
        def __getattr__(self,name):return getattr(self.raw,name)
    def popen(argv,**kw):
        proc=subprocess.Popen(argv,**kw);proc.stdout=Output(proc.stdout);processes.append(proc);return proc
    cfg=BroadcastConfig(audio='auto',ts_fps=10,size='320x240',video_kbps=400,nice=19)
    enc=B.Encoder(Source(),cfg,tmp_path/'encode',audio_for=lambda feed:None,popen=popen,
                  clock=time.monotonic,log=lambda m:None,ffmpeg=shutil.which('ffmpeg') or 'ffmpeg')
    startup=time.monotonic();snapshots=[]
    try:
        enc.dir.mkdir(parents=True);enc._spawn()
        deadline=startup+18
        while time.monotonic()<deadline and (enc.bytes_out==0 or enc._media['video_frames']<20):
            assert enc.proc.poll() is None,list(enc.errors)
            time.sleep(.05)
        assert enc.bytes_out>0,'Large first MJPEG + actual PCM must start without input-probe deadlock'
        trigger.set();assert blocked.wait(2)
        before=enc.status();time.sleep(1.)
        during=enc.status()
        assert during['media_video_s']==before['media_video_s']
        assert during['media_audio_s']<=during['media_video_s']+.021
        until=time.monotonic()+4
        while time.monotonic()<until:
            snapshots.append(enc.status());time.sleep(.1)
        final=enc.status()
        assert final['media_video_s']>before['media_video_s']+1
        assert -.15<=final['audio_lead_s']<=.021
        assert final['output_age_s'] is not None and final['output_age_s']<1
        assert enc.playlist() and len(list(enc.dir.glob('seg_*.ts')))>=2
    finally:
        enc.stop()
        for proc in processes:proc.wait(timeout=5)
    path=tmp_path/'actual-av.ts';path.write_bytes(captured)
    result=subprocess.run(['ffprobe','-v','error','-show_packets','-show_entries',
        'packet=codec_type,pts_time','-of','json',str(path)],capture_output=True,text=True,timeout=15)
    assert result.returncode==0,result.stderr[-2000:]
    packets=json.loads(result.stdout)['packets']
    ends={kind:max(float(p['pts_time']) for p in packets if p.get('codec_type')==kind and 'pts_time' in p)
          for kind in ('video','audio')}
    assert min(ends.values())>2 and abs(ends['video']-ends['audio'])<.2,ends
    (tmp_path/'real-av-receipt.json').write_text(json.dumps({'jpeg_bytes':len(jpeg),'ends':ends,
        'before_stall':before,'during_stall':during,'after_recovery':final,'samples':snapshots}))


# --- routes ------------------------------------------------------------------------------------------------------------

@pytest.fixture
def app(tmp_path):
    cfg = Config(data_dir=tmp_path / "data", cache_dir=tmp_path / "cache", public_url="http://10.89.1.246:8765")
    cfg.broadcast.tailnet_url = "http://lilspark.tail1fec29.ts.net:8765"
    a = server.create_app(cfg)
    a.cfg = cfg
    store = a.state.store
    store.put("worker", "spark", {"id": "spark", "name": "lilspark", "os": "linux", "last_seen": time.time() + 3600,
                                  "tools": []})
    store.put("session", "spark-a", {"session_id": "spark-a", "game_id": "doa2", "title": "Dead or Alive 2",
                                     "state": "running", "started": time.time(), "detail": {"display": ":91"}})
    yield a
    a.state.broadcast.close()


def main(app, actor=None):
    h = {"Authorization": "Bearer " + app.cfg.token()}
    return h | ({"x-gbox-actor": actor} if actor else {})


def test_feeds_list_every_live_session_with_stable_urls(app):
    c = TestClient(app)
    f = jpg(640, 480)
    body = b"".join(len(f).to_bytes(4, "big") + f for _ in range(3))
    assert c.post("/api/sessions/spark-a/stream", content=body, headers=main(app)).json() == {"frames": 3}
    d = c.get("/api/broadcast/feeds", headers=main(app)).json()
    assert d["program"]["session_id"] == "spark-a" and d["program"]["mode"] == "auto"
    assert d["program"]["lan"]["mjpeg"] == "http://10.89.1.246:8765/api/broadcast/program.mjpg"
    assert d["program"]["tailnet"]["ts"] == "http://lilspark.tail1fec29.ts.net:8765/api/broadcast/program.ts"
    (feed,) = d["feeds"]
    assert feed["id"] == "session/spark-a" and feed["kind"] == "spark_capture" and feed["resolution"] == [640, 480]
    assert feed["title"] == "Dead or Alive 2" and feed["pc"] == "lilspark" and feed["live"]
    assert feed["last_frame_age_s"] is not None and feed["paths"]["hls"] == "/api/broadcast/session/spark-a/hls/index.m3u8"
    assert feed["pc_paths"]["mjpeg"] == "/api/broadcast/pc/lilspark.mjpg"
    (pc,) = d["pcs"]
    assert pc["pc"] == "lilspark" and pc["aliases"] == ["spark1"] and pc["session_id"] == "spark-a"
    assert d["formats"]["mjpeg"] == "multipart/x-mixed-replace; boundary=gboxframe"


def test_tokens_auth_rules(app):
    c = TestClient(app)
    assert c.get("/api/broadcast/feeds").status_code == 401
    r = c.get("/api/broadcast/feeds?token=" + app.cfg.token())
    assert r.status_code == 401 and "never goes in a URL" in r.text
    assert c.post("/api/broadcast/tokens", json={"name": "x"}, headers=main(app, "agent")).status_code == 403
    made = c.post("/api/broadcast/tokens", json={"name": "Pine Box"}, headers=main(app)).json()
    tok = made["token"]
    assert made["scope"] == "view" and made["program"]["lan"]["ts"].endswith("/api/broadcast/program.ts?token=" + tok)
    d = c.get("/api/broadcast/feeds?token=" + tok).json()
    assert d["program"]["lan"]["mjpeg"].endswith("?token=" + tok), "URLs carry the token they were asked with"
    assert c.get("/api/broadcast/feeds", headers={"Authorization": "Bearer " + tok}).status_code == 200
    assert c.get("/api/broadcast/feeds?t=" + tok).status_code == 200
    assert c.get("/api/broadcast/tokens?token=" + tok).status_code == 403, "tokens cannot list tokens"
    assert c.post("/api/broadcast/program?token=" + tok, json="auto").status_code == 403, "view tokens only watch"
    assert c.get(f"/api/sessions/spark-a/mjpeg?token={tok}").status_code == 401, "broadcast routes only"
    assert c.get("/api/workers?token=" + tok).status_code == 401
    listed = c.get("/api/broadcast/tokens", headers=main(app)).json()
    assert listed[0]["name"] == "Pine Box" and "hash" not in listed[0] and "token" not in listed[0]
    assert c.delete("/api/broadcast/tokens/" + made["id"], headers=main(app)).json()["revoked"]
    assert c.get("/api/broadcast/feeds?token=" + tok).status_code == 401
    assert c.delete("/api/broadcast/tokens/nope", headers=main(app)).status_code == 404
    ctl = c.post("/api/broadcast/tokens", json={"name": "Pine Box", "scope": "control"}, headers=main(app)).json()
    assert c.post("/api/broadcast/program?token=" + ctl["token"], json={"session_id": "spark-a"}).status_code == 200
    assert c.post("/api/broadcast/tokens", json={"scope": "root"}, headers=main(app)).status_code == 422


def test_program_switch_rules_and_watching(app):
    c = TestClient(app)
    store = app.state.store
    r = c.post("/api/broadcast/program", json={"session_id": "spark-a"}, headers=main(app))
    assert r.json()["pin"] == r.json()["pin"] | {"mode": "session", "target": "spark-a", "by": "operator"}
    assert r.json()["program"]["session_id"] == "spark-a"
    for actor in ("agent", "hermes", "mcp"):
        assert c.post("/api/broadcast/program", json="auto", headers=main(app, actor)).status_code == 403
    assert c.post("/api/broadcast/program", json={"session_id": "nope"}, headers=main(app)).status_code == 409
    assert c.post("/api/broadcast/program", json={"pc": "toaster"}, headers=main(app)).status_code == 404
    assert c.post("/api/broadcast/program", json={"pc": "spark1"}, headers=main(app)).json()["pin"]["mode"] == "pc"
    assert c.post("/api/broadcast/program", json="auto", headers=main(app)).json()["pin"]["mode"] == "auto"
    assert any(e["action"] == "broadcast.program" for e in store.audit_for("auto"))
    store.put("session", "spark-b", {"session_id": "spark-b", "title": "B", "state": "running", "started": 1})
    w = c.post("/api/broadcast/watching", json={"session_id": "spark-b"}, headers=main(app) | {"x-gbox-client": "web"})
    assert w.json()["program"]["session_id"] == "spark-b" and w.json()["program"]["why"] == "following what you watch"
    assert w.json()["watch"]["client"] == "web"
    ignored = c.post("/api/broadcast/watching", json={"session_id": "spark-a"}, headers=main(app, "agent")).json()
    assert "ignored" in ignored and app.state.broadcast.watch["session_id"] == "spark-b"
    assert c.post("/api/broadcast/watching", json={"session_id": "../x"}, headers=main(app)).status_code == 422
    st = c.get("/api/broadcast", headers=main(app)).json()
    assert st["program"]["watching"]["session_id"] == "spark-b" and st["program"]["watching"]["counts"]
    assert st["urls"]["lan"]["hls"] == "http://10.89.1.246:8765/api/broadcast/program/hls/index.m3u8"


def test_jpeg_and_bad_feed_names(app):
    c = TestClient(app)
    tok = c.post("/api/broadcast/tokens", json={"name": "t"}, headers=main(app)).json()["token"]
    f = jpg(320, 240, (0, 200, 0))
    c.post("/api/sessions/spark-a/stream", content=len(f).to_bytes(4, "big") + f, headers=main(app))
    r = c.get("/api/broadcast/session/spark-a.jpg?token=" + tok)
    assert r.status_code == 200 and r.content == f and r.headers["x-gbox-state"] == "live"
    slate = c.get("/api/broadcast/pc/jaybuilt.jpg?token=" + tok)
    assert slate.status_code == 200 and B.jpeg_size(slate.content) == (1280, 720)
    assert c.get("/api/broadcast/session/a..b.jpg?token=" + tok).status_code == 404
    assert c.get("/api/broadcast/session/x/hls/evil.sh?token=" + tok).status_code == 404


def test_broadcast_can_be_switched_off(tmp_path):
    cfg = Config(data_dir=tmp_path / "data", cache_dir=tmp_path / "cache")
    cfg.broadcast.enabled = False
    a = server.create_app(cfg)
    assert TestClient(a).get("/api/broadcast", headers={"Authorization": "Bearer " + cfg.token()}).status_code == 404


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def live_server(app):
    port = free_port()
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    threading.Thread(target=srv.run, daemon=True).start()
    deadline = time.time() + 30
    while not srv.started and time.time() < deadline:
        time.sleep(0.05)
    stop = threading.Event()
    yield f"http://127.0.0.1:{port}", stop
    stop.set()
    srv.should_exit = True


def push(base, h, sid, color, stop, fps=30, size=(320, 240)):
    def body():
        while not stop.is_set():
            data = jpg(*size, color)
            yield len(data).to_bytes(4, "big") + data
            time.sleep(1 / fps)
    try:
        with httpx.Client(base_url=base, headers=h, timeout=None) as c:
            c.post(f"/api/sessions/{sid}/stream", content=body())
    except httpx.HTTPError:
        pass


def parts(buf: bytes) -> list[bytes]:
    out = []
    for chunk in buf.split(b"--gboxframe\r\n")[1:]:
        head, _, rest = chunk.partition(b"\r\n\r\n")
        n = int(head.split(b"Content-Length: ")[1].split(b"\r\n")[0])
        out.append(rest[:n])
    return out


def test_mjpeg_program_keeps_a_constant_rate_through_a_switch_and_a_session_end(app, live_server):
    base, stop = live_server
    store = app.state.store
    store.put("session", "spark-b", {"session_id": "spark-b", "title": "B", "state": "running", "started": time.time()})
    h = main(app)
    for sid, color in (("spark-a", (220, 0, 0)), ("spark-b", (0, 0, 220))):
        threading.Thread(target=push, args=(base, h, sid, color, stop), daemon=True).start()
    c = httpx.Client(base_url=base, headers=h, timeout=30)
    c.post("/api/broadcast/program", json={"session_id": "spark-a"})
    tok = c.post("/api/broadcast/tokens", json={"name": "test"}).json()["token"]
    time.sleep(0.5)
    buf, marks, ended = bytearray(), [], False
    with httpx.Client(base_url=base, timeout=30) as viewer:
        with viewer.stream("GET", f"/api/broadcast/program.mjpg?fps=20&token={tok}") as r:
            assert r.status_code == 200 and r.headers["x-gbox-fps"] == "20"
            t0 = time.time()
            for chunk in r.iter_bytes():
                buf.extend(chunk)
                t = time.time() - t0
                if t > 1.0 and not marks:
                    marks.append(len(parts(bytes(buf))))
                    switched = c.post("/api/broadcast/program", json={"session_id": "spark-b"}).json()["program"]
                    assert (switched["session_id"], switched["why"]) == ("spark-b", "pinned"), \
                        "the answer shows the switch done (the hub ticked)"
                if t > 2.5 and not ended:
                    ended = True
                    marks.append(len(parts(bytes(buf))))
                    store.put("session", "spark-b", store.get("session", "spark-b") | {"state": "ended"})
                if t > 7.0:
                    break
    frames = parts(bytes(buf))
    assert 120 <= len(frames) <= 155, f"{len(frames)} frames in 7 s at 20 fps"
    assert all(f.startswith(b"\xff\xd8") and f.endswith(b"\xff\xd9") for f in frames)
    colors = [color_of(f) for f in frames]
    reds = lambda xs: sum(1 for r_, g_, b_ in xs if r_ > 150 and b_ < 80)    # noqa: E731
    blues = lambda xs: sum(1 for r_, g_, b_ in xs if b_ > 150 and r_ < 80)   # noqa: E731
    assert reds(colors[:marks[0]]) >= marks[0] - 2, "A on air"
    assert blues(colors[marks[0] + 5:marks[1]]) >= marks[1] - marks[0] - 8, "B after the switch"
    assert blues(colors[marks[1]:marks[1] + 30]) >= 28, "B's last frame holds when it ends"
    assert reds(colors[-15:]) >= 13, "then A again: the pinned game ended, the program is back on auto"
    assert app.state.broadcast.pin["mode"] == "auto"
    deadline = time.time() + 5
    while app.state.broadcast.feeds.get("program") and app.state.broadcast.feeds["program"].viewers and             time.time() < deadline:
        time.sleep(0.05)
    assert not app.state.broadcast.feeds.get("program") or app.state.broadcast.feeds["program"].viewers == 0
    stop.set()


@pytest.mark.skipif(os.environ.get("GBOX_LIVE_FFMPEG") != "1" or not shutil.which("ffprobe"),
                    reason="set GBOX_LIVE_FFMPEG=1 to run the real ffmpeg")
def test_real_ffmpeg_program_as_mpegts_and_hls(app, live_server, tmp_path):
    base, stop = live_server
    store = app.state.store
    store.put("session", "spark-b", {"session_id": "spark-b", "title": "B", "state": "running", "started": time.time()})
    h = main(app)
    threading.Thread(target=push, args=(base, h, "spark-a", (220, 0, 0), stop, 30, (640, 480)), daemon=True).start()
    threading.Thread(target=push, args=(base, h, "spark-b", (0, 0, 220), stop, 30, (960, 720)), daemon=True).start()
    c = httpx.Client(base_url=base, headers=h, timeout=60)
    c.post("/api/broadcast/program", json={"session_id": "spark-a"})
    tok = c.post("/api/broadcast/tokens", json={"name": "test"}).json()["token"]
    got, switched = bytearray(), False
    with httpx.Client(base_url=base, timeout=60) as viewer:
        with viewer.stream("GET", f"/api/broadcast/program.ts?token={tok}") as r:
            assert r.status_code == 200 and r.headers["content-type"] == "video/mp2t"
            t0 = time.time()
            for chunk in r.iter_bytes():
                got.extend(chunk)
                if time.time() - t0 > 2 and not switched:
                    switched = True
                    c.post("/api/broadcast/program", json={"session_id": "spark-b"})
                if time.time() - t0 > 5:
                    break
    path = tmp_path / "program.ts"
    path.write_bytes(bytes(got))
    probe = json.loads(subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-show_entries",
                                       "stream=codec_name,width,height,nb_read_frames", "-of", "json", str(path)],
                                      capture_output=True, text=True, timeout=60).stdout)
    (stream_,) = [s for s in probe["streams"] if s["codec_name"] == "h264"]
    assert (stream_["width"], stream_["height"]) == (1280, 720) and int(stream_["nb_read_frames"]) >= 75   # ~150 at 30 fps
    pl = httpx.get(f"{base}/api/broadcast/program/hls/index.m3u8?token={tok}", timeout=60)
    assert pl.status_code == 200 and "#EXTINF" in pl.text
    seg = next(line for line in pl.text.splitlines() if line and not line.startswith("#"))
    assert seg.endswith("?token=" + tok)
    assert httpx.get(f"{base}/api/broadcast/program/hls/{seg}", timeout=60).content[:1] == b"\x47"
    stop.set()


NODE = shutil.which("node")


@pytest.mark.skipif(not NODE, reason="node is not installed")
def test_client_broadcast_controls_cjs():
    """The On air button, the watching heartbeat and the Sessions list's Broadcast bar (clients/web/viz/broadcast.js)."""
    r = subprocess.run([NODE, "--test", str(Path(__file__).with_name("test_broadcast_control.cjs"))],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-2000:]
