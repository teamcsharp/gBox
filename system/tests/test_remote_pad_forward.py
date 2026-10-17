"""#1532: a pad on the PC that views a Spark-hosted (streamed) session drives that session's Player 1.

The browser/desktop view posts {key, down, player: 1} to /api/sessions/{sid}/input; the session's worker pump
long-polls them and RetroArch's network RetroPad receives them. The desktop's XInput watcher feeds that view.
"""
import json
import socket
import struct
import threading
import time
from types import SimpleNamespace

from gbox import adapters, gamepads, padstate, tools


def _retroarch(port):
    a = object.__new__(adapters.RetroArchAdapter)
    a.remote_port, a.display, a.trigger_hotkeys = port, SimpleNamespace(name=":99"), False
    a.proc = SimpleNamespace(pid=None, poll=lambda: None)            # "running" for the pump's status loop
    a.supported = adapters.RetroArchAdapter.supported - {"stream_session"}
    return a


def test_view_pad_events_reach_the_remote_retroarch_player_one(plane, monkeypatch):
    monkeypatch.setattr(adapters, "HOST_OS", "linux")                 # lilspark: Linux RetroArch session
    monkeypatch.setattr(adapters.subprocess, "run", lambda *a, **kw: None)
    monkeypatch.setattr(padstate, "watch_xinput", lambda *a, **kw: None)
    sid = "lilspark-pad1532"
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sk:
        sk.bind(("127.0.0.1", 0)); sk.settimeout(10)
        tools.SESSIONS[sid] = (_retroarch(sk.getsockname()[1]), {})
        try:
            threading.Thread(target=tools._pump, args=(sid, tools.SESSIONS[sid][0], str(plane.base_url),
                                                       dict(plane.headers)), daemon=True).start()
            # exactly what the view's controller loop posts for Start on the operator's pad
            plane.post(f"/api/sessions/{sid}/input", json={"events": [{"key": "start", "down": True, "player": 1}]}).raise_for_status()
            down = struct.unpack("<iiiiH2x", sk.recv(64))
            assert plane.get(f"/api/sessions/{sid}/pad").json()["held"] == ["start"]
            plane.post(f"/api/sessions/{sid}/input", json={"events": [{"key": "start", "down": False, "player": 1}]}).raise_for_status()
            up = struct.unpack("<iiiiH2x", sk.recv(64))
        finally:
            tools.SESSIONS.pop(sid, None)
    assert down == (0, 1, 0, adapters.RETROPAD_ID["start"], 1)        # port 0 = Player 1, RetroPad Start pressed
    assert up == (0, 1, 0, adapters.RETROPAD_ID["start"], 0)


def _pad(slot=0, buttons=0, lx=0, **kw):
    return {"slot": slot, "buttons": buttons, "lt": 0, "rt": 0, "lx": lx, "ly": 0, "rx": 0, "ry": 0, **kw}


def test_xinput_watch_sends_changes_at_once_and_a_heartbeat_otherwise():
    t = [0.0]
    states = iter([[_pad()], [_pad()], [_pad(buttons=0x0010)], [_pad(buttons=0x0010, lx=300)],
                   [_pad(buttons=0x0010, lx=-300)], [_pad()], [_pad()], [_pad()], [_pad()]])
    reads, lines = [], []

    def read(slots=range(4)):
        reads.append(list(slots))
        return next(states)

    def sleep(dt):
        t[0] += dt
    gamepads.watch(lambda line: lines.append((round(t[0], 3), json.loads(line))), read=read, sleep=sleep,
                   clock=lambda: t[0], poll=0.1, heartbeat=0.25, rescan=1.0, ticks=9)
    held = [(at, [p["buttons"] for p in pads]) for at, pads in lines]
    # first state; Start down and up on the poll they happen; resting-stick jitter (±300) is quiet; then a heartbeat
    assert held == [(0.0, [0]), (0.2, [16]), (0.5, [0]), (0.8, [0])]
    assert reads[0] == list(range(4)) and reads[1] == [0]             # full scan once, then only the connected slot


def test_xinput_watch_rescans_when_a_pad_goes_away():
    t, reads = [0.0], []
    states = iter([[_pad(0), _pad(1)], [_pad(0)], [_pad(0)]])

    def read(slots=range(4)):
        reads.append(list(slots))
        return next(states)
    gamepads.watch(lambda line: None, read=read, sleep=lambda dt: t.__setitem__(0, t[0] + dt), clock=lambda: t[0],
                   poll=0.01, ticks=2)
    assert reads == [[0, 1, 2, 3], [0, 1], [0, 1, 2, 3]]
