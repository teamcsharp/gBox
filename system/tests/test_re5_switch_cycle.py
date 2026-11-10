"""RE5 Switch stage cycle (operator 18:03: "a random character / costume each and every round ... and level. I want
them learning and studying and cycling through all of the levels"): each visit to the selects takes the least-played
stage (never the last) and a random character / costume (never the last), held until a round starts on them; a death
answers No (the selects again, never the same round)."""
import json
import random

import pytest

from gbox.mercs.titles import re5_switch as R


@pytest.fixture
def cyc(monkeypatch, tmp_path):
    c = R.StageCycle(tmp_path / "cycle.json", rng=random.Random(1))
    monkeypatch.setattr(R, "_CYCLE", {"c": c})
    monkeypatch.setattr(R, "SELECTION", {})
    monkeypatch.setattr(R, "CYCLE", True)
    return c


def test_the_least_played_stage_never_the_last_and_a_character_never_the_last(cyc):
    cyc.stages = {i: 3 for i in range(8)}
    cyc.stages[5] = 1
    cyc.last = (2, 4)
    stage, char = cyc.pick()
    assert stage == 5 and char != 4 and cyc.pick() == (stage, char)          # held until a round starts
    cyc.last, cyc.stages[5] = (5, char), 9
    cyc.held = None
    assert cyc.pick()[0] != 5


def test_every_stage_comes_round_in_eight_rounds(cyc):
    seen = set()
    for _ in range(8):
        s, c = cyc.pick()
        seen.add(s)
        cyc.started(s, c)
    assert seen == set(range(8))
    saved = json.loads(open(cyc.path, encoding="utf-8").read())
    assert sum(saved["stages"].values()) == 8 and saved["last"] == list(cyc.last)


def test_the_selects_walk_to_the_pick_and_a_confirmed_round_is_counted_and_named(cyc):
    cyc.held = (3, 6)
    scr = {"where": "select_stage", "cursor": 0, "target": R.stage_target()}
    assert scr["target"] == 3 and R.step(scr) == "dright"
    R.pressed(scr, "dright")
    scr = {"where": "select_stage", "cursor": 3, "target": 3}
    assert R.step(scr) == "a"
    R.pressed(scr, "a")
    scr = {"where": "select_player", "cursor": 6, "target": R.player_target()}
    assert R.step(scr) == "a"
    R.pressed(scr, "a")
    d = R.RE5Switch()
    d.stats = {}
    d._cycle_started()
    assert d.stats["stage"] == "Ancient Ruins" and d.stats["character"] == "Jill (BSAA)"
    assert cyc.stages[3] == 1 and cyc.last == (3, 6) and "Ancient Ruins 1" in d.stats["stage_coverage"]
    d._cycle_started()
    assert cyc.stages[3] == 1                                                 # once a round


def test_a_target_the_cursor_never_reaches_is_given_up(cyc, monkeypatch):
    monkeypatch.setattr(R, "CHARACTER_SLOTS", 5)                 # a known roster: the locked-entry budget applies
    cyc.held = (0, 9)
    for _ in range(R.CYCLE_MAX_PRESSES):
        scr = {"where": "select_player", "cursor": 4, "target": 9}
        assert R.step(scr) == "dright"
        R.pressed(scr, "dright")
    assert R.step({"where": "select_player", "cursor": 4, "target": 9}) == "a"


def test_the_calibration_walk_may_pass_the_locked_entry_budget(cyc, monkeypatch):
    """The roster walk has to reach the right-hand end: the stall there is what teaches the count. Cutting it to the
    locked-entry budget made it confirm a mid-roster character, and the learning gate measured the score halving."""
    monkeypatch.setattr(R, "CHARACTER_SLOTS", 1)                 # calibrating: the roster count is unknown
    cyc.held = (0, 9)
    scr = {"where": "select_player", "cursor": 4, "target": 9}
    for _ in range(R.CYCLE_MAX_PRESSES + 5):                     # well past the locked-entry budget
        assert R.step(scr) == "dright"
        R.pressed(scr, "dright")
    for _ in range(R.CALIBRATE_PRESSES):                         # but the hard ceiling still ends the walk
        R.pressed(scr, "dright")
    assert R.step(scr) == "a"


def test_a_ten_entry_select_learns_its_count_from_the_wrap_of_its_own_forward_press(cyc, monkeypatch):
    """11-06..11-08 every calibration walk went round a 10-entry select 4 times (40 presses) and confirmed where it
    began (11-07: 51 of 53 rounds the same costume): the wrap rule wanted more than the 14 names."""
    monkeypatch.setattr(R, "CHARACTER_SLOTS", 0)
    cyc.observe_cursor(0, "select_player")                       # a reopened select at 0: no count from that
    assert R.CHARACTER_SLOTS == 0
    for cursor in range(9):
        cyc.note_press(cursor, "dright")
        cyc.observe_cursor(cursor + 1, "select_player")
    assert R.CHARACTER_SLOTS == 0
    cyc.note_press(9, "dright")
    cyc.observe_cursor(9, "select_player")                       # the press not shown yet: nothing learned, kept
    assert R.CHARACTER_SLOTS == 0
    cyc.observe_cursor(0, "select_player")                       # ... 9 -> 0: the wrap
    assert R.CHARACTER_SLOTS == 10 and json.loads(open(cyc.path, encoding="utf-8").read())["character_slots"] == 10
    monkeypatch.setattr(R, "CHARACTER_SLOTS", 0)
    cyc.note_press(1, "dright")
    cyc.observe_cursor(0, "select_player")                       # from entry 1: never a count of 2
    assert R.CHARACTER_SLOTS == 0


def test_a_walk_standing_at_the_end_confirms_at_once_but_a_moving_one_is_never_cut(cyc, monkeypatch):
    monkeypatch.setattr(R, "CHARACTER_SLOTS", 1)                 # calibrating
    now = [0.0]
    cyc.clock = lambda: now[0]
    cyc.held = (0, 30)
    for cursor in range(10):                                      # moving: every press moves it
        scr = {"where": "select_player", "cursor": cursor, "target": 30}
        assert R.step(scr) == "dright"
        R.pressed(scr, "dright")
        now[0] += 1.5
    end = {"where": "select_player", "cursor": 9, "target": 30}
    for _ in range(R.STALL_PRESSES):                              # standing at 9 through the Navigator's re-presses
        assert R.step(end) == "dright"
        R.pressed(end, "dright")
        now[0] += 0.4
    now[0] += R.STALL_S
    assert R.step(end) == "a" and cyc.presses < R.CALIBRATE_PRESSES
    R.pressed(end, "a")
    assert cyc.confirmed["character"] == 9 and cyc.stalls == 0


def test_the_operators_choice_wins(cyc, monkeypatch):
    monkeypatch.setattr(R, "SELECTION", {"stage": 6, "character": 2})
    assert R.stage_target() == 6 and R.player_target() == 2


def test_a_death_answers_no():
    assert R.REPLAY_ON_DEATH is False and R.continue_target() == R.CONTINUE_NO
