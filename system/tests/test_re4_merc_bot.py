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


def facing(m, rot):
    m.put(PL + 0xA4, ">f", rot)


def test_turns_with_the_stick_then_aims_then_fires_never_writing_leon():
    now = [0.0]
    m = world([((0, 0, 2000), True)])                  # straight ahead along +z: heading 0
    before = m.rd(PL, 0x300)
    bot = B.Bot(m, clock=lambda: now[0], nav=False)
    facing(m, 1.5)                                     # facing far to the left of him
    assert bot.tick(B.snapshot(m)) == {"hold": {"right"}}             # turn round first, not aiming yet
    facing(m, 0.2)
    assert bot.tick(B.snapshot(m)) == {"hold": {"r", "right"}}        # close: aim and fine-turn
    facing(m, 0.02)
    assert bot.tick(B.snapshot(m)) == {"hold": {"r", "a"}}            # on him: fire
    pitch = struct.unpack(">f", m.rd(PL + B.AIM_PITCH, 4))[0]
    assert pitch == pytest.approx(math.atan2(B.HEAD_H - B.GUN_H, 2000.0), abs=1e-4)   # at his head
    facing(m, 0.0)
    assert m.rd(PL, 0x300)[:0xA4] == before[:0xA4]                    # position and the rest: never written


def test_no_enemy_near_runs_to_the_nearest_time_bonus_and_shoots_it():
    now = [0.0]
    m = world([((30000, 0, 30000), True)], room=0x400, leon=(5592.0, 0.0, 12384.0))   # 4000 short of the (5592, 16384) one
    bot = B.Bot(m, clock=lambda: now[0], nav=False)
    facing(m, 0.0)
    assert bot.tick(B.snapshot(m)) == {"hold": {"up", "b"}}           # run straight at it
    m.put(PL + 0x94, ">3f", 5592.0, 0.0, 15400.0)
    act = bot.tick(B.snapshot(m))
    assert act["hold"] >= {"r", "a"}                                   # in range: shoot the hourglass


def test_the_clock_jumping_up_is_a_time_bonus_taken():
    now = [0.0]
    m = world([], room=0x400, leon=(5592.0, 0.0, 16000.0), timer_s=60.0)
    bot = B.Bot(m, clock=lambda: now[0], nav=False)
    bot.tick(B.snapshot(m))
    now[0] = 0.5
    m.put(B.MERC_TIMER, ">I", int(150 * 30))           # +90 s: the bonus
    bot.tick(B.snapshot(m))
    assert bot.stats["time_bonus"] == 1 and (5592.0, 16384.0) not in bot.bonus and len(bot.bonus) == 3


def test_blocked_while_running_vaults_then_detours():
    now = [0.0]
    m = world([], room=0x400, leon=(100.0, 7.0, 200.0), timer_s=100.0)
    bot = B.Bot(m, clock=lambda: now[0], nav=False)
    facing(m, B.heading(5592.0 - 100.0, 16384.0 - 200.0))   # towards the nearest hourglass
    acts = []
    for t in range(1, 40):                             # Leon never moves: a fence
        now[0] = t * 0.1
        m.put(B.MERC_TIMER, ">I", int((100 - now[0]) * 30))
        acts.append(bot.tick(B.snapshot(m)))
    assert {"tap": "a"} in acts and bot.stats["vaults"] >= 1           # JUMP OVER first
    assert bot.stats["detours"] >= 1                                     # then around it
    assert bot.stats["hops"] >= 1                                        # still blocked: a short hop past it
    x, y, z = struct.unpack(">3f", m.rd(PL + 0x94, 12))
    assert math.hypot(x - 100.0, z - 200.0) == pytest.approx(B.HOP_SHORT, rel=0.01) and y == 7.0   # HOP_SHORT along
    assert B.heading(x - 100.0, z - 200.0) == pytest.approx(B.heading(5592.0 - 100.0, 16384.0 - 200.0), abs=0.01)


def test_uses_the_navmap_path_when_there_is_one():
    class Nav:
        def stage(self, room):
            return {"events": [{"kind": "hourglass", "pos": [5000.0, 0.0, 0.0]}]}

        def path(self, stage, start, goal):
            return [(0.0, 3000.0), goal]                 # round a wall: first north
    now = [0.0]
    m = world([], room=0x400, leon=(0.0, 0.0, 0.0))
    bot = B.Bot(m, clock=lambda: now[0], nav=Nav())
    facing(m, 0.0)
    assert bot.tick(B.snapshot(m)) == {"hold": {"up", "b"}}           # heading 0 = +z: the first waypoint
    assert bot.bonus == [(5000.0, 0.0)]


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
    facing(m, 0.0)                                     # on the near one
    bot = B.Bot(m, clock=lambda: now[0], nav=False)
    for t in range(0, 70):
        now[0] = t * 0.1
        m.put(B.MERC_TIMER, ">I", int((100 - now[0]) * 30))
        bot.tick(B.snapshot(m))
    assert 1 in bot.skip                              # the near one never died
    now[0] = 7.1
    m.put(B.MERC_TIMER, ">I", int((100 - now[0]) * 30))
    assert bot.tick(B.snapshot(m))["hold"] & {"left", "right"}      # turning round to the other one


def test_play_presses_and_lets_go(monkeypatch):
    m = world([((0, 0, 1000), True)])
    sent, n = [], [0]

    def stopped():
        n[0] += 1
        return n[0] > 3
    facing(m, 0.0)
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


def test_the_next_rounds_clock_is_not_a_time_bonus():
    now = [0.0]
    m = world([], room=0x400, leon=(5592.0, 0.0, 16000.0), timer_s=0.1)
    bot = B.Bot(m, clock=lambda: now[0], nav=False)
    bot.tick(B.snapshot(m))
    now[0] = 0.5
    m.put(B.MERC_TIMER, ">I", int(120 * 30))           # the next round starts at 2:00
    bot.tick(B.snapshot(m))
    assert bot.stats["time_bonus"] == 0
