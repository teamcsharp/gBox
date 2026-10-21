"""RE4 Mercenaries playbook (gbox.re4_merc_bot): RAM reading, targeting, the aim by stick, prompts, autoplay picking it."""
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
    from gbox import re4_menus
    m = FakeMem()
    for a, sig in re4_menus.SIGNATURES.items():       # main.dol's code, as RAM holds it (the menus reader checks it)
        m.wr(a, sig)
    m.put(B.P_GLOBAL, ">I", PG)
    m.put(PG + 0x20, "B", 3)                          # pG+0x20: the room runs (not a stage still loading)
    m.put(PG + B.G_ROOM, ">H", room)
    m.put(PG + B.G_HP, ">h", 1000)                    # Leon alive
    m.put(B.P_PLAYER, ">I", PL)
    for off in (0x94, 0x1C0):                         # Leon keeps two copies of his position
        m.put(PL + off, ">3f", *leon)
    m.put(B.EMMGR, ">3I", EM, len(enemies) + 1, STRIDE)
    for k, (pos, alive) in enumerate(enemies, start=1):
        o = EM + k * STRIDE
        m.put(o, ">I", 0x601 if alive else 0)
        m.put(o + 0x94, ">3f", *pos)
        m.put(o + B.EM_HP, ">hh", 1000, 1000)
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
    m = world([((0, 800, 2000), True)])                # straight ahead along +z, up on a ledge (beyond ELEV_DY)
    before = m.rd(PL, 0x300)
    bot = B.Bot(m, clock=lambda: now[0], nav=False)
    facing(m, 1.5)                                     # facing far to the left of him
    assert bot.tick(B.snapshot(m)) == {"hold": {"right"}}             # turn round first, not aiming yet
    facing(m, 0.2)
    assert bot.tick(B.snapshot(m)) == {"hold": {"r", "right"}}        # close: aim and fine-turn
    facing(m, 0.02)
    assert bot.tick(B.snapshot(m)) == {"hold": {"r"}}                 # on him, the aim pose coming up: not yet
    head = math.atan2(800 + B.HEAD_H - B.GUN_H, 2000.0)              # his head up there: 0.44 rad above the gun
    now[0] = 0.3
    m.put(B.MERC_TIMER, ">I", int((100 - 0.3) * 30))
    assert bot.tick(B.snapshot(m)) == {"hold": {"r", "up"}}          # pose up, the aim level: raise it with the stick
    now[0] = 0.35
    m.put(PL + B.AIM_PITCH, ">f", head - 0.01)                         # the game raised it
    assert bot.tick(B.snapshot(m)) == {"hold": {"r", "a"}}            # at his head: fire

    def mine(b):                                                       # all but what this test itself moved
        return b[:0xA4] + b[0xA8:B.AIM_PITCH] + b[B.AIM_PITCH + 4:]
    assert mine(m.rd(PL, 0x300)) == mine(before)                        # Leon: never written by the bot


def test_no_enemy_near_runs_to_the_nearest_time_bonus_and_shoots_it():
    now = [0.0]
    m = world([((30000, 0, 30000), True)], room=0x400, leon=(5592.0, 0.0, 12384.0))   # 4000 short of the (5592, 16384) one
    bot = B.Bot(m, clock=lambda: now[0], nav=False)
    facing(m, 0.0)
    assert bot.tick(B.snapshot(m)) == {"hold": {"up", "b"}}           # run straight at it
    m.put(PL + 0x94, ">3f", 5592.0, 0.0, 15400.0)
    act = bot.tick(B.snapshot(m))
    assert act["hold"] >= {"r", "a"}                                   # in range: shoot the hourglass
    m.put(PL + 0xA4, ">f", 0.0)


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
    for t in range(1, 60):                             # Leon never moves: a fence
        now[0] = t * 0.1
        m.put(B.MERC_TIMER, ">I", int((100 - now[0]) * 30))
        acts.append(bot.tick(B.snapshot(m)))
    assert {"tap": "a"} in acts and bot.stats["vaults"] >= 1           # JUMP OVER first
    assert bot.stats["detours"] >= 1                                     # then around it
    assert bot.stats["backoffs"] >= 1 and {"hold": {"down"}} in acts    # still blocked: back off, then the other side
    assert struct.unpack(">3f", m.rd(PL + 0x94, 12)) == (100.0, 7.0, 200.0)   # never moved by a write: no teleports


def test_a_climb_is_not_blocked():
    now = [0.0]
    m = world([], room=0x400, leon=(100.0, 0.0, 200.0), timer_s=100.0)
    bot = B.Bot(m, clock=lambda: now[0], nav=False)
    facing(m, B.heading(5592.0 - 100.0, 16384.0 - 200.0))
    for t in range(1, 40):                             # up a ladder: along nothing, up 400 a second
        now[0] = t * 0.1
        m.put(B.MERC_TIMER, ">I", int((100 - now[0]) * 30))
        m.put(PL + 0x94, ">3f", 100.0, 40.0 * t, 200.0)
        bot.tick(B.snapshot(m))
    assert bot.stats["vaults"] == bot.stats["detours"] == bot.stats["backoffs"] == 0


class FakeNav:
    """gbox.re4_navmap's API: stage() with hourglasses, path() -> Waypoints, tour() -> order, sight()."""

    def __init__(self, items, sight=True, path=None):
        self.items, self.see, self.way = items, sight, path

    def stage(self, room):
        return {"hourglasses": self.items}

    def path(self, st, start, goal):
        from gbox.re4_navmap import Waypoint
        gx, gy, gz = goal if len(goal) == 3 else (goal[0], 0.0, goal[1])
        return [Waypoint(*w) for w in (self.way or [])] + [Waypoint(gx, gy, gz, None)]

    def tour(self, st, start, targets=None):
        return list(reversed(range(len(targets))))                  # the planner's order (here: reversed)

    def sight(self, st, a, b):
        return self.see


def item(kind, x, z):
    return {"kind": kind, "reachable": True, "pos": [x, 0.0, z], "stand": [x, 0.0, z - 300.0], "seconds": 90}


def test_with_the_map_takes_the_time_bonuses_in_the_planned_order_with_a():
    now = [0.0]
    m = world([], room=0x400, leon=(0.0, 0.0, 0.0))
    first, second = item("time_bonus", 0.0, 5000.0), item("time_bonus", 0.0, -5000.0)
    bot = B.Bot(m, clock=lambda: now[0], nav=FakeNav([first, second]))
    facing(m, math.pi)                                                    # facing -z: the planner's first pick
    assert bot.tick(B.snapshot(m)) == {"hold": {"up", "b"}}               # run (tour reversed the list: -z first)
    assert bot.items[0] is second
    m.put(PL + 0x94, ">3f", 0.0, 0.0, -5200.0)                            # at its stand point (-5300)
    assert bot.tick(B.snapshot(m)) == {"tap": "a"}                        # TAKE


def test_a_vault_waypoint_is_jumped_with_a():
    now = [0.0]
    m = world([], room=0x400, leon=(0.0, 0.0, 0.0))
    bonus = item("time_bonus", 0.0, 9000.0)
    bot = B.Bot(m, clock=lambda: now[0], nav=FakeNav([bonus], path=[(0.0, 0.0, 600.0, "vault")]))
    facing(m, 0.0)
    assert bot.tick(B.snapshot(m)) == {"tap": "a"}                        # the fence 600 ahead: JUMP OVER
    assert bot.stats["vaults"] == 1


def test_no_line_of_sight_means_move_not_shoot():
    now = [0.0]
    m = world([((0, 0, 1500), True)], room=0x400)
    bot = B.Bot(m, clock=lambda: now[0], nav=FakeNav([], sight=False))
    facing(m, 0.0)
    assert bot.tick(B.snapshot(m)) == {"hold": {"up", "b"}}               # behind a wall: go round to him


def test_a_crowd_sends_him_for_a_combo_bonus_first():
    now = [0.0]
    ganados = [((800.0 * k, 0, 2500), True) for k in range(-2, 3)]       # five close by
    m = world(ganados, room=0x400)
    combo = item("combo_bonus", 0.0, 3000.0)
    bot = B.Bot(m, clock=lambda: now[0], nav=FakeNav([combo]))
    facing(m, 0.0)
    act = bot.tick(B.snapshot(m))
    assert act == {"hold": {"up", "b"}} and bot.goal["item"] is combo     # every kill in its 30 s scores more


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
    clock = iter([0.0, 0.0, 0.0, 0.1, 0.1, 0.2, 0.4, 0.4, 0.5, 0.6, 0.7, 0.8] + [0.9] * 50)
    B.play(None, sent.append, stopped, sleep=lambda s: None, m=m, clock=lambda: next(clock))
    assert sent[0] == [{"key": "r", "down": True}]                     # aim first: the pose comes up
    assert {"key": "r", "down": False} in sent[-1] and not any(r["down"] for r in sent[-1])   # all let go at the end


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


def test_between_rounds_it_never_presses_blind_and_counts_the_next_round():
    # out of a round on a screen RAM does not name as a menu (no title task; the stage still loading, with the last
    # round's clock showing): no press at all. Blind up + A had walked to the main title and started a story game with
    # the hooks in (2026-10-20); the menus from RAM are tests/test_re4_menus.py
    m = world([((500.0, 0.0, 0.0), True)], room=0x400, timer_s=9.8)
    m.put(PG + 0x20, "B", 2)                                           # pG+0x20 2: the Village still loading
    now, sent, live, step = [0.0], [], {}, [0]
    steps = iter(range(60))

    def stopped():
        i = step[0] = next(steps, None)
        if i == 40:
            m.put(PG + 0x20, "B", 3)                                   # the room runs: the next round started
            m.put(B.MERC_TIMER, ">I", 120 * 30)
        return i is None
    B.play(None, lambda rows: sent.append((step[0], rows)), stopped, sleep=lambda s: now.__setitem__(0, now[0] + s),
           m=m, stats=live, clock=lambda: now[0])
    assert not [rows for i, rows in sent if i is not None and i < 40]     # nothing pressed out of the round
    assert live["menu_presses"] == 0 and live["screen"] == "loading"
    assert live["rounds"] == 1 and "timer" in live and "max_combo" in live    # live stats for the watch panel


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


def test_shoots_only_what_he_can_hit():
    now = [0.0]
    far = world([((0, 0, 3000), True)])                                    # inside ENGAGE, beyond SHOOT_RANGE
    facing(far, 0.0)
    assert B.Bot(far, clock=lambda: now[0], nav=False).tick(B.snapshot(far)) == {"hold": {"up", "b"}}   # close in
    close = world([((0, 0, 400), True)])                                   # point blank
    facing(close, 0.0)
    assert B.Bot(close, clock=lambda: now[0], nav=False).tick(B.snapshot(close)) == {"hold": {"r"}}     # aims: no back-off
    roof = world([((0, 0, 1500), True)], leon=(0.0, 2600.0, 0.0))          # Leon up on the start roof
    facing(roof, 0.0)
    assert B.Bot(roof, clock=lambda: now[0], nav=False).tick(B.snapshot(roof)) == {"hold": {"up", "b"}}  # down to them


def test_the_learned_map_routes_round_a_wall_it_ran_into(tmp_path):
    lm = B.LearnedMap(tmp_path / "r400.json")
    for i in range(-3, 4):                                                 # a wall across z = 1200, x -1200..1600
        lm.block(i * B.CELL + 10, 1210.0)
    for i in range(-5, 6):
        for j in range(-2, 8):
            if j != 3:
                lm.walk(i * B.CELL + 10, j * B.CELL + 10)
    way = lm.path((10.0, 10.0), (10.0, 2410.0))
    assert len(way) > 1 and way[-1] == (10.0, 2410.0)
    assert all(not lm.wall(lm.cell(x, z)) for x, z in way)
    assert any(abs(x) >= 1400 for x, _ in way)                           # round the end of the wall
    lm.save()
    again = B.LearnedMap(tmp_path / "r400.json")                           # the next round starts with it
    assert again.blocked == lm.blocked and again.walked == lm.walked


def test_running_into_something_teaches_the_map(tmp_path):
    now = [0.0]
    m = world([], room=0x400, leon=(100.0, 7.0, 200.0), timer_s=100.0)
    bot = B.Bot(m, clock=lambda: now[0], nav=False, learn_dir=tmp_path)
    facing(m, B.heading(5592.0 - 100.0, 16384.0 - 200.0))
    for t in range(1, 15):
        now[0] = t * 0.1
        m.put(B.MERC_TIMER, ">I", int((100 - now[0]) * 30))
        bot.tick(B.snapshot(m))
    assert bot.stats["learned_walls"] >= 1 and bot.stats["replans"] >= 1
    bot.save()
    assert (tmp_path / "r400.json").is_file()


def test_between_rounds_a_rerun_hook_replaces_the_blind_presses():
    m = world([], room=0x400, timer_s=0.0)                                # the Result screen
    now, sent, calls = [0.0], [], []
    steps = iter(range(40))

    def rerun():
        calls.append(now[0])
        m.put(B.MERC_TIMER, ">I", int(120 * 30))                         # the next round is on
    B.play(None, lambda rows: sent.append((now[0], rows)), lambda: next(steps, None) is None,
           sleep=lambda s: now.__setitem__(0, now[0] + s), m=m, clock=lambda: now[0], rerun=rerun)
    assert len(calls) == 1                                                # one rerun
    assert not [t for t, rows in sent if t <= calls[0] and {"key": "a", "down": True} in rows]   # no blind A before it


def test_a_grab_mid_round_is_not_the_end_of_the_round():
    m = world([], room=0x400, timer_s=21.8)
    m.put(B.P_PLAYER, ">I", 0)                                              # Leon's pointer gone for a moment (grabbed)
    now, calls = [0.0], []
    steps = iter(range(40))                                                # ~10 s of fake time
    B.play(None, lambda rows: None, lambda: next(steps, None) is None, sleep=lambda s: now.__setitem__(0, now[0] + s),
           m=m, clock=lambda: now[0], rerun=lambda: calls.append(now[0]))
    assert calls == []                                                     # no rerun: the round goes on


def hp(m, slot, value):
    m.put(EM + slot * STRIDE + B.EM_HP, ">h", value)


def test_his_health_scores_the_shots_and_misses_move_the_aim_height():
    now = [0.0]
    m = world([((0, 800, 2000), True)])
    facing(m, 0.0)
    bot = B.Bot(m, clock=lambda: now[0], nav=False)

    def tick(t):
        now[0] = t
        m.put(B.MERC_TIMER, ">I", int((100 - t) * 30))
        act = bot.tick(B.snapshot(m))
        keys = act.get("hold", set())
        pitch = struct.unpack(">f", m.rd(PL + B.AIM_PITCH, 4))[0]               # the game, under the stick
        m.put(PL + B.AIM_PITCH, ">f", pitch + 0.06 * (("up" in keys) - ("down" in keys)))   # a quick stick
        return act
    t = 0.0
    while "a" not in tick(t).get("hold", set()):                           # raise the aim to his head, then fire
        t += 0.05
        assert t < 3
    hp(m, 1, 800)
    tick(t + 0.2)
    assert bot.stats["hits"] == 1                                          # his health fell: a hit
    for k in range(1, 55):                                                 # then nothing lands for a while
        tick(t + 0.2 + k * 0.1)
    assert bot.stats["misses"] >= 3 and bot.stats["pitch_offset"] != 0.0  # the aim height moves on
    assert 0 < bot.stats["accuracy"] < 1


def test_an_inverted_aim_stick_is_learned():
    now = [0.0]
    m = world([((0, 800, 2000), True)])
    facing(m, 0.0)
    bot = B.Bot(m, clock=lambda: now[0], nav=False)
    head = math.atan2(800 + B.HEAD_H - B.GUN_H, 2000.0)
    fired = False
    for k in range(80):                                                    # this game: up LOWERS the aim
        now[0] = k * 0.05
        m.put(B.MERC_TIMER, ">I", int((100 - now[0]) * 30))
        keys = bot.tick(B.snapshot(m)).get("hold", set())
        fired = fired or "a" in keys
        pitch = struct.unpack(">f", m.rd(PL + B.AIM_PITCH, 4))[0]
        m.put(PL + B.AIM_PITCH, ">f", pitch + 0.02 * (("down" in keys) - ("up" in keys)))
    assert bot.pitch_up == "down" and fired
    assert abs(struct.unpack(">f", m.rd(PL + B.AIM_PITCH, 4))[0] - head) <= B.PITCH_TOL + 0.02


def test_the_hand_cannon_keeps_its_own_fire_rate():
    wm = dict(B.PACKAGE)["weapon_mod"]
    assert "fire_rate" not in wm and wm.get("reset") is True              # full auto bent Leon's arm over his head


def test_an_on_screen_prompt_is_pressed_and_a_stuck_one_is_left_alone():
    m = world([], room=0x400)                                              # no Ganados: every A is a prompt press
    facing(m, 0.0)
    now, sent = [0.0], []
    steps = iter(range(60))
    shown = {"on": True}

    def tick_stop():
        n = next(steps, None)
        m.put(B.MERC_TIMER, ">I", int((100 - now[0]) * 30))
        for off in (0x94, 0x1C0):                                          # Leon runs freely: no stuck vault taps
            m.put(PL + off, ">3f", 0.0, 0.0, 300.0 * (n or 0))
        return n is None
    B.play(None, lambda rows: sent.append((now[0], rows)), tick_stop, sleep=lambda s: now.__setitem__(0, now[0] + s),
           m=m, clock=lambda: now[0], prompt=lambda: "a" if shown["on"] else None)
    taps = [t for t, rows in sent if rows == [{"key": "a", "down": True}]]
    assert len(taps) >= 3                                                  # pressed while it showed
    assert all(b - a >= B.PROMPT_EVERY - 1e-6 for a, b in zip(taps, taps[1:]))
    early = [t for t in taps if t < 3.0]
    assert len(early) == B.PROMPT_BURST                                    # then left alone for PROMPT_REST


def test_the_prompt_detector_finds_the_a_icon():
    import numpy as np
    from gbox import screen_prompt as P
    img = np.zeros((480, 640, 3), np.uint8)
    img[:, :] = (90, 80, 60)                                               # brown dirt
    yy, xx = np.ogrid[:480, :640]
    disc = (yy - 386) ** 2 + (xx - 259) ** 2 <= 10 ** 2
    img[disc] = (40, 134, 104)                                             # RE4's A icon, where the game draws it
    found = P.detect(img)
    assert found and found["button"] == "a" and 240 < found["box"][0] < 260
    img2 = img.copy()
    img2[disc] = (90, 80, 60)
    img2[440:470, 500:600] = (40, 134, 104)                                # the ammo dial's green: outside the box
    assert P.detect(img2) is None


def test_autoplay_gives_a_playbook_that_takes_prompts_a_screen_watcher(monkeypatch):
    import io
    import threading
    import numpy as np
    from PIL import Image
    from gbox import tools, autoplay as apmod

    class D:
        def __init__(self, *a, **k):
            self.stopped, self.trace = False, []
    monkeypatch.setattr(apmod, "Driver", D)
    monkeypatch.setattr(tools.httpx, "get", lambda *a, **k: SimpleNamespace(json=lambda: []))
    monkeypatch.setattr(tools.httpx, "post", lambda *a, **k: SimpleNamespace(status_code=200, json=lambda: {}, text=""))
    img = np.zeros((480, 640, 3), np.uint8)
    yy, xx = np.ogrid[:480, :640]
    img[(yy - 386) ** 2 + (xx - 259) ** 2 <= 100] = (40, 134, 104)       # RE4's A prompt on screen
    buf = io.BytesIO()
    Image.fromarray(img).save(buf, "PNG")
    ad = SimpleNamespace(name="dolphin", supported={"send_input"}, send_input=lambda rows: None,
                         get_frame=lambda: buf.getvalue())
    monkeypatch.setitem(tools.SESSIONS, "s9", (ad, {"platform": "gamecube", "title": "RE4"}))
    monkeypatch.setattr(tools, "AUTOPLAY", {})
    seen, done = [], threading.Event()

    def play(ad, send, stopped, prompt=None):
        for _ in range(40):
            if prompt():
                seen.append(prompt())
                break
            import time as _t
            _t.sleep(0.05)
        done.set()
        return {}
    pb = SimpleNamespace(__name__="gbox.re4_merc_bot", __doc__="RE4 bot.", setup=lambda ad: [], play=play)
    inp = tools.AutoplayIn(session_id="s9", op="start", mode="playbook")
    tools._start_playbook(pb, inp, D(), ad, 0.0)
    assert done.wait(5) and seen == ["a"]                                 # the playbook saw the A prompt


def test_a_tripled_time_bonus_still_counts():
    now = [0.0]
    m = world([], room=0x400, leon=(5592.0, 0.0, 16000.0), timer_s=100.0)
    bot = B.Bot(m, clock=lambda: now[0], nav=False)
    bot.tick(B.snapshot(m))
    now[0] = 0.5
    m.put(B.MERC_TIMER, ">I", int(370 * 30))          # +270 s: a 90 s pickup with the time bonus x3 hack
    bot.tick(B.snapshot(m))
    assert bot.stats["time_bonus"] == 1


def test_you_are_dead_is_answered_yes_and_counted_once():
    now = [0.0]
    m = world([], room=0x400, timer_s=60.0)
    m.put(PG + B.G_HP, ">h", 1200)
    bot = B.Bot(m, clock=lambda: now[0], nav=False)
    bot.tick(B.snapshot(m))
    m.put(PG + B.G_HP, ">h", 0)                       # dead: the clock stops on "Continue Yes / No"
    taps = []
    for k in range(1, 120):                           # a minute on that screen
        now[0] = k * 0.5
        taps.append(bot.tick(B.snapshot(m)).get("tap"))
    assert set(t for t in taps if t) == {"a"} and bot.stats["deaths"] == 1   # Yes, never B


def test_a_session_reads_its_own_dolphin_only(monkeypatch):
    from gbox import ram_dump
    seen = {}

    class Ram:                                        # ShmRam of the session's own Dolphin
        def read(self, address, n):
            seen["at"] = address
            return bytes(n)
    monkeypatch.setattr(ram_dump.ShmRam, "find", classmethod(lambda cls, ad: Ram() if ad.proc.pid == 41 else None))
    monkeypatch.setattr(B, "ShmMem", lambda *a, **k: pytest.fail("scanned every Dolphin on the host"))
    mine = B.memory(SimpleNamespace(name="dolphin", proc=SimpleNamespace(pid=41)))
    mine.rd(B.EMMGR, 4)
    assert isinstance(mine, B.OwnShm) and seen["at"] == B.EMMGR      # its own process, the GameCube address
    other = B.memory(SimpleNamespace(name="dolphin", proc=SimpleNamespace(pid=7), read_memory=lambda a, n: bytes(n)))
    assert isinstance(other, B.AdMem)                 # no shared view of its own: the adapter's reads, never a scan


def test_a_level_target_is_shot_as_soon_as_the_aim_is_up():
    now = [0.0]
    m = world([((0, 0, 2000), True)])
    facing(m, 0.0)
    bot = B.Bot(m, clock=lambda: now[0], nav=False)
    assert bot.tick(B.snapshot(m)) == {"hold": {"r"}}               # the aim pose coming up
    now[0] = B.PITCH_AFTER + 0.01
    assert bot.tick(B.snapshot(m)) == {"hold": {"r", "a"}}       # same level: fire, no aim-height push


def test_a_ganado_about_to_strike_comes_before_a_combo_bonus():
    now = [0.0]
    crowd = [((800.0 * k, 0, 3000), True) for k in range(-2, 3)] + [((0, 0, 900), True)]   # five out there, one close
    m = world(crowd, room=0x400)
    bot = B.Bot(m, clock=lambda: now[0], nav=FakeNav([item("combo_bonus", 0.0, -3000.0)]))
    facing(m, 0.0)
    act = bot.tick(B.snapshot(m))
    assert "r" in act.get("hold", set()) and not (bot.goal or {}).get("item")   # aiming at him, not running off
