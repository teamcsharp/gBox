"""Stranglehold x Tetris DS link (#1401): profile watch specs, pointer-path watches, and the full hands-free round with
fake adapters (local guest and a guest on another worker driven through the control plane)."""
import json
import struct
import time
from pathlib import Path

import pytest

from gbox import stranglehold, tools
from gbox.registry import Ctx

PROFILES = Path(__file__).resolve().parent.parent / "profiles"
GWORLD = 0x1032D740
PAWN_MODE = 0x20006000 + 0x13FC
TDS_P0_STATE, TDS_P1_STATE, TDS_LINES = 0x0217DD32, 0x0217E032, 0x0217DD38


class Mem:
    """Sparse emulated RAM with the adapter surface game_link uses."""
    name, supported = "fake", {"read_memory", "pause", "resume", "load_state"}

    def __init__(self):
        self.b, self.paused, self.loads, self.pauses = {}, False, 0, 0

    def write(self, a, data):
        for i, x in enumerate(data):
            self.b[a + i] = x

    def read_memory(self, a, n):
        return bytes(self.b.get(a + i, 0) for i in range(n))

    def pause(self):
        self.paused, self.pauses = True, self.pauses + 1

    def resume(self):
        self.paused = False

    def load_state(self):
        self.loads += 1


def stranglehold_ram() -> Mem:
    """GWorld -> World -> PersistentLevel -> Actors[0] (WorldInfo) -> ControllerList: an AI controller first, then the
    player controller (bIsPlayer) -> Pawn; big-endian 32-bit pointers like the PS3."""
    m = Mem()
    be = lambda v: struct.pack(">I", v)
    m.write(GWORLD, be(0x20000000))
    m.write(0x20000000 + 0x4C, be(0x20001000))
    m.write(0x20001000 + 0x38, be(0x20002000))
    m.write(0x20002000, be(0x20003000))
    m.write(0x20003000 + 0x338, be(0x20004000))           # AI controller: bIsPlayer clear
    m.write(0x20004000 + 0x1B8, be(0x20005000))
    m.write(0x20005000 + 0x1BC, be(0x80000000))           # player controller
    m.write(0x20005000 + 0x1AC, be(0x20006000))           # its pawn
    return m


@pytest.fixture
def fast(monkeypatch):
    real = time.sleep
    monkeypatch.setattr(tools.time, "sleep", lambda s: real(min(s, 0.005)))
    monkeypatch.setattr(stranglehold.time, "sleep", lambda s: real(min(s, 0.005)))
    return real


def wait(cond, real_sleep, n=400):
    for _ in range(n):
        if cond():
            return True
        real_sleep(0.005)
    return False


def test_profiles_carry_the_link_specs():
    sh = json.loads((PROFILES / "stranglehold-ps3-us.json").read_text(encoding="utf-8"))
    tds = json.loads((PROFILES / "tetris-ds-us.json").read_text(encoding="utf-8"))
    assert sh["link"]["trigger"]["address"] == "0x1032D740" and sh["link"]["trigger"]["eq"] == 2
    assert tds["game_id"] == "646664179043720f" and tds["match"]["gamecode"] == "ATRE"
    f = tds["fields"]
    assert (f["state"]["p0"], f["score"]["p0"], f["lines"]["p0"], f["level"]["p0"], f["piece"]["p0"]) == \
        ("0x0217DD32", "0x0217DD34", "0x0217DD38", "0x0217DD3C", "0x0217DD24")
    base, stride = int(tds["players"]["base"], 16), int(tds["players"]["stride"], 16)
    for name, field in f.items():                          # every p0 address = player base + offset
        if field.get("p0"):
            assert int(field["p0"], 16) == base + int(field["offset"], 16), name
    assert int(f["state"]["p1"], 16) == base + stride + int(f["state"]["offset"], 16)


def test_link_specs_from_profiles():
    s = stranglehold.link_specs("tetris_ds")
    assert s["round"] == "vs_cpu" and s["game_id"] == "646664179043720f"
    assert s["win"] == {"address": "0x0217E032", "type": "u8", "eq": 7}
    assert s["lose"] == {"address": "0x0217DD32", "type": "u8", "eq": 7}
    assert s["trigger"]["path"][-1] == {"add": "0x13FC"} and "evidence" not in s["trigger"]
    assert stranglehold.link_specs("tetris_ds", "sprint")["win"]["ge"] == 2
    with pytest.raises(ValueError, match="no round"):
        stranglehold.link_specs("tetris_ds", "marathon_200")
    with pytest.raises(ValueError, match="unknown guest"):
        stranglehold.link_specs("tetris_99")


def test_pointer_path_watch_follows_the_controller_list():
    m = stranglehold_ram()
    trig = stranglehold.link_specs("tetris_ds")["trigger"]
    assert tools._watch_address(m, trig, True) == PAWN_MODE
    assert not tools._watch_true(m, trig, True)
    m.write(PAWN_MODE, b"\x02")                            # Precision Aim
    assert tools._watch_true(m, trig, True)
    m.write(PAWN_MODE, b"\x03")                            # Barrage is not precision aim
    assert not tools._watch_true(m, trig, True)
    m.write(0x20005000 + 0x1AC, b"\0\0\0\0")               # no pawn (dead / loading): false, not an error
    assert tools._watch_address(m, trig, True) is None and not tools._watch_true(m, trig, True)
    empty = Mem()                                          # GWorld not set yet
    assert not tools._watch_true(empty, trig, True)


def test_watch_ge_any_all():
    m = Mem()
    m.write(TDS_LINES, struct.pack("<I", 2))
    assert tools._watch_true(m, {"address": hex(TDS_LINES), "type": "u32", "ge": 2}, False)
    assert not tools._watch_true(m, {"address": hex(TDS_LINES), "type": "u32", "ge": 3}, False)
    spec = {"any": [{"address": hex(TDS_P1_STATE), "type": "u8", "eq": 7}, {"address": hex(TDS_LINES), "type": "u32", "ge": 2}]}
    assert tools._watch_true(m, spec, False)
    assert not tools._watch_true(m, {"all": spec["any"]}, False)


def _start(monkeypatch, host_sid, guest_sid, ctx, style="pause", **kw):
    applied = []
    monkeypatch.setattr(tools, "script_patch", lambda inp, _ctx: applied.append((inp.session_id, inp.preset)) or {"result": {}})
    r = stranglehold.stranglehold_shot(stranglehold.StrangleholdShotIn(
        op="link", session_id=host_sid, guest="tetris_ds", guest_session_id=guest_sid, style=style, **kw), ctx)
    tools.LINKS[f"{host_sid}|{r['result']['guest_session_id']}"]["in"].poll_s = 0.005
    return r, applied


def test_link_round_with_local_guest(monkeypatch, fast):
    host, guest = stranglehold_ram(), Mem()
    tools.SESSIONS.update({"h-1": (host, {"platform": "ps3"}), "g-1": (guest, {"platform": "nds"})})
    try:
        r, applied = _start(monkeypatch, "h-1", "g-1", None)
        assert r["result"]["round"] == "vs_cpu" and r["result"]["running"]
        host.write(PAWN_MODE, b"\x02")                     # the player enters precision aim
        assert wait(lambda: host.paused and guest.loads == 1, fast)
        assert not guest.paused
        guest.write(TDS_P1_STATE, b"\x07")                 # the CPU tops out: the player wins
        assert wait(lambda: applied and not host.paused, fast)
        assert applied == [("h-1", "god_hit")] and guest.paused
        host.write(PAWN_MODE, b"\x00")                     # shot over
        guest.write(TDS_P1_STATE, b"\x02")
        assert wait(lambda: tools.LINKS["h-1|g-1"]["state"] == "waiting", fast)
        fast(0.1)                                          # the loop sees the aim end before the next one
        host.write(PAWN_MODE, b"\x02")                     # next shot: lose this time
        assert wait(lambda: guest.loads == 2, fast)
        guest.write(TDS_P0_STATE, b"\x07")
        assert wait(lambda: len(applied) == 2 and not host.paused, fast)
        assert applied[1] == ("h-1", "god_miss")
        out = tools.game_link(tools.LinkIn(op="stop", host="h-1", guest="g-1"), None)["result"]
        assert [h["verdict"] for h in out["history"]] == ["win", "lose"] and out["error"] is None
    finally:
        tools.game_link(tools.LinkIn(op="stop", host="h-1", guest="g-1"), None)
        tools.SESSIONS.pop("h-1", None), tools.SESSIONS.pop("g-1", None)


class FakePlane:
    """The control plane for a guest on another worker: session list, @launch, session rpc, session_op jobs."""

    def __init__(self, guest: Mem, running=False):
        self.guest, self.running, self.calls = guest, running, []

    def __call__(self, method, path, body=None):
        self.calls.append((method, path, (body or {}).get("op") or (body or {}).get("tool")))
        if path == "/api/sessions":
            return [{"session_id": "w2-tds", "game_id": "646664179043720f", "state": "running", "started": 5}] if self.running else []
        if path == "/api/jobs" and body["tool"] == "@launch":
            assert body["input"] == {"game_id": "646664179043720f", "node": "linux", "swap": False}
            return {"id": "j-launch", "state": "running"}
        if path == "/api/jobs/j-launch":
            self.running = True
            return {"id": "j-launch", "state": "succeeded", "output": {"session_id": "w2-tds"}}
        if path == "/api/jobs" and body["tool"] == "session_op":
            assert body["input"]["session_id"] == "w2-tds" and body["input"]["op"] == "load_state"
            self.guest.load_state()
            return {"id": "j-load", "state": "succeeded", "output": {"result": {"loaded": True}}}
        if path == "/api/sessions/w2-tds/rpc":
            op, args = body["op"], body["args"]
            if op == "info":
                return {"platform": "nds", "title": "Tetris DS (USA)", "emulator": "retroarch"}
            if op == "read_memory":
                return self.guest.read_memory(args["address"], args["length"]).hex()
            getattr(self.guest, op)()
            return {}
        raise AssertionError(f"unexpected {method} {path}")


def test_link_launches_a_remote_guest_and_plays_a_round_in_pip(monkeypatch, fast):
    host, guest = stranglehold_ram(), Mem()
    plane = FakePlane(guest)
    monkeypatch.setattr(stranglehold, "_api", lambda ctx, m, p, b=None: plane(m, p, b))
    monkeypatch.setattr(tools.RemoteSession, "_http", lambda self, m, p, b=None: plane(m, p, b))
    tools.SESSIONS["h-2"] = (host, {"platform": "ps3"})
    ctx = Ctx(type("C", (), {"runtime": "/tmp"})(), job_id="t", worker="t")
    ctx.server = "http://plane"
    try:
        r, applied = _start(monkeypatch, "h-2", "", ctx, style="pip")
        assert r["result"]["guest_session_id"] == "w2-tds" and r["result"]["guest_launched"] is True
        assert r["result"]["guest_remote"] is True
        host.write(PAWN_MODE, b"\x02")
        assert wait(lambda: host.paused and guest.loads == 1, fast)
        L = tools.LINKS["h-2|w2-tds"]
        assert wait(lambda: L.get("pip"), fast)
        assert L["pip"]["mjpeg"] == "/api/sessions/w2-tds/mjpeg"   # the app shows the guest's stream picture-in-picture
        guest.write(TDS_P0_STATE, b"\x07")                 # the player tops out
        assert wait(lambda: applied and not host.paused, fast)
        assert applied == [("h-2", "god_miss")] and guest.paused and L["pip"] is None
        assert ("POST", "/api/sessions/w2-tds/rpc", "resume") in plane.calls
    finally:
        tools.game_link(tools.LinkIn(op="stop", host="h-2", guest="w2-tds"), None)
        tools.SESSIONS.pop("h-2", None)


def test_link_reuses_a_running_guest(monkeypatch):
    plane = FakePlane(Mem(), running=True)
    monkeypatch.setattr(stranglehold, "_api", lambda ctx, m, p, b=None: plane(m, p, b))
    g = stranglehold.guest_session(None, "646664179043720f")
    assert g == {"session_id": "w2-tds", "launched": False}
    assert not any(c[1] == "/api/jobs" for c in plane.calls)


def test_failed_round_never_leaves_the_host_frozen(monkeypatch, fast):
    host, guest = stranglehold_ram(), Mem()

    def broken_load():
        raise RuntimeError("no save state parked")
    guest.load_state = broken_load
    tools.SESSIONS.update({"h-3": (host, {"platform": "ps3"}), "g-3": (guest, {"platform": "nds"})})
    try:
        _r, applied = _start(monkeypatch, "h-3", "g-3", None)
        host.write(PAWN_MODE, b"\x02")
        L = tools.LINKS["h-3|g-3"]
        assert wait(lambda: L["error"] and host.pauses, fast)
        assert wait(lambda: not host.paused, fast)
        assert "no save state parked" in L["error"] and not applied
        fast(0.05)
        assert host.pauses == 1                            # the same aim does not retrigger the failed round
    finally:
        tools.game_link(tools.LinkIn(op="stop", host="h-3", guest="g-3"), None)
        tools.SESSIONS.pop("h-3", None), tools.SESSIONS.pop("g-3", None)


def test_link_without_guest_or_addresses_is_refused():
    with pytest.raises(ValueError, match="guest_session_id"):
        stranglehold.stranglehold_shot(stranglehold.StrangleholdShotIn(op="link", session_id="h"), None)
