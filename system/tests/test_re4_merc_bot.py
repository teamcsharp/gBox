"""RE4 Mercenaries playbook (gbox.re4_merc_bot): RAM reading, targeting, teleport, prompts, and autoplay picking it."""
import math
import struct
from types import SimpleNamespace

import pytest

from gbox import re4_merc_bot as B


class FakeMem:
    """MEM1 as a bytearray at 0x80000000."""

    def __init__(self):
        self.b = bytearray(0x400000)

    def rd(self, a, n):
        o = a - 0x80000000
        return bytes(self.b[o:o + n])

    def wr(self, a, data):
        o = a - 0x80000000
        self.b[o:o + len(data)] = data

    def put(self, a, fmt, *v):
        self.wr(a, struct.pack(fmt, *v))


PG, PL, EM, STRIDE = 0x80300000, 0x80310000, 0x80320000, 0xDE0


def world(enemies, room=0x400, timer_s=100.0, combo=0, leon=(0.0, 0.0, 0.0)):
    m = FakeMem()
    m.put(B.P_GLOBAL, ">I", PG)
    m.put(PG + B.G_ROOM, ">H", room)
    m.put(B.P_PLAYER, ">I", PL)
    for off in (0x94, 0x1C0):                         # Leon keeps two copies of his position
        m.put(PL + off, ">3f", *leon)
    m.put(B.EMMGR, ">3I", EM, len(enemies) + 1, STRIDE)
    for k, (pos, alive) in enumerate(enemies, start=1):
        o = EM + k * STRIDE
        m.put(o, ">I", 0x601 if alive else 0)
        m.put(o + 0x94, ">3f", *pos)
    m.put(B.MERC_TIMER, ">I", int(timer_s * 30))
    m.put(B.MERC + 0x28, ">I", combo)
    return m


def test_snapshot_reads_leon_the_live_ganados_and_the_merc_state():
    m = world([((1000, 0, 0), True), ((50, 0, 50), False)], combo=4)
    s = B.snapshot(m)
    assert s["room"] == 0x400 and s["timer"] == 100.0 and s["combo"] == 4
    assert [e["slot"] for e in s["enemies"]] == [1]
    assert B.in_mercenaries(s) and not B.in_mercenaries(B.snapshot(world([], room=0x120)))


def test_faces_the_nearest_and_fires_in_range_runs_when_further():
    now = [0.0]
    m = world([((0, 0, 2000), True), ((0, 0, -4000), True)])
    bot = B.Bot(m, clock=lambda: now[0])
    act = bot.tick(B.snapshot(m))
    assert act == {"hold": {"r", "a"}}
    assert struct.unpack(">f", m.rd(PL + 0xA4, 4))[0] == pytest.approx(0.0)        # facing +z, onto the target
    m2 = world([((3000, 0, 0), True)])
    bot2 = B.Bot(m2, clock=lambda: now[0])
    assert bot2.tick(B.snapshot(m2)) == {"hold": {"up", "b"}}                       # sprint in
    assert struct.unpack(">f", m2.rd(PL + 0xA4, 4))[0] == pytest.approx(math.pi / 2)


def test_teleports_next_to_a_far_target_moving_every_position_copy():
    now = [10.0]
    m = world([((100, 500, 9000), True)], leon=(100.0, 7.0, 200.0))
    bot = B.Bot(m, clock=lambda: now[0])
    bot.tick(B.snapshot(m))
    for off in (0x94, 0x1C0):
        x, y, z = struct.unpack(">3f", m.rd(PL + off, 12))
        assert (x, y) == (100, 500) and z == pytest.approx(9000 - B.HOP_SHORT)
    assert m.rd(PL + 0x200, 12) == bytes(12)           # nothing else in Leon's struct was touched
    assert bot.stats["hops"] == 1


def test_a_stopped_clock_is_a_prompt_answered_yes():
    now = [0.0]
    m = world([((0, 0, 1000), True)])
    bot = B.Bot(m, clock=lambda: now[0])
    bot.tick(B.snapshot(m))
    now[0] = 1.5                                      # same timer value 1.5 s later
    assert bot.tick(B.snapshot(m)) == {"tap": "a"}
    now[0] = 8.0
    assert bot.tick(B.snapshot(m)) == {"tap": "b"}     # still stuck: back out


def test_a_target_that_soaks_fire_is_skipped():
    now = [0.0]
    m = world([((0, 0, 1000), True), ((0, 0, -1500), True)])
    bot = B.Bot(m, clock=lambda: now[0])
    for t in range(0, 70):
        now[0] = t * 0.1
        m.put(B.MERC_TIMER, ">I", int((100 - now[0]) * 30))
        bot.tick(B.snapshot(m))
    assert 1 in bot.skip                              # the near one never died
    now[0] = 7.1
    m.put(B.MERC_TIMER, ">I", int((100 - now[0]) * 30))
    bot.tick(B.snapshot(m))
    assert struct.unpack(">f", m.rd(PL + 0xA4, 4))[0] == pytest.approx(math.pi)     # now facing the other one


def test_play_presses_and_lets_go(monkeypatch):
    m = world([((0, 0, 1000), True)])
    sent, n = [], [0]

    def stopped():
        n[0] += 1
        return n[0] > 3
    B.play(None, sent.append, stopped, sleep=lambda s: None, m=m)
    assert sent[0] == [{"key": "a", "down": True}, {"key": "r", "down": True}]
    assert sent[-1] == [{"key": "a", "down": False}, {"key": "r", "down": False}]


def test_auto_mode_prefers_a_matching_playbook(monkeypatch, tmp_path):
    from gbox import tools, autoplay as apmod

    class D:
        def __init__(self, *a, **k):
            self.stopped, self.trace = False, []
    monkeypatch.setattr(apmod, "Driver", D)
    monkeypatch.setattr(tools.httpx, "get", lambda *a, **k: SimpleNamespace(
        json=lambda: [{"session_id": "s9", "game_id": "re4", "started": 0}]))
    ad = SimpleNamespace(name="dolphin", supported={"send_input"}, send_input=lambda rows: None)
    monkeypatch.setitem(tools.SESSIONS, "s9", (ad, {"platform": "gamecube", "title": "RE4"}))
    monkeypatch.setattr(tools, "AUTOPLAY", {})
    calls = []
    pb = SimpleNamespace(__name__="gbox.re4_merc_bot", __doc__="RE4 bot.\n", setup=lambda ad: calls.append("setup") or [],
                         play=lambda ad, send, stopped: calls.append("play") or {"hops": 0})
    monkeypatch.setattr(tools, "_playbook", lambda ad, g: pb)
    ctx = SimpleNamespace(server="http://x", headers={"authorization": "Bearer t"}, config=SimpleNamespace(runtime=tmp_path))
    r = tools.autoplay(tools.AutoplayIn(session_id="s9", op="start"), ctx)["result"]
    assert r["mode"] == "playbook" and r["started"] == "playbook: re4_merc_bot"
    tools.AUTOPLAY["s9"]["thread"].join(5)
    assert calls == ["setup", "play"] and tools.AUTOPLAY["s9"]["result"]["playbook"] == "re4_merc_bot"
    monkeypatch.setattr(tools, "_playbook", lambda ad, g: None)
    with pytest.raises(ValueError, match="no playbook"):
        tools.autoplay(tools.AutoplayIn(session_id="s9", op="start", mode="playbook"), ctx)


def test_between_rounds_it_presses_a_until_the_next_round_and_counts_it():
    m = world([((500.0, 0.0, 0.0), True)], room=0x100)              # not a Mercenaries room: results / menus
    now, sent, live = [0.0], [], {}
    steps = iter(range(60))

    def stopped():
        i = next(steps, None)
        if i == 40:
            m.put(PG + B.G_ROOM, ">H", 0x400)                         # the presses started the next round
        return i is None
    B.play(None, sent.append, stopped, sleep=lambda s: now.__setitem__(0, now[0] + s), m=m, stats=live,
           clock=lambda: now[0])
    presses = [r for r in sent if r == [{"key": "a", "down": True}]]
    assert len(presses) >= 3 and live["menu_presses"] == len(presses)
    assert live["rounds"] == 2 and "timer" in live and "max_combo" in live    # live stats for the watch panel


def test_the_result_screen_is_not_a_round():
    m = world([], room=0x400, timer_s=0.0)                          # the Result screen: Mercenaries room, clock at 0
    now, sent = [0.0], []
    steps = iter(range(30))
    B.play(None, sent.append, lambda: next(steps, None) is None, sleep=lambda s: now.__setitem__(0, now[0] + s), m=m,
           clock=lambda: now[0])
    assert [{"key": "a", "down": True}] in sent                       # pressed on: the next round
