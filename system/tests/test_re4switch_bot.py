"""The RE4 Switch playbook: it must claim only its own title, and it must start a round exactly once.

The failure this guards against is the one the operator saw: a round that never starts because nothing presses A, and the
opposite error - pressing into a screen nobody has classified. Both are cheap to pin with a stand-in adapter.
"""
import pytest

from gbox import re4switch_bot as B


class Adapter:
    """Records presses; hands back one frame per call from a script."""

    def __init__(self, frames):
        self.frames = list(frames)
        self.sent = []

    def get_frame(self):
        return self.frames.pop(0) if self.frames else b""


class Reader:
    """Stands in for the frame classifier: a script of screens, one per read."""

    def __init__(self, script):
        self.script = list(script)

    def read(self, frame):
        return {"where": self.script.pop(0) if self.script else "unknown"}


def test_it_only_claims_resident_evil_4_on_switch():
    assert B.matches(None, {"platform": "switch", "game_id": "270a15eb98dab4d7"}) is True
    assert B.matches(None, {"platform": "switch", "title": "Resident Evil 4 (Switch)"}) is True
    assert B.matches(None, {"platform": "gamecube", "title": "Resident Evil 4 (USA) (Disc 1)"}) is False
    assert B.matches(None, {"platform": "switch", "game_id": "52d15709be0fda1a", "title": "Resident Evil 5"}) is False
    assert B.matches(None, {}) is False


def test_setup_installs_nothing(monkeypatch):
    state = B.setup(None)
    assert state["hacks"] == [] and "screen-only" in state["note"]


def test_it_presses_three_times_to_start_a_round_and_then_plays(monkeypatch):
    """After a stage screen, `unknown` is a live round: exactly three A presses, then movement/fire."""
    monkeypatch.setattr(B.screens, "Reader", lambda: Reader(["select_stage"] + ["unknown"] * 40))
    adapter = Adapter([b"frame"] * 60)
    budget = {"n": 0}

    def stopped():
        budget["n"] += 1
        return budget["n"] > 22

    stats = {}
    result = B.play(adapter, lambda rows: adapter.sent.append(rows), stopped, sleep=lambda s: None, stats=stats)
    keys = [row[0]["key"] for row in adapter.sent if row and row[0].get("down")]
    assert stats["rounds"] == 1, "one round entered, not one per tick"
    assert keys.count("a") >= B.ROUND_ENTRY_PRESSES
    assert "w" in keys and "dup" in keys, "it advances and sweeps the aim once the round is live"
    assert result["ok"] is True and result["rounds"] == 1


def test_it_never_presses_into_an_unclassified_screen_before_a_stage(monkeypatch):
    """A screen nobody can classify, before any stage has been seen, must not be pressed through blindly."""
    monkeypatch.setattr(B.screens, "Reader", lambda: Reader(["unknown"] * 30))
    adapter = Adapter([b"frame"] * 30)
    budget = {"n": 0}

    def stopped():
        budget["n"] += 1
        return budget["n"] > 12

    stats = {}
    B.play(adapter, lambda rows: adapter.sent.append(rows), stopped, sleep=lambda s: None, stats=stats)
    assert adapter.sent == [], "no presses before the stage screen has been seen"
    assert stats["rounds"] == 0


def test_a_still_menu_walks_the_escape_sequence(monkeypatch):
    """A trapped menu: the playbook presses the escape one step per still picture - back out, lift the cursor off "No",
    confirm - which is what clears the "Cancel loading? Yes/No" prompt that held a run for minutes."""
    monkeypatch.setattr(B.screens, "Reader", lambda: Reader(["main_menu"] * 60))
    adapter = Adapter([b"same-frame"] * 80)          # byte-identical frames: the picture never changes
    ticks = {"n": 0}

    def clock():
        ticks["n"] += 1
        return float(ticks["n"]) * 10.0              # ten seconds per read: past still_s quickly

    stats = {}
    B.play(adapter, lambda rows: adapter.sent.append(rows), lambda: ticks["n"] > 30,
           sleep=lambda s: None, stats=stats, clock=clock, still_s=12.0)
    keys = [row[0]["key"] for row in adapter.sent if row and row[0].get("down")]
    assert keys[:len(B.STALL_ESCAPE)] == list(B.STALL_ESCAPE), f"the escape must run in order, got {keys}"
    assert stats["stall_steps"] >= len(B.STALL_ESCAPE)


def test_the_escape_advances_even_while_the_picture_repaints(monkeypatch):
    """The reason the escape used to fail: a cursor moving on a stuck menu repaints the picture without going anywhere, so
    pixels cannot be the reset signal. The same *named screen* means the same stall, however much it repaints."""
    monkeypatch.setattr(B.screens, "Reader", lambda: Reader(["main_menu"] * 60))
    frames = [bytes([i % 250]) * 4 for i in range(60)]      # every frame differs from the last
    adapter = Adapter(frames)
    ticks = {"n": 0}

    def clock():
        ticks["n"] += 1
        return float(ticks["n"]) * 10.0

    stats = {}
    B.play(adapter, lambda rows: adapter.sent.append(rows), lambda: ticks["n"] > 26,
           sleep=lambda s: None, stats=stats, clock=clock, still_s=12.0)
    keys = [row[0]["key"] for row in adapter.sent if row and row[0].get("down")]
    assert keys[:len(B.STALL_ESCAPE)] == list(B.STALL_ESCAPE), f"a repainting stuck screen still escalates, got {keys}"


def test_a_change_of_named_screen_restarts_the_escape(monkeypatch):
    """Progress is a different named screen: that is what puts the escape back to its first press."""
    script = ["main_menu"] * 6 + ["extras_menu"] * 30
    monkeypatch.setattr(B.screens, "Reader", lambda: Reader(script))
    adapter = Adapter([b"frame"] * 60)
    ticks = {"n": 0}

    def clock():
        ticks["n"] += 1
        return float(ticks["n"]) * 10.0

    stats = {}
    B.play(adapter, lambda rows: adapter.sent.append(rows), lambda: ticks["n"] > 20,
           sleep=lambda s: None, stats=stats, clock=clock, still_s=12.0)
    assert stats["stall_steps"] <= len(B.STALL_ESCAPE), "a new screen resets the sequence"


def test_a_maximum_duration_ends_the_run(monkeypatch):
    monkeypatch.setattr(B.screens, "Reader", lambda: Reader(["select_stage"] + ["unknown"] * 40))
    adapter = Adapter([b"frame"] * 60)
    ticks = {"n": 0}

    def clock():
        ticks["n"] += 1
        return float(ticks["n"])

    stats = {}
    result = B.play(adapter, lambda rows: adapter.sent.append(rows), lambda: False, sleep=lambda s: None,
                    stats=stats, clock=clock, max_seconds=3)
    assert result["ok"] is True and stats["seconds"] >= 0


class Scripted:
    """A reader that hands back whole screen dicts (cursor rows, steering counts)."""

    def __init__(self, script):
        self.script = list(script)

    def read(self, frame):
        return dict(self.script.pop(0)) if self.script else {"where": "unknown"}


def _down(adapter):
    return [row[0]["key"] for row in adapter.sent if row and row[0].get("down")]


def test_the_main_menu_walk_reaches_extras_without_the_escape_backing_it_out(monkeypatch):
    """Live 2026-11-09 (lilspark, three times in a row): LOAD -> EXTRAS is four cursor steps at the walk's 3 s gap, the
    escape fired 13 s after the menu came up - just as the cursor reached EXTRAS - and its back press put the game on the
    title again. A cursor that moves is progress."""
    script = []
    for row in (1, 2, 3, 4, 5):
        script += [{"where": "main_menu", "cursor": row}] * 3     # three reads (3 s) per row
    for row in (0, 1, 2):
        script += [{"where": "extras_menu", "cursor": row}] * 3
    reader = Scripted(script)
    monkeypatch.setattr(B.screens, "Reader", lambda: reader)
    adapter = Adapter([b"frame"] * 80)
    t = [1000.0]                                         # time moves when the playbook sleeps (about 1 s a read)

    def sleep(s):
        t[0] += s if s >= 0.2 else 0.0

    stats = {}
    B.play(adapter, lambda rows: adapter.sent.append(rows), lambda: not reader.script,
           sleep=lambda s: sleep(s * 5), stats=stats, clock=lambda: t[0], still_s=12.0)
    keys = _down(adapter)
    assert "b" not in keys, f"the escape backed the walk out of a working menu: {keys}"
    assert keys.count("ddown") >= 6 and keys.count("a") == 2 and stats.get("title_returns", 0) == 0


def test_a_cursor_that_never_settles_is_still_a_stall(monkeypatch):
    script = [{"where": "main_menu", "cursor": 1 + (i % 2)} for i in range(200)]
    monkeypatch.setattr(B.screens, "Reader", lambda: Scripted(script))
    adapter = Adapter([b"frame"] * 200)
    ticks = {"n": 0}

    def clock():
        ticks["n"] += 1
        return float(ticks["n"]) * 5.0

    B.play(adapter, lambda rows: adapter.sent.append(rows), lambda: ticks["n"] > 400,
           sleep=lambda s: None, stats={}, clock=clock, still_s=12.0)
    assert "b" in _down(adapter), "past CURSOR_PROGRESS_MAX a moving cursor no longer holds the escape off"


def test_the_dj_pick_is_steered_on_select_player_and_select_stage(monkeypatch):
    """Ada on Waterworld: one step right on Select Player, then right + down on the stage grid, each then confirmed."""
    from gbox.mercs.titles import re4_switch_screens as S
    seq = iter([{"where": "select_player"}] + [{"where": "unknown"}] * 8 + [{"where": "select_stage"}]
               + [{"where": "unknown"}] * 12 + [{"where": "loading"}] * 40)
    monkeypatch.setattr(S, "classify", lambda _png: next(seq, {"where": "unknown"}))
    adapter = Adapter([b"frame"] * 200)
    ticks = {"n": 0}

    def clock():
        ticks["n"] += 1
        return 1000.0 + ticks["n"] * 1.1

    game = {"launch": {"mercmode": {"selection": {"title": "re4", "mode": "mercenaries", "character": "Ada",
                                                   "stage": 3, "stage_name": "Waterworld"}}}}
    stats = {}
    B.play(adapter, lambda rows: adapter.sent.append(rows), lambda: ticks["n"] > 120,
           sleep=lambda s: None, stats=stats, clock=clock, still_s=12.0, game=game)
    keys = _down(adapter)
    assert stats["queued_selection"] == "Ada / Waterworld"
    assert keys[:5] == ["dright", "a", "dright", "ddown", "a"], keys


def test_a_bad_pick_is_reported_and_the_defaults_are_walked(monkeypatch):
    monkeypatch.setattr(B.screens, "Reader", lambda: Reader(["unknown"]))
    stats = {}
    B.play(Adapter([b"f"]), lambda rows: None, lambda: True, sleep=lambda s: None, stats=stats,
           game={"launch": {"mercmode": {"selection": {"title": "re4", "character": "Chris"}}}})
    assert "Chris" in stats["queued_selection_error"]
    assert B.driver.SELECTION == {"player": None, "stage": None}


def test_keys_go_down_once_and_up_when_let_go():
    sent = []
    k = B.Keys(sent.append)
    k.apply({"hold": {"lup", "lright"}})
    k.apply({"hold": {"lup", "lright"}})
    k.apply({"hold": {"zl"}, "tap": "zr"})
    k.release()
    assert sent == [[{"key": "lright", "down": True}, {"key": "lup", "down": True}],
                    [{"key": "lright", "down": False}, {"key": "lup", "down": False},
                     {"key": "zl", "down": True}, {"key": "zr", "down": True}, {"key": "zr", "down": False}],
                    [{"key": "zl", "down": False}]]


RAN_OUT = [62.0 - 2 * i for i in range(32)] + [0.0] * 60    # ~2 wall s per read in _round: a real run-down


class FakeRound:
    """driver.snapshot stand-in: a clock that counts down to 0 and a player 5 m from one Ganado."""

    def __init__(self, timers, player=True):
        self.timers, self.player = list(timers), player

    def __call__(self, m):
        t = self.timers.pop(0) if len(self.timers) > 1 else self.timers[0]
        return {"timer": t, "clock_addr": 0x3CA8E78710, "enemies": [{"pos": (0.0, 0.0, 500.0), "hp": 400, "ptr": 9}],
                "player": {"pos": (0.0, 0.0, 0.0), "rot": 0.0, "hp": 1000, "ptr": 1} if self.player else None}


def _round(monkeypatch, timers, player=True, boundary=None, n=400):
    monkeypatch.setattr(B.screens, "Reader", lambda: Reader(["playing"] * 200))
    monkeypatch.setattr(B.driver, "snapshot", FakeRound(timers, player))
    adapter = Adapter([b"frame"] * 200)
    ticks = {"n": 0}

    def clock():
        ticks["n"] += 1
        return 1_000_000.0 + ticks["n"] * 0.5

    stats = {}
    out = B.play(adapter, lambda rows: adapter.sent.append(rows), lambda: ticks["n"] > n, sleep=lambda s: None,
                 stats=stats, clock=clock, m=object(), round_boundary=boundary)
    return adapter, stats, out


def test_with_the_player_in_ram_the_bot_fights_through_holds_and_taps(monkeypatch):
    adapter, stats, out = _round(monkeypatch, [100.0 - i for i in range(60)])
    rows = [r for batch in adapter.sent for r in batch]
    assert stats["fight"] == "ram" and out["mode"] == "re4-switch-ram"
    assert {"key": "zr", "down": True} in rows and {"key": "zl", "down": True} in rows
    assert stats["shots"] >= 1 and "w" not in _down(adapter), "the blunt cadence does not run beside the fight"


def test_the_round_end_posts_one_boundary_with_the_clock_witness(monkeypatch):
    posted = []
    _, stats, out = _round(monkeypatch, RAN_OUT, boundary=lambda body, st: posted.append(body) or True)
    assert len(posted) == 1 and out["boundaries_posted"] == 1
    body = posted[0]
    assert body["map_id"] == "010099A00BC1E000" and body["role"] == "solo_p1"
    assert body["source"] == "native_terminal_reader" and len(body["round_id"]) == 32
    w = body["witness"]
    assert w["screen"] == "results" and w["timer"] == 0 and w["tally_ready"] is True
    assert w["clock_verified"] is True and w["playing_observed"] is True and w["player_verified"] is True
    assert (body["character"], body["stage"]) == ("Leon", "Village")


def test_without_the_player_the_clock_alone_witnesses_the_results(monkeypatch):
    posted = []
    _, stats, _ = _round(monkeypatch, RAN_OUT, player=False,
                         boundary=lambda body, st: posted.append(body) or True)
    assert stats["fight"] == "frame"
    assert len(posted) == 1 and posted[0]["witness"]["player_verified"] is False
    assert posted[0]["witness"]["clock_verified"] is True


def test_a_short_countdown_is_not_the_rounds_clock(monkeypatch):
    """A float that fell at wall rate from 10 s (a picked-by-mistake timer) must not end the round: the results need
    a clock seen at RESULTS_MIN_CLOCK_S or more, run down at no more than the fastest emulation allows."""
    posted = []
    _round(monkeypatch, [10.0 - i for i in range(11)] + [0.0] * 60, boundary=lambda body, st: posted.append(body) or True)
    assert posted == []
    posted.clear()
    _round(monkeypatch, [90.0, 60.0, 30.0] + [0.0] * 60, boundary=lambda body, st: posted.append(body) or True)
    assert posted == [], "90 s of clock gone in 4 s of wall time is not this round's clock"


def test_a_clock_never_seen_counting_posts_nothing(monkeypatch):
    posted = []
    _round(monkeypatch, [0.0] * 50, player=False, boundary=lambda body, st: posted.append(body) or True)
    assert posted == [], "a clock at 0 from the first read is a results screen this run did not play"


def test_a_round_outside_mercmode_says_why_it_posted_nothing(monkeypatch):
    _, stats, _ = _round(monkeypatch, RAN_OUT, boundary=None)
    assert "no round_boundary sink" in stats["mercmode_boundary_error"]


def test_the_playbook_asks_for_the_boundary_sink_and_the_game():
    """tools._start_playbook passes round_boundary and game only to a play() whose signature names them."""
    import inspect
    params = inspect.signature(B.play).parameters
    assert "round_boundary" in params and "game" in params and "stats" in params


class Game:
    """A closed-loop stand-in for RE4 Switch's menus: presses move the cursor or change the screen after a fade, the main
    menu returns to the title after IDLE_S without a press (the coordinator's hypothesis, kept in so the walk must beat
    it), A on LOAD opens the story save list (the failure the walk must never cause), and three A presses page the
    round's intro. Time only moves when the playbook sleeps."""

    FADE_S, IDLE_S, LOAD_S = 0.6, 30.0, 2.0

    def __init__(self):
        self.t = 0.0
        self.screen, self.cursor = "title", 0
        self.fade_until = 0.0
        self.last_press = 0.0
        self.intro_pages = 0
        self.log = []

    def clock(self):
        self.t += 0.001
        return self.t

    def sleep(self, s):
        self.t += max(s, 0.0)

    def _go(self, screen, cursor=0):
        self.screen, self.cursor, self.fade_until = screen, cursor, self.t + self.FADE_S

    def frame(self):
        if self.screen == "main_menu" and self.t - self.last_press > self.IDLE_S:
            self._go("title")
        if self.screen == "loading" and self.t >= self.fade_until + self.LOAD_S:
            self._go("intro")
        return b"sim"

    def classify(self, _png):
        if self.t < self.fade_until:
            return {"where": "unknown"}
        if self.screen in ("main_menu", "extras_menu"):
            return {"where": self.screen, "cursor": self.cursor}
        if self.screen == "intro":
            return {"where": "unknown"}
        if self.screen == "round":
            return {"where": "playing"}
        return {"where": self.screen}

    def send(self, rows):
        for row in rows:
            if not row.get("down"):
                continue
            key = row["key"]
            self.log.append((round(self.t, 2), self.screen, key))
            self.last_press = self.t
            if self.t < self.fade_until:
                continue                                     # a press during a fade is dropped
            s = self.screen
            if s == "title" and key == "a":
                self._go("main_menu", 1)
            elif s in ("main_menu", "extras_menu") and key in ("ddown", "dup"):
                top = 6 if s == "main_menu" else 4
                self.cursor = min(max(self.cursor + (1 if key == "ddown" else -1), 0), top)
            elif s == "main_menu" and key == "a":
                self._go("extras_menu", 0) if self.cursor == 5 else self._go("story")
            elif s == "main_menu" and key == "b":
                self._go("title")
            elif s == "extras_menu" and key == "a":
                self._go("mercs_title") if self.cursor == 2 else self._go("story")
            elif s == "mercs_title" and key == "a":
                self._go("select_player")
            elif s == "select_player" and key == "a":
                self._go("select_stage")
            elif s == "select_stage" and key == "a":
                self._go("loading")
            elif s == "intro" and key == "a":
                self.intro_pages += 1
                if self.intro_pages >= 3:
                    self._go("round")


def test_the_walk_reaches_a_round_fast_and_never_backs_out(monkeypatch):
    """Title to a live round in a closed loop: at one press per 3 s the main menu alone took 12 s and the old escape
    backed it out every time (2026-11-09/10, live). Now: no back press, no story screen, the round inside 25 s."""
    from gbox.mercs.titles import re4_switch_screens as S
    game = Game()
    monkeypatch.setattr(S, "classify", game.classify)

    class Ad:
        get_frame = staticmethod(game.frame)

    stats = {}
    B.play(Ad(), game.send, lambda: stats.get("rounds", 0) >= 1 or game.t > 120, sleep=game.sleep, stats=stats,
           clock=game.clock)
    keys = [k for _, _, k in game.log]
    assert game.screen == "round", (game.screen, game.log[-8:])
    assert "b" not in keys and not any(s == "story" for _, s, _ in game.log), game.log
    assert stats["walk_s"] < 25.0, stats["walk_s"]
    assert stats.get("title_returns", 0) == 0


def test_the_walk_survives_the_title_coming_back(monkeypatch):
    """The game drops the main menu to the title (an idle return): the walk names the title and starts again."""
    from gbox.mercs.titles import re4_switch_screens as S
    game = Game()
    game.IDLE_S = 2.5                                    # shorter than the walk needs: the title comes back once
    monkeypatch.setattr(S, "classify", game.classify)

    class Ad:
        get_frame = staticmethod(game.frame)

    stats = {}
    B.play(Ad(), game.send, lambda: game.screen == "extras_menu" or game.t > 60, sleep=game.sleep, stats=stats,
           clock=game.clock)
    if game.screen != "extras_menu":
        assert stats.get("title_returns", 0) >= 1, "a title return is counted where the panel can see it"
    assert "b" not in [k for _, _, k in game.log]
