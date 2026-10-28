"""The drivers' read hooks for the learned tuning (gbox/mercs/tuning.py): RE5 / RE6 Switch apply it at each round
start for the round's stage; RE5 seeds its dead ends from the learned ones and notes each stuck relocation."""
import pytest

from gbox.mercs import tuning
from gbox.mercs.titles import re5_switch as R5, re6_switch as R6


@pytest.fixture
def calls(monkeypatch):
    seen = []
    monkeypatch.setattr(tuning, 'apply', lambda title, stage, stats=None, base=None: seen.append((title, stage)))
    return seen


def test_re5_applies_the_tuning_of_the_stage_the_menus_pick_at_each_round_start(calls, monkeypatch):
    monkeypatch.setitem(R5.SELECTION, 'stage', 1)
    bot = R5.Bot(stats={}, clock=lambda: 0.0)
    bot._new_round(5.0)
    assert calls == [(R5.MAP_ID, 'The Mines')]


def test_re6_applies_the_tuning_of_the_round_that_went_up(calls, monkeypatch):
    monkeypatch.setattr(R6.PICK, 'last', {'stage': 0})
    bot = R6.Bot(stats={}, clock=lambda: 0.0)
    bot._round_start({}, 5.0)
    bot._round_start({}, 6.0)                                        # once a round
    assert calls == [(R6.MAP_ID, R6.STAGES[0])]


def test_re5_seeds_its_dead_ends_from_the_learned_ones_and_notes_a_stuck_run(monkeypatch):
    noted = []
    monkeypatch.setattr(tuning, 'apply', lambda title, stage, stats=None, base=None: {})
    monkeypatch.setattr(tuning, 'dead_ends', lambda title: [(500.0, 0.0, 900.0)])
    monkeypatch.setattr(tuning, 'note_dead_end',
                        lambda title, pos, goal=None, base=None, now=None: noted.append((pos, goal)))
    clock = [10.0]
    bot = R5.Bot(stats={}, clock=lambda: clock[0])
    bot._new_round(clock[0])
    assert bot._dead_ends == [(500.0, 0.0, 900.0)]                   # his relocation goals avoid them this round
    monkeypatch.setattr(bot, '_reloc_goal', lambda p, live, snap, now: (0.0, None, (0.0, 0.0, 800.0)))
    bot._reloc_due, bot._reloc_ready = True, -1e9
    p = {'pos': (0.0, 0.0, 0.0), 'rot': 0.0, 'hp': 1000, 'hp_max': 1000}
    bot._relocate(p, [], lambda e: 1e9, {'bonuses': []}, clock[0])
    clock[0] += R5.RELOC_STUCK_S + 0.5                               # no progress since: a dead end
    assert bot._relocate(p, [], lambda e: 1e9, {'bonuses': []}, clock[0]) is None
    assert noted == [((0.0, 0.0), (0.0, 0.0, 800.0))] and bot.stats['reloc_dead_ends'] == 1


def test_learned_dead_ends_come_from_the_rounds_avoid_spots(tmp_path):
    (tmp_path / 'T').mkdir()
    (tmp_path / 'T' / tuning.FILE).write_text('{"schema": "gbox.mercs.tuning/1", "title": "T", "version": "v", '
                                              '"params": {}, "avoid": {"Village": [[100, 200, 250]]}}')
    tuning._cache.clear()
    tuning.apply('T', 'Village', {}, base=tmp_path)
    assert tuning.dead_ends('T') == [(100.0, 0.0, 200.0)]
    tuning.note_dead_end('T', (1.2, 3.4), (10.0, 0.0, 20.0), base=tmp_path, now=1.0)
    assert (tmp_path / 'T' / tuning.DEAD_ENDS).read_text().strip() ==         '{"at": 1.0, "stage": "Village", "x": 1, "z": 3, "gx": 10, "gz": 20}'
