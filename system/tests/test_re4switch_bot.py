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
