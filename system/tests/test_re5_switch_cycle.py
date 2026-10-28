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


def test_a_target_the_cursor_never_reaches_is_given_up(cyc):
    cyc.held = (0, 9)
    for _ in range(R.CYCLE_MAX_PRESSES):
        scr = {"where": "select_player", "cursor": 4, "target": R.player_target()}
        assert R.step(scr) == "dright"
        R.pressed(scr, "dright")
    assert R.step({"where": "select_player", "cursor": 4, "target": 9}) == "a"


def test_the_operators_choice_wins(cyc, monkeypatch):
    monkeypatch.setattr(R, "SELECTION", {"stage": 6, "character": 2})
    assert R.stage_target() == 6 and R.player_target() == 2


def test_a_death_answers_no():
    assert R.REPLAY_ON_DEATH is False and R.continue_target() == R.CONTINUE_NO
