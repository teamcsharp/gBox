"""RE4 Mercenaries playbook (gbox.re4_merc_bot): RAM reading, targeting, the aim by stick, prompts, autoplay picking it."""
import math
import struct
from types import SimpleNamespace

import pytest
import time

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


def test_snapshot_player_health_is_not_overwritten_by_last_enemy():
    m=world([((1000,0,0),True)])
    m.put(PG+B.G_HP,'>h',73)
    m.put(EM+STRIDE+B.EM_HP,'>hh',0,1500)
    snap=B.snapshot(m)
    assert snap['hp']==73 and snap['enemies'][0]['hp']==0


def test_snapshot_reads_expanded_native_enemy_table():
    m = world([((1000, 0, 0), True)] * 149)
    snap = B.snapshot(m)
    assert len(snap['enemies']) == 149
    assert snap['enemies'][-1]['slot'] == 149


def test_snapshot_rejects_enemy_table_outside_mem1():
    m = world([])
    m.put(B.EMMGR, '>3I', 0x817FFF00, 150, STRIDE)
    assert B.snapshot(m)['enemies'] == []


def facing(m, rot):
    m.put(PL + 0xA4, ">f", rot)


def set_pitch(m, rad):
    m.put(B.AIM_PITCH, ">f", rad / B.PITCH_SCALE)                       # the game's aim blend (-1 .. 1)


def get_pitch(m):
    return struct.unpack(">f", m.rd(B.AIM_PITCH, 4))[0] * B.PITCH_SCALE


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
    set_pitch(m, head - 0.01)                         # the game raised it
    assert bot.tick(B.snapshot(m)) == {"hold": {"r", "a"}}            # at his head: fire

    def mine(b):                                                       # all but what this test itself moved
        return b[:0xA4] + b[0xA8:]
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
    assert bot.tick(B.snapshot(m)) != {"tap": "a"}                        # facing away from it (-z): turn first
    facing(m, 0.0)                                                        # the item is 200 ahead (+z)
    assert bot.tick(B.snapshot(m)) == {"tap": "a"}                        # facing it, against it: TAKE


def test_a_missed_take_is_tried_again_once():
    now = [0.0]
    m = world([], room=0x400, leon=(0.0, 0.0, 5000.0))
    h = item("time_bonus", 0.0, 5000.0)
    bot = B.Bot(m, clock=lambda: now[0], nav=FakeNav([h]))
    facing(m, math.pi)
    bot.items = [h]
    for _ in range(2):
        bot.goal = None
        bot._take(B.snapshot(m)["player"], h, now[0], bot.items)
        now[0] += B.COLLECT_TRY_S + 1
        bot._take(B.snapshot(m)["player"], h, now[0], bot.items)
        if _ == 0:
            assert bot.items == [h]                                       # back in the pool for one more try
    assert h not in bot.items and h["tries"] == B.TAKE_TRIES


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


def test_raycast_fan_marks_walls_and_reports_stats(tmp_path):
    """The lookahead fan casts rays ahead every tick, marks hit cells into the learned map,
    and reports rays_cast / ray_hits in stats (request #3299)."""
    now = [0.0]
    m = world([], room=0x400, leon=(0.0, 0.0, 0.0), timer_s=100.0)
    bot = B.Bot(m, clock=lambda: now[0], nav=False, learn_dir=tmp_path)
    facing(m, 0.0)
    bot._round(0x400)                          # sets up self.learned and self.room
    # Manually set up a stage with a wall directly ahead (+z)
    bot.st = {"walls": [[-500.0, 800.0, 500.0, 800.0, 0.0, 2000.0, 0.0]]}
    bot._raycast_fan({"pos": [0.0, 0.0, 0.0], "rot": 0.0, "aim_rot": 0.0}, now[0])
    assert bot.stats["rays_cast"] == B.RAY_FAN_N
    assert bot.stats["ray_hits"] >= 1
    # The hit cell should be marked in the learned map
    assert len(bot.learned.blocked) >= 1


def test_raycast_fan_is_safe_without_stage_or_learned_map():
    """Without a stage or learned map the fan is a no-op."""
    now = [0.0]
    m = world([], room=0x400, leon=(0.0, 0.0, 0.0), timer_s=100.0)
    bot = B.Bot(m, clock=lambda: now[0], nav=False)
    bot.st = None
    bot.learned = None
    bot._raycast_fan({"pos": [0.0, 0.0, 0.0], "rot": 0.0, "aim_rot": 0.0}, now[0])
    assert bot.stats["rays_cast"] == 0


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
    act = bot.tick(B.snapshot(m))["hold"]
    assert act & {"left", "right"} or act >= {"down", "b"}           # turning round to the other one (stick / quick turn)


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


def test_autoplay_ops_never_wait_on_the_full_session_list(monkeypatch, tmp_path):
    """The full GET /api/sessions took minutes on a loaded Spark (2026-10-21) and every autoplay op timed out: start takes
    the game from the worker's own SESSIONS, stop and status ask nothing, and only the running sessions are ever listed
    (a timeout there is no game rather than a failed op)."""
    from gbox import tools, autoplay as apmod

    class D:
        def __init__(self, *a, **k):
            self.stopped, self.trace = False, []
    monkeypatch.setattr(apmod, "Driver", D)
    asked = []

    def get(url, **k):
        asked.append(k.get("params"))
        raise tools.httpx.ReadTimeout("timed out")
    monkeypatch.setattr(tools.httpx, "get", get)
    ad = SimpleNamespace(name="rpcs3", supported={"send_input"}, send_input=lambda rows: None)
    monkeypatch.setitem(tools.SESSIONS, "s5", (ad, {"game_id": "re5", "platform": "ps3", "title": "RE5"}))
    monkeypatch.setattr(tools, "AUTOPLAY", {})
    pb = SimpleNamespace(__name__="gbox.mercs_bot", __doc__="Mercs.\n", setup=lambda ad: [], play=lambda *a: {})
    monkeypatch.setattr(tools, "_playbook", lambda ad, g: pb)
    games = []
    monkeypatch.setattr(tools, "_start_playbook",
                        lambda pb, inp, d, ad, since, ctx, g, game_id: games.append(game_id) or {"started": "playbook"})
    ctx = SimpleNamespace(server="http://x", headers={"authorization": "Bearer t"}, config=SimpleNamespace(runtime=tmp_path))
    assert tools.autoplay(tools.AutoplayIn(session_id="s5", op="start"), ctx)["result"]["started"] == "playbook"
    assert tools.autoplay(tools.AutoplayIn(session_id="s5", op="status"), ctx)["result"]["running"] is False
    assert tools.autoplay(tools.AutoplayIn(session_id="s5", op="stop"), ctx)["result"]["stopped"] is False
    assert games == ["re5"] and asked == []
    assert tools._session_game_id(ctx, "elsewhere") is None and asked == [{"include_ended": "false"}]


def test_between_rounds_it_never_presses_blind_and_counts_the_next_round():
    # out of a round on a screen RAM does not name as a menu (no title task; the stage still loading, with the last
    # round's clock showing): no press at all. Blind up + A had walked to the main title and started a story game with
    # the hooks in (2026-10-20); the menus from RAM are tests/test_re4_menus.py
    m = world([((500.0, 0.0, 0.0), True)], room=0x400, timer_s=9.8)
    m.put(PG + 0x20, "B", 2)                                           # pG+0x20 2: the Village still loading
    now, sent, live, step, screens = [0.0], [], {}, [0], {}
    steps = iter(range(60))

    def stopped():
        i = step[0] = next(steps, None)
        screens[i] = live.get("screen")
        if i == 40:
            m.put(PG + 0x20, "B", 3)                                   # the room runs: the next round started
            m.put(B.MERC_TIMER, ">I", 120 * 30)
        return i is None
    B.play(None, lambda rows: sent.append((step[0], rows)), stopped, sleep=lambda s: now.__setitem__(0, now[0] + s),
           m=m, stats=live, clock=lambda: now[0])
    assert not [rows for i, rows in sent if i is not None and i < 40]     # nothing pressed out of the round
    assert live["menu_presses"] == 0 and screens[39] == "loading" and live["screen"] == "playing"
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
    act = B.Bot(far, clock=lambda: now[0], nav=False).tick(B.snapshot(far))
    assert {"r", "a"}.isdisjoint(act["hold"]) and {"up", "b"} <= act["hold"]   # out of range, bonuses left: runs, no shot
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
        pitch = get_pitch(m)               # the game, under the stick
        set_pitch(m, pitch + 0.06 * (("up" in keys) - ("down" in keys)))   # a quick stick
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
        pitch = get_pitch(m)
        set_pitch(m, pitch + 0.02 * (("down" in keys) - ("up" in keys)))
    assert bot.pitch_up == "down" and fired
    lo = math.atan2(800 + B.HEAD_LO - B.GUN_H, 2000.0)                    # the aim ends inside his head band (any pitch
    hi = math.atan2(800 + B.BODY_HI - B.GUN_H, 2000.0)                    # there lands), on its way to the head
    assert lo <= get_pitch(m) <= hi and head > lo


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


def test_a_grab_is_shaken_off_without_pause_or_rest():
    """SHAKE OFF (RAM "wiggle"): Leon loses 10 hp a frame until enough new stick flicks and A / B presses come (live
    2026-10-21), so the flicks go out back to back for as long as it shows - no PROMPT_EVERY gap, no PROMPT_REST."""
    m = world([((0, 0, 500), True)], room=0x400)
    facing(m, 0.0)
    now, sent = [0.0], []
    steps = iter(range(40))

    def tick_stop():
        n = next(steps, None)
        m.put(B.MERC_TIMER, ">I", int((100 - now[0]) * 30))
        return n is None
    B.play(None, lambda rows: sent.append((now[0], rows)), tick_stop, sleep=lambda s: now.__setitem__(0, now[0] + s),
           m=m, clock=lambda: now[0], ram_prompt=lambda: "wiggle")
    flicks = [t for t, rows in sent if {"key": "left", "down": True} in rows]
    assert len(flicks) >= 40 * 3 - 5                                       # every pass: three left flicks (and rights)
    assert max(b - a for a, b in zip(flicks, flicks[1:])) < 0.25            # never a rest
    assert all({"key": "a", "down": True} in rows for t, rows in sent if {"key": "left", "down": True} in rows)


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


# -- combat: threats from RAM (gbox.re4_threats) ------------------------------------------------------------------------
def act_state(m, slot, r, ev=0):
    m.put(EM + slot * STRIDE + 0xFC, ">4B", *r)
    m.put(EM + slot * STRIDE + 0x288, ">I", ev)


def run(bot, m, now, t, n=1):
    acts = []
    for _ in range(n):
        now[0] = t
        m.put(B.MERC_TIMER, ">I", int((100 - t) * 30))
        acts.append(bot.tick(B.snapshot(m)))
        t += 0.05
    return acts


def test_an_attacking_ganado_is_shot_before_a_nearer_one_that_only_walks():
    now = [0.0]
    m = world([((0, 0, 900), True), ((-1300, 0, 1300), True)])             # the near one walks; the other swings
    act_state(m, 1, (1, 0x03, 0, 0))
    act_state(m, 2, (1, 0x27, 1, 0))
    facing(m, B.heading(-1300, 1300))                                        # already facing the attacker
    bot = B.Bot(m, clock=lambda: now[0], nav=False)
    run(bot, m, now, 0.0)
    acts = run(bot, m, now, B.PITCH_AFTER + 0.05, 2)
    assert any("a" in a.get("hold", set()) for a in acts) and bot.target_slot == 2


def test_a_swing_that_lands_before_he_can_shoot_is_run_out_of():
    now = [0.0]
    m = world([((0, 0, -700), True)])                                        # right behind him
    act_state(m, 1, (1, 0x26, 1, 0), ev=B.threats_ram.EV_SWING)
    facing(m, 0.0)
    bot = B.Bot(m, clock=lambda: now[0], nav=False)
    bot.tracker.update(B.snapshot(m), -0.6)                                  # the swing started 0.6 s ago
    act = run(bot, m, now, 0.0)[0]
    assert act["hold"] >= {"up", "b"} and bot.stats["evades"] == 1          # away from it at a run, not turning to aim


def test_the_trigger_is_pressed_once_per_shot_not_held():
    now = [0.0]
    m = world([((0, 0, 1500), True)])
    facing(m, 0.0)
    bot = B.Bot(m, clock=lambda: now[0], nav=False)
    acts = run(bot, m, now, 0.0, 60)                                         # 3 s on target
    downs = [i for i, (a, b) in enumerate(zip(acts, acts[1:]))
             if "a" not in a.get("hold", set()) and "a" in b.get("hold", set())]
    assert len(downs) >= 5                                                   # pressed again and again, never just held
    assert bot.stats["shots"] == 3                                           # the gun fires at its own rate (35 frames)


def test_dying_ganados_are_not_shot_at():
    now = [0.0]
    m = world([((0, 0, 900), True), ((0, 0, -1400), True)])
    act_state(m, 1, (3, 1, 0, 0))                                            # dying in front of him
    hp(m, 1, 0)
    facing(m, 0.0)
    bot = B.Bot(m, clock=lambda: now[0], nav=False)
    act = run(bot, m, now, 0.0)[0]
    assert act["hold"] & {"left", "right"} or act["hold"] == {"down", "b"}   # turning to the live one behind him


def test_held_by_a_ganado_the_bot_lets_the_game_and_the_prompts_have_him():
    now = [0.0]
    m = world([((0, 0, 300), True)])
    act_state(m, 1, (1, 0x2E, 1, 0))
    m.put(PL + 0xFC, ">4B", 1, 0, 1, 0)                                      # Leon held (SHAKE OFF)
    facing(m, 0.0)
    bot = B.Bot(m, clock=lambda: now[0], nav=False)
    assert run(bot, m, now, 0.0)[0] == {"hold": set()} and bot.stats["hits_taken"] == 1


def test_an_attacker_in_front_is_shot_even_when_it_is_close_to_landing():
    now = [0.0]
    m = world([((0, 0, 1000), True)])                                        # right in front, mid-swing
    act_state(m, 1, (1, 0x26, 1, 0))
    facing(m, 0.0)
    bot = B.Bot(m, clock=lambda: now[0], nav=False)
    bot.tracker.update(B.snapshot(m), -0.5)                                  # 0.5 s into it: lands in ~0.2 s
    act = run(bot, m, now, 0.0)[0]
    assert "r" in act["hold"] and bot.stats["evades"] == 0                   # aim and fire, not a quick turn away


def test_a_kick_prompt_waits_while_another_attack_lands():
    now = [0.0]
    m = world([((0, 0, -800), True)])                                        # one behind him, mid-swing
    act_state(m, 1, (1, 0x26, 1, 0))
    facing(m, 0.0)
    bot = B.Bot(m, clock=lambda: now[0], nav=False)
    bot.tracker.update(B.snapshot(m), -0.4)
    run(bot, m, now, 0.0)
    assert not bot.prompt_ok("a", B.snapshot(m)) and bot.prompt_ok("wiggle", B.snapshot(m))


def test_a_take_prompt_for_dropped_ammo_is_ignored_but_an_hourglass_goal_takes_it():
    # operator 2026-10-24: "dont have the bot pick up ammo in any mode, he has infinite ammo ... Just fight"
    now = [0.0]
    m = world([])
    bot = B.Bot(m, clock=lambda: now[0], nav=False)
    bot.stats["ram_action"] = "TAKE"
    assert not bot.prompt_ok("a", B.snapshot(m)) and bot.stats["pickups_skipped"] == 1
    bot.goal = {"item": {"pos": (0, 0, 100)}}                               # walking to a time-bonus hourglass
    assert bot.prompt_ok("a", B.snapshot(m))
    bot.goal, bot.stats["ram_action"] = None, "KICK"
    assert bot.prompt_ok("a", B.snapshot(m))


def test_a_ganado_behind_him_gets_the_quick_turn():
    now = [0.0]
    m = world([((0, 0, -1200), True)])                                       # right behind him, walking
    act_state(m, 1, (1, 0x03, 0, 0))
    facing(m, 0.0)
    bot = B.Bot(m, clock=lambda: now[0], nav=False)
    assert run(bot, m, now, 0.0)[0] == {"hold": {"down", "b"}} and bot.stats["quick_turns"] == 1
    assert "down" not in run(bot, m, now, 0.2)[0]["hold"]                    # once: then the stick finishes the turn


def test_of_two_close_ones_the_one_in_front_is_shot_first():
    now = [0.0]
    m = world([((0, 0, -1000), True), ((0, 0, 1150), True)])               # one behind, one a little further in front
    act_state(m, 1, (1, 0x03, 0, 0))
    act_state(m, 2, (1, 0x03, 0, 0))
    facing(m, 0.0)
    bot = B.Bot(m, clock=lambda: now[0], nav=False)
    run(bot, m, now, 0.0)
    acts = run(bot, m, now, B.PITCH_AFTER + 0.05, 3)
    assert any("a" in a.get("hold", set()) for a in acts) and bot.target_slot == 2


def test_a_thrown_axe_too_close_to_shoot_is_stepped_out_of_its_line():
    now = [0.0]
    m = world([((0, 0, 6000), True)])
    axe = EM + 2 * STRIDE
    m.put(B.EMMGR, ">3I", EM, 3, STRIDE)
    m.put(axe, ">I", 1)
    m.put(axe + 0x100, ">B", B.threats_ram.THROWN_ID)
    m.put(axe + 0xFC, ">4B", 1, 6, 0, 0)                                    # in flight (01 06)
    facing(m, math.pi / 2)                                                   # looking away to his left: no shot in time
    bot = B.Bot(m, clock=lambda: now[0], nav=False)
    acts = []
    for k in range(4):
        m.put(axe + 0x94, ">3f", 30.0, 1400.0, 1200.0 - 150.0 * k)           # 3000 units / s, 0.3 s out
        acts += run(bot, m, now, 0.05 * k)
    assert bot.stats["evades"] == 1 and acts[-1]["hold"] >= {"up", "b"}
    away = bot.evade["away"]
    assert abs(abs(B.wrap(away)) - math.pi / 2) < 0.2                       # across its line (+-x), not along it


def test_a_thrown_axe_coming_at_him_is_aimed_at_where_it_will_be():
    now = [0.0]
    m = world([((0, 0, 6000), True)])                                       # the thrower, far out
    axe = EM + 2 * STRIDE
    m.put(B.EMMGR, ">3I", EM, 3, STRIDE)
    m.put(axe, ">I", 1)
    m.put(axe + 0x100, ">B", B.threats_ram.THROWN_ID)
    m.put(axe + 0xFC, ">4B", 1, 6, 0, 0)                                    # in flight (01 06)
    facing(m, 0.0)
    bot = B.Bot(m, clock=lambda: now[0], nav=False)
    for k in range(4):
        m.put(axe + 0x94, ">3f", 0.0, 1400.0, 4000.0 - 150.0 * k)            # 3000 units / s straight at him
        run(bot, m, now, 0.05 * k)
    assert bot.tracker.stats["thrown_seen"] == 1
    t = bot.tracker.update(B.snapshot(m), 0.2)
    assert t[0].kind == "thrown" and t[0].pos[2] < 3550.0


def aiming_world(rot, off, z=2000.0):
    """Leon aiming (00 06 01 01, the pose up) at a Ganado straight ahead along +z; his aim's own offset off."""
    m = world([((0, 0, z), True)])
    facing(m, rot)
    m.put(PL + 0xFC, ">4B", 0, 6, 1, 1)
    m.put(PL + B.AIM_YAW_OFF, ">f", off)
    return m


def test_the_gun_points_at_his_facing_plus_the_aims_own_offset():
    """While he aims the stick first moves the aim's offset (Leon +0x400) inside the weapon's cone, then turns him:
    the gun points at facing + offset (the aim routine 0x8014415C; run1.rec 2026-10-20)."""
    m = aiming_world(0.10, -0.08)                     # his body 0.10 left of the Ganado, the aim pushed back right
    s = B.snapshot(m)
    assert s["player"]["aim_rot"] == pytest.approx(0.02) and s["player"]["aim_off"] == pytest.approx(-0.08)
    bot = B.Bot(m, clock=lambda: 0.0, nav=False)
    assert bot.tick(s) == {"hold": {"r", "a"}}       # the gun is on him: fire (his facing alone said turn)
    m = aiming_world(-0.07, -0.05)                    # his body just inside, the aim further right: the gun is off
    bot = B.Bot(m, clock=lambda: 0.0, nav=False)
    act = bot.tick(B.snapshot(m))
    assert "a" not in act["hold"] and "left" in act["hold"]


def test_a_ganado_that_shots_never_reach_is_left_for_the_next():
    """BLOCKED_MISSES misses in a row at one (not attacking) Ganado: something is in the way (live 2026-10-21: a water
    tank took a clip) - he is skipped for BLOCKED_SKIP_S and the other one is shot."""
    now = [0.0]
    m = world([((0, 0, 2000), True), ((1500, 0, 1500), True)])          # straight ahead, and one off to his left
    facing(m, 0.0)
    m.put(PL + 0xFC, ">4B", 0, 6, 1, 1)                                   # aiming
    bot = B.Bot(m, clock=lambda: now[0], nav=False)
    for k in range(B.BLOCKED_MISSES):                                     # three shots, none lands
        bot.target_slot = 1
        bot.shots.fired(now[0])
        now[0] += B.threats_ram.Shots.HIT_S + 0.6
        bot._score(B.snapshot(m), now[0])
    assert bot.skip.get(1, 0) > now[0] and bot.stats["blocked_skips"] == 1
    act = bot.tick(B.snapshot(m))
    assert bot.aim["slot"] == 2 or "left" in act["hold"]                  # the other one now


def test_the_gun_stays_up_while_he_aim_turns_onto_a_target_that_moved():
    """Live 2026-10-21: a lunging Ganado moved his bearing past TURN_TOL; the bot lowered the gun to turn, raised it
    again (0.6 s of pose) and the swing landed. Already aiming, the gun stays up within AIM_KEEP_ERR."""
    now = [0.0]
    m = world([((0, 0, 2000), True)])
    facing(m, 0.5)                                                        # 0.5 rad off: past TURN_TOL
    bot = B.Bot(m, clock=lambda: now[0], nav=False)
    assert "r" not in bot.tick(B.snapshot(m))["hold"]                     # not aiming yet: turn round first
    bot.r_since = -1.0                                                    # aiming already
    m.put(PL + 0xFC, ">4B", 0, 6, 1, 1)
    assert bot.tick(B.snapshot(m))["hold"] >= {"r", "right"}             # the gun stays up, aim-turning
    facing(m, 1.2)                                                        # far round: then it comes down to turn
    assert "r" not in bot.tick(B.snapshot(m))["hold"]


def test_the_turn_rate_is_measured_from_his_turns():
    """gBox's stick keys give 72 of 127 (live 2026-10-21): the turn is slower than full stick, so the bot measures it
    (and its "can I shoot before that lands" sums use the measured rate)."""
    now = [0.0]
    m = world([((-2000, 0, 0), True)])                                       # far to his left (heading -pi/2)
    rot = 0.0
    facing(m, rot)
    bot = B.Bot(m, clock=lambda: now[0], nav=False)
    for k in range(12):
        now[0] = k * 0.05
        keys = bot.tick(B.snapshot(m)).get("hold", set())
        if keys == {"right"}:
            rot -= 0.075                                                    # 1.5 rad/s
        elif keys == {"left"}:
            rot += 0.075
        facing(m, rot)
    assert abs(bot.turn_rate - 1.5) < 0.6 and bot.stats["turn_rate"] == round(bot.turn_rate, 2)


def test_the_aim_offset_counts_only_while_he_aims_and_motion_values_are_not_the_pitch():
    m = aiming_world(0.3, 0.05)
    m.put(PL + 0xFC, ">4B", 0, 1, 0, 0)               # running: the offset left over from the last aim is stale
    m.put(PL + 0x258, ">f", 142.857)                  # a motion value (the quick turn's): never read as the aim
    m.put(B.AIM_PITCH, ">f", 0.25)                    # the aim's vertical blend, kept between aims
    m.put(B.GAME_PAD, ">bb", -127, 0)                 # the stick, as the game read it
    p = B.snapshot(m)["player"]
    assert p["aim_rot"] == pytest.approx(0.3) and p["aim_off"] == 0.0
    assert p["pitch"] == pytest.approx(0.25 * B.PITCH_SCALE) and p["stick"] == (-127, 0)
    m.put(B.AIM_PITCH, ">f", float("nan"))
    assert B.snapshot(m)["player"]["pitch"] is None   # out of its range: unknown, the stick is not pushed on it


def test_leon_is_mortal_in_the_package():
    assert ("unlimited_health", {"on": True}) not in B.PACKAGE
    assert ("unlimited_health", {"on": False}) in B.PACKAGE
    from gbox.mercs import vocab
    assert dict(vocab.profile("G4BE08").mercs["package"])["unlimited_health"] == {"on": False}


def test_never_fires_at_a_ganado_behind_a_wall_and_goes_for_the_bonus_instead():
    now = [0.0]
    m = world([((0, 0, 2200), True)], room=0x400, leon=(0.0, 0.0, 0.0))
    bonus = item("time_bonus", 9000.0, 0.0)
    bot = B.Bot(m, clock=lambda: now[0], nav=FakeNav([bonus], sight=False))
    facing(m, 0.0)
    act = bot.tick(B.snapshot(m))
    assert {"r", "a"}.isdisjoint(act["hold"]) and bot.goal is not None


def test_he_never_fires_with_the_aim_below_the_head_band():
    m = world([((0, 0, 1500), True)])
    facing(m, 0.0)
    now = [0.0]
    bot = B.Bot(m, clock=lambda: now[0], nav=False)
    gun = B.GUN_H
    lo = math.atan2(B.HEAD_LO - gun, 1500.0)
    set_pitch(m, lo - 0.3)                                                 # the last aim left at the ground
    below_fired, fired_at = False, None
    for k in range(120):
        now[0] = k * 0.05
        m.put(B.MERC_TIMER, ">I", int((100 - now[0]) * 30))
        keys = bot.tick(B.snapshot(m)).get("hold", set())
        pitch = get_pitch(m)
        if "a" in keys:
            fired_at = pitch
            if pitch < lo - 1e-6:
                below_fired = True
            break
        set_pitch(m, pitch + 0.02 * (("up" in keys) - ("down" in keys)))
    assert fired_at is not None and not below_fired                        # it raised the aim, then fired
    assert lo <= fired_at <= math.atan2(B.BODY_HI - gun, 1500.0)


def test_package_keeps_the_games_own_aim_turn_speed():
    # operator 2026-10-22: x3 aim speed made the camera spin spastically and the bot overshoot - regular speed
    assert B.AIM_SPEED_X == 1.0
    assert dict(B.PACKAGE)["aim_turn_speed"] == {"multiplier": 1.0}


def test_every_select_player_draws_a_random_loadout_and_the_package_skips_the_fixed_one(monkeypatch):
    calls = []
    from gbox import re_mods_tool as RM
    monkeypatch.setattr(RM, "RE4", lambda ad: object())
    monkeypatch.setattr(RM, "run", lambda ad, op, g=None, **kw: calls.append(op) or {"verified": True})
    menus = B._Menus(object(), object(), lambda *_: None, lambda *_: None, time.time, {})
    if menus.boot is None:
        pytest.skip("no menus module")
    assert menus.boot.round_hooks() == []
    assert calls == ["random_loadout"]
    calls.clear()
    assert menus.boot.hooks() == []
    assert "merc_loadout" not in calls and "weapon_mod" not in calls and "random_loadout" not in calls and calls


def _fake_spawn_g():
    import types
    V = types.SimpleNamespace(
        SPAWN_HOOK_CODE=b"\x01\x02\x03\x04", SPAWN_HOOK=0x80002800, SPAWN_DONE=0x800029C0,
        SPAWN_DUP_SITE=0x80100000, SPAWN_DUP_ORIG=b"\xAA\xAA\xAA\xAA", SPAWN_DUP_PATCH=b"\xBB\xBB\xBB\xBB",
        SPAWN_VARS=0x800029A0, HOOKS=0x80002000)
    mem = {}
    class M:
        def rd(self, a, n):
            return bytes(mem.get(a + i, 0) for i in range(n))
        def wr(self, a, b):
            for i, x in enumerate(b):
                mem[a + i] = x
        def u32(self, a):
            return 0
    g = types.SimpleNamespace(V=V, m=M(), hook=lambda: None)
    g.m.wr(V.SPAWN_DUP_SITE, V.SPAWN_DUP_ORIG)
    return g, mem


def test_spawn_multiplier_behaviour_writes_factor_and_restores(monkeypatch):
    import gbox.re_mods_tool as RM
    monkeypatch.setattr(RM.time, "sleep", lambda s: None)
    g, mem = _fake_spawn_g()
    for count in (2, 3, 4):                      # slider 2x-4x -> count=N, on=true
        r = RM.spawn_multiplier(g, count, True)
        assert r["factor"] == count and r["verified"] is True
        assert g.m.rd(g.V.SPAWN_VARS, 1)[0] == count
        assert g.m.rd(g.V.SPAWN_DUP_SITE, 4) == g.V.SPAWN_DUP_PATCH
    r = RM.spawn_multiplier(g, 4, False)         # slider 1x -> on=false: factor 1, original instruction back
    assert r["factor"] == 1 and r["verified"] is True
    assert g.m.rd(g.V.SPAWN_VARS, 1)[0] == 0
    assert g.m.rd(g.V.SPAWN_DUP_SITE, 4) == g.V.SPAWN_DUP_ORIG
    assert RM.spawn_multiplier(g, 99, True)["factor"] == 8      # backend bound unchanged (UI clamps to 4)


def test_downed_ganados_and_chickens_are_aimed_low_not_at_head_height():
    # operator 2026-10-24: Leon missed "people he knocked down, people who fell down, chickens"
    assert B.body_band({"r": (0, 0, 0, 0), "hp_max": 1000}) is B.BODY_BAND
    assert B.body_band({"r": (2, 1, 0, 0), "hp_max": 1000}) == B.LOW_BODY            # hurt: knocked down / fallen
    assert B.body_band({"r": (1, 0, 0, 0), "hp_max": 5}) == B.SMALL_BODY             # a chicken
    assert B.LOW_BODY[1] < B.HEAD_LO and B.SMALL_BODY[1] < B.HEAD_LO


def test_a_downed_ganado_at_his_feet_gets_a_step_back_into_the_aim():
    now = [0.0]
    m = world([((0, 0, 600), True)])                                         # 6 m ahead, on the ground
    act_state(m, 1, (2, 1, 0, 0))
    facing(m, 0.0)
    bot = B.Bot(m, clock=lambda: now[0], nav=False)
    acts = run(bot, m, now, 0.0, n=3)
    assert any(a.get("hold") == {"down"} for a in acts) and bot.stats["low_target_backsteps"] >= 1


def test_a_goal_inside_his_turning_circle_is_turned_to_on_the_spot_not_orbited():
    # operator 2026-10-24: "Leon is running into a circle"
    now = [0.0]
    m = world([])
    bot = B.Bot(m, clock=lambda: now[0], nav=False)
    p = {"pos": (0.0, 0.0, 0.0), "rot": 0.0}
    keys = bot._go(p, (1500.0, 800.0), 0.0)["hold"]                          # near, ~60 degrees off: no running
    assert not keys & {"up", "b"} and keys & {"left", "right"}
    far = bot._go(p, (9000.0, 5000.0), 0.1)["hold"]                          # far away: run while turning
    assert {"up", "b"} <= far


def test_running_round_in_circles_turns_on_the_spot_then_drops_the_goal():
    now = [0.0]
    m = world([])
    bot = B.Bot(m, clock=lambda: now[0], nav=False)
    bot.items = [{"pos": (5000.0, 0.0, 0.0)}, {"pos": (-5000.0, 0.0, 0.0)}]
    bot.goal = {"pos": (5000.0, 0.0, 5000.0)}
    first = bot.items[0]
    def lap(t0):
        for i in range(17):                                                   # a full turn in a 1.5 m circle, 4 s
            a = i * (2 * math.pi / 16)
            bot._circling({"pos": (750 * math.cos(a), 0.0, 750 * math.sin(a)), "rot": B.wrap(a)}, (5000.0, 5000.0),
                          t0 + i * 0.25)
    lap(0.0)
    assert bot.stats["circles_broken"] == 1 and bot.turn_first and bot.goal is not None
    lap(10.0)
    assert bot.stats["circle_goals_dropped"] == 1 and bot.goal is None and bot.items[0] is not first


def _ad_with_memory(calls, mem):
    # a live-adapter stand-in: the game's 32 MiB as one backing buffer; the disc id lives at Dolphin's
    # MEM1 base (0x80000000) the way the bot reads it, and at 0x80200000 the way re_mods does
    class Ad:
        def read_memory(self, a, n):
            i = a - 0x80000000
            return b"G4BE08" if (a, n) in ((0x80000000, 6), (0x80200000, 6)) else mem[i:i + n]

        def write_memory(self, a, data):
            calls.append((a, bytes(data)))
            mem[a - 0x80000000:a - 0x80000000 + len(data)] = bytes(data)

    return Ad()


def test_setup_applies_the_aim_turn_speed_package_item_at_the_games_own_speed():
    # operator 2026-10-22: the package's aim_turn_speed must reach re_mods at x1 (the game's own ~30 deg/s)
    import struct
    import gbox.re_mods_tool as RM
    mem = bytearray(0x2000000)
    calls = []
    ad = _ad_with_memory(calls, mem)
    pg = 0x80010000                                    # a valid game-struct base, so status() stays in bounds
    mem[RM.R.GC.P_GLOBAL - 0x80000000:RM.R.GC.P_GLOBAL - 0x80000000 + 4] = struct.pack(">I", pg)
    for a, orig in RM.R.GC.AIM_TURN:                   # seed the aim constants the game ships with
        mem[a - 0x80000000:a - 0x80000000 + 4] = struct.pack(">f", orig)
    failed = B.apply_package(ad, only=("aim_turn_speed",))
    assert failed == []
    for a, orig in RM.R.GC.AIM_TURN:
        data = [d for addr, d in calls if addr == a]
        assert data, f"{a:08X}: the aim constant was never written"
        assert struct.unpack(">f", data[0])[0] == orig * B.AIM_SPEED_X, f"{a:08X}: x{B.AIM_SPEED_X} expected"


def test_setup_only_runs_the_unlock_bits_at_the_title():
    # out of a Merc round setup() applies only the unlock bits - the aim constants stay the game's own
    import struct
    import gbox.re_mods_tool as RM
    mem = bytearray(0x2000000)
    calls = []
    ad = _ad_with_memory(calls, mem)
    B.setup(ad)
    assert not any(a in dict(RM.RE4(ad).V.AIM_TURN) for a, _ in calls), "aim speed must not be applied at the title"


def test_you_are_dead_answers_no_so_the_next_round_draws_a_new_character():
    # operator 2026-10-26: "why dont the character change between rounds? Stop picking the same character"
    from gbox import re4_menus as Mn
    sel = Mn.RandomSelections(key="test-dead-no")
    Mn.REQUESTS.pop("test-dead-no", None)
    dead = {"where": "dead"}
    assert sel.step(dead) == Mn.DPAD["right"] and sel.step(dead) == "a"   # No, not Continue Yes
    sel.screen.__func__                                                       # (bound API unchanged)
    sel.no_selected = False
    Mn.REQUESTS["test-dead-no"] = {"player": 1, "stage": None}               # an asked-for round keeps Continue Yes
    assert sel.step(dead) == "a"
    Mn.REQUESTS.pop("test-dead-no", None)
    assert sel.step({"where": "results"}) == "a"


def test_the_trigger_taps_about_ten_times_a_second():
    assert B.PRESS_HOLD <= 0.05 and B.PRESS_GAP <= 0.1
