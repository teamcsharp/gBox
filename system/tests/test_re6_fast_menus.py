"""RE6 Switch menu bursts: whole cursor batches with only segment boundaries confirmed."""
from gbox.mercs.titles import re6_switch


class FakeGame:
    """The measured route as RAM would report it: each A advances a screen once its cursor is on the target."""

    def __init__(self):
        self.where = "main_menu"
        self.cursor = 0
        self.targets = {"main_menu": 0, "play_game": 3, "extra_content": 2, "mercs_mode": 0,
                        "select_stage": 0, "select_player": 0}
        self.next = {"main_menu": "play_game", "play_game": "extra_content", "extra_content": "mercs_mode",
                     "mercs_mode": "select_stage", "select_stage": "select_player", "select_player": "playing"}
        self.presses = []
        self.stuck = False

    def screen(self, m):
        return {"where": self.where, "cursor": self.cursor, "target": self.targets.get(self.where)}

    def send(self, events):
        event = events[0]
        if not event.get("down"):
            return
        key = event["key"]
        self.presses.append(key)
        if key in ("down", "ddown") and not self.stuck:
            self.cursor += 1
        elif key in ("up", "dup") and not self.stuck:
            self.cursor -= 1
        elif key == "a" and self.cursor == self.targets.get(self.where):
            self.where = self.next[self.where]
            self.cursor = 0


def _run(fake):
    stats = {}
    clock = iter(range(100000))

    def now():
        return next(clock) * 0.01

    ok = re6_switch.fast_start(object(), fake.send, stats=stats, screen_fn=fake.screen,
                               sleep=lambda _s: None, clock=now)
    return ok, stats


def test_cursor_moves_are_batched_and_the_route_reaches_playing():
    fake = FakeGame()
    ok, stats = _run(fake)
    assert ok is True
    assert fake.where == "playing"
    assert stats["fast_start"]["ok"] is True
    # main_menu A; play_game ddown x3 A; extra_content ddown x2 A; mercs_mode A; select_stage A; select_player A
    assert fake.presses == ["a", "ddown", "ddown", "ddown", "a", "ddown", "ddown", "a", "a", "a", "a"]
    assert stats["fast_start"]["presses"] == 11


def test_a_stuck_screen_falls_back_without_spamming():
    fake = FakeGame()
    fake.stuck = True                        # the D-pad never moves this screen's cursor
    ok, stats = _run(fake)
    assert ok is False
    assert stats["fast_start"]["ok"] is False
    assert fake.presses.count("a") <= 3      # it did not keep pressing on a screen that did not move


def test_playing_already_is_an_immediate_success():
    fake = FakeGame()
    fake.where = "playing"
    ok, stats = _run(fake)
    assert ok is True
    assert fake.presses == []
