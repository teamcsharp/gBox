"""RE5 Switch instant menus (docs/research/re5-instant-menus.md): RAM cursor jumps (written, read back, held, proven
by the game's own step, then direct), their fallbacks, the Continue? Yes skip, the Navigator's per-screen learned waits,
and a simulated walk from the results to the next round's intro that gets faster run after run.

The menus are the fake 64-bit guest of tests/test_re5_switch.py (the live layout of 2026-10-26: sUnit's interface
units, their cursors at the measured offsets) driven by a small game model: a press is taken only once its screen has
been up READY_S, A moves on after FADE_S, a D-pad press moves the RAM cursor at once. Those latencies are the model's,
not measurements: the walk's seconds below compare the old and the new walk on the same model."""
import struct

import pytest

import test_re5_switch as T5
from gbox import mercs_bot as MB
from gbox.mercs import menu_speed
from gbox.mercs.titles import re5_switch as R

READY_S, FADE_S, LOAD_S = 0.10, 0.30, 1.0


class Adapter:
    """The Switch adapter's write_memory: a write into the guest, read back (gbox.adapters raises when it differs)."""

    def __init__(self, guest, refuse=False):
        self.guest, self.refuse, self.writes = guest, refuse, []

    def write_memory(self, address, data):
        if self.refuse:
            raise PermissionError("memory_write not granted")
        self.guest.put(address, bytes(data))
        self.writes.append((address, bytes(data)))
        return {"address": address, "written": len(data), "verified": True}


class Game:
    """The menus from a round's end to the next round's intro: alert_ok -> results -> loading -> STAGE SELECT ->
    CHARACTER SELECT -> loading -> the intro. The select cursor `model`: "honor" (the RAM integer IS the cursor),
    "revert" (the game keeps its own index and puts it back into RAM every frame: a write never holds), "shadow" (the
    game steps its own index and only writes RAM when it steps: a write holds but is not the cursor)."""
    SCREENS = ("alert_ok", "results", "loading", "select_stage", "select_player", "loading2", "intro")

    def __init__(self, model="honor", stage_open=0, player_open=0):
        self.g = T5.round_guest(phase=R.PHASE_OVER, player=False)
        self.g.adapter = Adapter(self.g)
        self.now, self.model = 0.0, model
        self.su = R.u64(self.g, T5.BASE + R.S_UNIT)
        self.gs = R.u64(self.g, R.u64(self.g, T5.BASE + R.S_MAIN) + R.MAIN_GAMESYS)
        self.opens = {"select_stage": stage_open, "select_player": player_open}
        self.index, self.appeared, self.due, self.own, self.off = 0, 0.0, None, None, None
        self.presses = []
        self._show()

    def where(self):
        return self.SCREENS[self.index]

    def _show(self):
        w = self.where()
        self.appeared, self.unit, self.own = self.now, None, None
        if w == "alert_ok":
            self.unit = self.g.obj("uIdAlert00", 0x400)
            self.g.put(self.unit + R.ALERT_UP, struct.pack("<ii", 0xC0, 0x09))
        elif w == "results":
            self.unit = self.g.obj("uIdMerceEd00", 0x400)
        elif w in ("loading", "loading2"):
            self.unit = self.g.obj("uIdNowLoading00", 0x400)
            self.due = self.now + LOAD_S
        elif w in ("select_stage", "select_player"):
            name, off = ("uIdStartUp21", R.MENU_CURSOR) if w == "select_stage" else ("uIdStartUp22", R.PLAYER_CURSOR)
            self.unit = self.g.obj(name, 0x400)
            self.off, self.own = off, self.opens[w]
            self.g.i32(self.unit + off, self.own)
        elif w == "intro":
            p = self.g.obj("uPl00ChrisNormal", 0x3000)
            self.g.put(p + R.P_HP, struct.pack("<hh", 1000, 1000))
            self.g.q(R.u64(self.g, T5.BASE + R.S_PLAYER) + R.P_FIRST, p)
            self.g.i32(self.gs + R.GS_PHASE, R.PHASE_INTRO)
        self.g.q(self.su + R.UNIT_LINES + R.LINE_STRIDE * 28, self.unit or 0)

    def go(self, where):
        while self.where() != where:
            self.index += 1
            self.due = None
            self._show()

    def cursor(self):
        return R._i32(self.g, self.unit + self.off)

    def advance(self, dt):
        end = self.now + max(0.0, dt)
        while self.due is not None and self.due <= end:
            self.now = max(self.now, self.due)
            self.index += 1
            self.due = None
            self._show()
        self.now = end
        if self.model == "revert" and self.own is not None:
            self.g.i32(self.unit + self.off, self.own)      # the game's own index, every frame

    def send(self, events):
        for e in events:
            if not e.get("down"):
                continue
            key, w = e["key"], self.where()
            self.presses.append((round(self.now, 3), w, key))
            if self.now - self.appeared < READY_S or self.due is not None:
                continue                                     # not taking input yet (or already moving on)
            if w in ("select_stage", "select_player") and key in ("dleft", "dright"):
                base = self.cursor() if self.model == "honor" else self.own
                self.own = max(0, min(13, base + (1 if key == "dright" else -1)))
                self.g.i32(self.unit + self.off, self.own)
            elif (w, key) in (("alert_ok", "a"), ("results", "plus"), ("select_stage", "a"), ("select_player", "a")):
                self.due = self.now + FADE_S
        return {"sent": 1}


@pytest.fixture
def menus(monkeypatch):
    monkeypatch.setattr(R, "CYCLE", False)
    monkeypatch.setattr(R, "SELECTION", {"stage": 6, "character": 7})
    monkeypatch.setattr(R, "_CYCLE", {"c": R.StageCycle(None)})
    R._CYCLE["c"].chars = {i: 1 for i in range(10)}      # characters 0-9 confirmed in earlier rounds: they exist
    monkeypatch.setattr(R, "MENU_JUMPS", True)
    monkeypatch.setattr(R, "MENU_LEARN", True)


def _learner(game):
    speed = menu_speed.Speed(clock=lambda: game.now)
    R._MENU["speed"] = speed
    return speed


def walk(game, stats=None, limit=60.0):
    """The play loop's menus part (gbox.mercs_bot.play): read, Boot.tick, sleep the poll. -> seconds to the intro."""
    stats = {} if stats is None else stats
    boot = MB.Boot(R, game.g, game.send, sleep=game.advance, clock=lambda: game.now, stats=stats)
    start = game.now
    while game.now - start < limit:
        scr = R.screen(game.g)
        if scr["where"] == "playing" and scr.get("intro"):
            return round(game.now - start, 2)
        why = boot.tick(game.now, scr=scr)
        assert why is None, why
        game.advance(boot.nav.poll_s(scr, MB.POLL_S))
    raise AssertionError(f"the walk did not reach the intro: {game.where()} {stats}")


def _enter(game, where):
    """The walk reaches `where` from the screen before it (the assist saw that one: a new visit, never the last)."""
    R.menu_assist(game.g, R.screen(game.g))
    game.go(where)


def _two_reads(game, stats=None):
    """A jumpable screen read twice a couple of frames apart (a write needs the same cursor twice): -> the 2nd assist."""
    R.menu_assist(game.g, R.screen(game.g), stats)
    game.advance(0.04)
    return R.menu_assist(game.g, R.screen(game.g), stats)


# --- the jumps on synthetic RAM ---------------------------------------------------------------------------------------
def test_an_approach_jump_writes_next_to_the_target_and_the_games_own_step_proves_it(menus):
    game = Game(stage_open=0)
    speed = _learner(game)
    _enter(game, "select_stage")
    stats = {}
    scr = R.screen(game.g)
    assert (scr["cursor"], scr["target"], scr["unit"]) == (0, 6, game.unit)
    assert R.menu_assist(game.g, scr, stats) is scr and not game.g.adapter.writes   # one read: no write yet
    game.advance(0.04)
    out = R.menu_assist(game.g, R.screen(game.g), stats)
    assert game.g.adapter.writes == [(game.unit + R.MENU_CURSOR, struct.pack("<i", 5))]
    assert out["cursor"] == 5 and out["jump_wait"] is True and R.step(out) is None    # not held yet: no press
    assert stats["menu_last_jump"] == "select_stage: cursor 0 -> 5 (approach, target 6)"
    game.advance(0.04)
    held = R.menu_assist(game.g, R.screen(game.g), stats)
    assert held["cursor"] == 5 and not held.get("jump_wait") and R.step(held) == "dright"
    assert speed.screen("select_stage")["jumps"] == 1
    game.advance(READY_S)
    game.send([{"key": "dright", "down": True}])                    # the game's own step: 5 -> 6
    landed = R.menu_assist(game.g, R.screen(game.g), stats)
    assert landed["cursor"] == 6 and R.step(landed) == "a"
    assert speed.screen("select_stage")["jump_proven"] == 1 and stats["menu_jumps_proven"] == 1


def test_after_the_proofs_a_screen_writes_its_target_and_confirms_with_one_press(menus):
    game = Game(stage_open=1)
    speed = _learner(game)
    for _ in range(R.JUMP_PROVE_N):
        speed.jump_result("select_stage", "proven")
    _enter(game, "select_stage")
    out = _two_reads(game)
    assert out["cursor"] == 6 and out["jumped"] == "direct" and game.cursor() == 6
    game.advance(0.04)
    assert R.step(R.menu_assist(game.g, R.screen(game.g))) == "a"


def test_a_write_the_game_puts_back_is_a_failure_and_the_walk_steps_option_by_option(menus):
    game = Game(model="revert", stage_open=0)
    speed = _learner(game)
    _enter(game, "select_stage")
    stats = {}
    _two_reads(game, stats)
    assert game.g.adapter.writes                                     # written and read back at once ...
    game.advance(0.04)                                               # ... but the game's next frame put its own back
    back = R.menu_assist(game.g, R.screen(game.g), stats)
    assert back["cursor"] == 0 and R.step(back) == "dright"          # stepping from the game's real cursor
    assert stats["menu_jump_fails"] == 1 and "did not hold" in stats["menu_jump_error"]
    assert speed.screen("select_stage")["jump_fails"] == 1
    game.advance(0.1)
    R.menu_assist(game.g, R.screen(game.g), stats)
    assert len(game.g.adapter.writes) == 1                           # that visit never writes again


def test_a_field_the_game_does_not_step_from_is_caught_and_failures_stop_the_jumps_until_reset(menus, monkeypatch):
    speed = None
    for _ in range(R.JUMP_FAIL_N):
        game = Game(model="shadow", stage_open=0)
        speed = speed or _learner(game)
        speed.clock = lambda: game.now
        _enter(game, "select_stage")
        _two_reads(game)
        game.advance(0.04)
        held = R.menu_assist(game.g, R.screen(game.g))
        assert held["cursor"] == 5 and R.step(held) == "dright"     # the write held in RAM ...
        game.advance(READY_S)
        game.send([{"key": "dright", "down": True}])                 # ... but the game stepped 0 -> 1, not 5 -> 6
        assert R.menu_assist(game.g, R.screen(game.g))["cursor"] == 1
    assert not speed.jump_allowed("select_stage")                    # back to stepping, kept in the profile
    game = Game(stage_open=0)
    speed.clock = lambda: game.now
    _enter(game, "select_stage")
    _two_reads(game)
    assert not game.g.adapter.writes
    monkeypatch.setattr(R, "MENU_JUMPS", False)
    R.menu_assist(game.g, R.screen(game.g))
    monkeypatch.setattr(R, "MENU_JUMPS", True)                       # the operator turns them off and on: trusted again
    R.menu_assist(game.g, R.screen(game.g))
    assert speed.jump_allowed("select_stage")


def test_only_entries_known_to_exist_are_written(menus, monkeypatch):
    game = Game(player_open=0)
    _learner(game)
    _enter(game, "select_player")
    monkeypatch.setitem(R.SELECTION, "character", 12)                # past every index the game has shown (0-9)
    out = _two_reads(game)
    assert not game.g.adapter.writes and out["cursor"] == 0 and R.step(out) == "dright"
    monkeypatch.setitem(R.SELECTION, "character", 7)
    R._SEEN_CURSOR.clear()
    out = _two_reads(game)
    assert out["cursor"] == 6 and game.g.adapter.writes[-1] == (game.unit + R.PLAYER_CURSOR, struct.pack("<i", 6))


def test_the_mode_list_jumps_next_to_no_mercy(menus):
    g = T5.round_guest(phase=R.PHASE_OVER, player=False, units=((28, "uIdStartUp29"),),
                       cursors={"uIdStartUp29": {R.MENU_SUB: 1, R.MODE_CURSOR: 0}})
    g.adapter = Adapter(g)
    clock = [0.0]
    R._MENU["speed"] = menu_speed.Speed(clock=lambda: clock[0])
    R.menu_assist(g, R.screen(g))
    clock[0] += 0.04
    out = R.menu_assist(g, R.screen(g))
    u = R.ui_units(g)["uIdStartUp29"]
    assert out["where"] == "mercs_mode" and out["cursor"] == 2
    assert g.adapter.writes == [(u + R.MODE_CURSOR, struct.pack("<i", 2))]
    assert R.step(dict(out, jump_wait=False)) == "ddown"


def test_no_write_without_a_writing_adapter_in_an_unmodified_session_or_on_a_unit_that_changed_class(menus):
    game = Game(stage_open=0)
    _learner(game)
    _enter(game, "select_stage")
    game.g.mercs_no_modifications = True
    stats = {}
    out = _two_reads(game, stats)
    assert not game.g.adapter.writes and out["cursor"] == 0 and "unmodified" in stats["menu_jump_error"]
    assert game.g.adapter._menu_jump_blocked                         # this session: no more tries
    game = Game(stage_open=0)
    _learner(game)
    game.g.adapter.refuse = True
    _enter(game, "select_stage")
    stats = {}
    _two_reads(game, stats)
    assert stats["menu_jump_error"].startswith("select_stage: write refused")
    game = Game(stage_open=0)
    _learner(game)
    _enter(game, "select_stage")
    scr = R.screen(game.g)
    R.menu_assist(game.g, scr)
    game.advance(0.04)
    game.g.q(game.unit, game.g.klass("uIdStartUp22"))                # freed and reused as another unit between reads
    stats = {}
    R.menu_assist(game.g, dict(scr), stats)
    assert not game.g.adapter.writes and "no longer uIdStartUp21" in stats["menu_jump_error"]


# --- the skip: Continue? Yes when the next round is this one ----------------------------------------------------------
def test_continue_yes_skips_the_whole_walk_only_when_the_next_round_is_this_one(monkeypatch):
    monkeypatch.setattr(R, "REPLAY_ON_DEATH", False)
    monkeypatch.setattr(R, "CYCLE", True)
    monkeypatch.setattr(R, "_CYCLE", {"c": R.StageCycle(None)})
    monkeypatch.setattr(R, "SELECTION", {})
    R._CYCLE["c"].last = (2, 4)
    assert R.continue_target() == R.CONTINUE_NO                      # the random cycle: never the same round
    monkeypatch.setattr(R, "SELECTION", {"stage": 2, "character": 4})
    assert R.continue_target() == R.CONTINUE_YES                     # the operator fixed this round: replay it
    R._CYCLE["c"].last = (2, 5)
    assert R.continue_target() == R.CONTINUE_NO                      # the last round was not on them
    R._CYCLE["c"].last = (2, 4)
    managed = type("C", (), {"managed": True})()
    m = type("M", (), {})()
    m.adapter = type("A", (), {"_merc_round_controls": managed})()
    assert R.continue_target(m) == R.CONTINUE_NO                     # the icon panel / a DJ pick owns the next round
    monkeypatch.setattr(R, "CYCLE", False)
    assert R.continue_target() == R.CONTINUE_NO                      # no record of what the selects confirmed
    monkeypatch.setattr(R, "CYCLE", True)
    monkeypatch.setattr(R, "REPLAY_SAME_ROUND", False)
    assert R.continue_target() == R.CONTINUE_NO


def test_the_dead_dialog_is_answered_on_the_first_frame_it_takes_input(monkeypatch):
    monkeypatch.setattr(R, "REPLAY_ON_DEATH", False)
    monkeypatch.setattr(R, "SELECTION", {})
    b, clock = T5.brain()
    dead = lambda ready: dict(T5.bot_snap(hp=0), continue_cursor=R.CONTINUE_YES, continue_ready=ready)
    assert b.tick(dead(None)) == {"hold": ()}
    clock[0] = 0.8
    assert b.tick(dead(False)) == {"hold": ()}                       # up, not taking input: the fixed wait holds
    clock[0] = 0.9
    assert b.tick(dead(True)) == {"tap": "dright"}                   # takes input at 0.9 s, not DEAD_WAIT_S (2.5 s)
    g = T5.round_guest(phase=R.PHASE_PLAYING, hp=0, units=((28, "uIdGameover00"),))
    u = R.ui_units(g)["uIdGameover00"]
    assert R.snapshot(g)["continue_ready"] is False
    g.i32(u + R.CONTINUE_INPUT, R.CONTINUE_TAKES_INPUT)
    assert R.snapshot(g)["continue_ready"] is True


# --- the Navigator's per-screen hints ------------------------------------------------------------------------------------
def test_the_navigator_takes_a_screens_learned_waits_but_never_longer_ones():
    sent, now = [], [0.0]
    tick = lambda s: now.__setitem__(0, now[0] + s)
    nav = MB.Navigator(sent.append, lambda scr: "a", sleep=tick, clock=lambda: now[0])
    scr = {"where": "results", "settle_s": 0.06, "hold_s": 0.12, "poll_s": 0.03}
    assert nav.tick(scr) is None
    now[0] += 0.07
    assert nav.tick(scr) == "a" and now[0] == pytest.approx(0.19)    # pressed at 0.07 s, held 0.12 s
    assert nav.poll_s(scr, MB.POLL_S) == 0.03
    now[0] += 0.5
    assert nav.tick(scr) is None                                     # a confirm unseen keeps RETRY_S (1.2 s)
    slow = {"where": "results", "settle_s": 9.0, "hold_s": 5.0}      # never longer than the fixed waits
    plain = MB.Navigator(sent.append, lambda s: "a", sleep=tick, clock=lambda: now[0])
    t0 = now[0]
    plain.tick(slow)
    now[0] += MB.Navigator.STABLE_S
    assert plain.tick(slow) == "a" and now[0] - t0 == pytest.approx(MB.Navigator.STABLE_S + MB.Navigator.HOLD_S)
    assert plain.poll_s({"where": "loading"}, MB.POLL_S) == MB.POLL_S
    dpad = MB.Navigator(sent.append, lambda s: "dright", sleep=tick, clock=lambda: now[0])
    sel = {"where": "select_stage", "cursor": 0, "target": 6, "settle_s": 0.05, "retry_s": 0.2, "dir_hold_s": 0.06}
    dpad.tick(sel)
    now[0] += 0.05
    assert dpad.tick(sel) == "dright"
    now[0] += 0.21
    assert dpad.tick(sel) == "dright"                                # unseen: again after the learned 0.2 s


# --- the whole walk, run after run --------------------------------------------------------------------------------------
def test_the_learned_walk_is_faster_than_the_fixed_one_and_faster_run_after_run(menus, monkeypatch, capsys):
    monkeypatch.setattr(R, "MENU_JUMPS", False)
    monkeypatch.setattr(R, "MENU_LEARN", False)
    base = Game(stage_open=0, player_open=0)
    _learner(base)
    before = walk(base)
    before_presses = len(base.presses)
    monkeypatch.setattr(R, "MENU_JUMPS", True)
    monkeypatch.setattr(R, "MENU_LEARN", True)
    game = Game(stage_open=0, player_open=0)
    speed = _learner(game)
    times, presses = [], []
    for run in range(12):
        if run:
            game.__init__(stage_open=0, player_open=0)
        times.append(walk(game))
        presses.append(len(game.presses))
    assert presses[0] < before_presses and presses[-1] <= 6          # alert, plus, two A (+ at most a step each)
    assert times[-1] < times[0] < before
    assert times[-1] <= before * 0.6
    assert speed.screen("select_stage")["jump_proven"] >= R.JUMP_PROVE_N
    assert all(t2 <= t1 + 0.05 for t1, t2 in zip(times[3:], times[4:]))   # no backsliding once learned
    with capsys.disabled():
        print(f"\n  walk (model, results -> intro, stage 0->6, character 0->7): fixed {before:.2f} s / "
              f"{before_presses} presses; learned run 1 {times[0]:.2f} s / {presses[0]} presses, run {len(times)} "
              f"{times[-1]:.2f} s / {presses[-1]} presses; per run {', '.join(f'{t:.2f}' for t in times)}")


def test_the_driver_times_a_round_end_to_its_clock_running(menus):
    game = Game()
    speed = _learner(game)
    d = R.RE5Switch(clock=lambda: game.now)
    stats = {}
    d.stats = stats
    d.screen(T5.round_guest(timer=97.5), None)                       # a round with its clock running
    assert speed.in_round
    game.now = 50.0
    d.screen(T5.round_guest(phase=R.PHASE_PLAYING, hp=0), None)      # he dies: the transition opens
    assert speed.open["kind"] == "next" and speed.open["start"] == 50.0
    game.now = 52.0
    _enter(game, "select_stage")
    walk(game)
    d.screen(T5.round_guest(timer=119.9), None)                      # the next round's clock runs
    assert stats["menu_play_seconds"] == pytest.approx(game.now - 50.0, abs=0.01)
    assert 0 < stats["menu_seconds"] < stats["menu_play_seconds"]
    assert stats["menu_screens"].startswith("alert_ok") and "intro" in stats["menu_screens"]
    assert R.menu_status()["text"].startswith("menus: ")


def test_the_sidebar_view_carries_the_menus_line_and_the_two_knobs(tmp_path):
    from gbox.mercs import bot_logic
    R._MENU["speed"] = None
    view = bot_logic.status("re5", path=tmp_path / "bot-logic.json")
    assert view["menus"]["text"] == "menus: not timed yet"
    knobs = {k["name"]: k for k in view["knobs"]}
    assert knobs["MENU_JUMPS"]["group"] == "Menus" and knobs["MENU_JUMPS"]["value"] is True
    assert knobs["MENU_LEARN"]["kind"] == "bool"
    clock = [0.0]
    speed = R._MENU["speed"] = menu_speed.Speed(clock=lambda: clock[0])
    speed.gameplay()
    clock[0] = 80.0
    speed.round_end()
    for where in ("alert_ok", "results", "select_stage", "select_player", "loading"):
        clock[0] += 1.0
        speed.seen(where, (where, 1, None))
    clock[0] += 20.0
    speed.gameplay()
    assert bot_logic.status("re5", path=tmp_path / "bot-logic.json")["menus"]["text"] == \
        "menus: 5 s (best 5 s) · to play 25 s"
