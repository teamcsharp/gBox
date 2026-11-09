"""Tier (a) of the learning loop: the learned constants the bots read (gbox/mercs/tuning.py) and the server's tuner
that steps, keeps, reverts and expires them from the measured rounds (gbox/mercs/tuner.py)."""
import json
import math
from pathlib import Path
import sqlite3
import sys
import types

import pytest

from gbox.mercs import tuner as TU, tuning as T
from gbox.mercs.learning import Learning
from gbox.store import Store

TITLE, GAME = '010018100CD46000', '52d15709be0fda1a'


@pytest.fixture
def fake_bot(monkeypatch):
    """A stand-in driver module with two tunable constants (the real drivers are not touched here)."""
    mod = types.ModuleType('gbox.mercs.titles.fake_bot')
    mod.RELOC_CROWD_N, mod.BLAST_CM = 6, 800.0
    monkeypatch.setitem(sys.modules, 'gbox.mercs.titles.fake_bot', mod)
    monkeypatch.setitem(T.PARAMS, 'FAKE', {'fake_bot.RELOC_CROWD_N': (4, 6, -1),
                                           'fake_bot.BLAST_CM': (800.0, 1200.0, 100.0)})
    T._cache.clear()
    return mod


def write(base, title, params=None, avoid=None, version='v1'):
    path = Path(base) / title
    path.mkdir(parents=True, exist_ok=True)
    (path / T.FILE).write_text(json.dumps({'schema': T.SCHEMA, 'title': title, 'version': version,
                                           'params': params or {}, 'avoid': avoid or {}}))
    T._cache.clear()


def test_apply_sets_the_stages_constants_within_bounds_and_stamps_the_round(fake_bot, tmp_path):
    write(tmp_path, 'FAKE', {'*': {'fake_bot.BLAST_CM': 1000}, 'The Mines': {'fake_bot.RELOC_CROWD_N': 1,
                                                                             'fake_bot.OTHER': 3}})
    stats = {}
    applied = T.apply('FAKE', 'The Mines', stats, base=tmp_path)
    assert applied == {'fake_bot.BLAST_CM': 1000.0, 'fake_bot.RELOC_CROWD_N': 4}     # 1 clamped to the floor 4
    assert (fake_bot.BLAST_CM, fake_bot.RELOC_CROWD_N) == (1000.0, 4) and not hasattr(fake_bot, 'OTHER')
    assert stats == {'tuning_stage': 'The Mines', 'tuning_version': 'v1',
                     'tuning_params': 'BLAST_CM=1000.0,RELOC_CROWD_N=4', 'tuning_avoid': 0}
    T.apply('FAKE', 'Village', stats, base=tmp_path)                 # another stage: only the "*" entry
    assert (fake_bot.BLAST_CM, fake_bot.RELOC_CROWD_N) == (1000.0, 6)


def test_apply_puts_shipped_values_back_and_follows_a_reloaded_module(fake_bot, tmp_path):
    write(tmp_path, 'FAKE', {'*': {'fake_bot.RELOC_CROWD_N': 5}})
    T.apply('FAKE', None, {}, base=tmp_path)
    assert fake_bot.RELOC_CROWD_N == 5
    write(tmp_path, 'FAKE', {}, version='v2')
    T.apply('FAKE', None, {}, base=tmp_path)
    assert fake_bot.RELOC_CROWD_N == 6                               # dropped from the file: the shipped value
    fake_bot.RELOC_CROWD_N = 5                                       # a hot reload shipping a new default (5)
    write(tmp_path, 'FAKE', {}, version='v3')
    T.apply('FAKE', None, {}, base=tmp_path)
    assert fake_bot.RELOC_CROWD_N == 5                               # the new default is kept, not the old one
    (tmp_path / 'FAKE' / T.FILE).write_text('{broken')
    T._cache.clear()
    stats = {}
    assert T.apply('FAKE', None, stats, base=tmp_path) == {} and stats['tuning_version'] == 'shipped'


def test_stage_name_reads_a_drivers_index():
    assert T.stage_name(('Public Assembly', 'The Mines'), 1) == 'The Mines'
    assert T.stage_name(('Public Assembly',), 5) is None and T.stage_name(('Public Assembly',), None) is None


def test_steer_turns_a_relocation_off_a_learned_dead_end_and_notes_stops(fake_bot, tmp_path):
    write(tmp_path, 'FAKE', {}, avoid={'Village': [[0, 800, 250]]})
    T.apply('FAKE', 'Village', {}, base=tmp_path)
    assert T.steer('FAKE', (0, 0), 0.0, 800.0) == pytest.approx(math.radians(30))    # straight at the spot: turned
    assert T.steer('FAKE', (0, 0), math.pi / 2, 800.0) == math.pi / 2                # clear: unchanged
    T.note_dead_end('FAKE', (120.4, -33.0), base=tmp_path, now=5.0)
    assert json.loads((tmp_path / 'FAKE' / T.DEAD_ENDS).read_text()) == {'at': 5.0, 'stage': 'Village', 'x': 120,
                                                                         'z': -33}


# --- the tuner ---------------------------------------------------------------------------------------------------------

class Rounds:
    """A Notebook rounds table (the columns the learning loop reads)."""
    def __init__(self, root):
        path = Path(root) / 'mercs/curriculum' / TITLE
        path.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path / 'rounds.sqlite')
        self.db.execute('CREATE TABLE rounds(id TEXT PRIMARY KEY, ts REAL, stage TEXT, mode TEXT, character TEXT, '
                        'outcome TEXT, data TEXT, vector BLOB)')
        self.n = 0

    def add(self, ts, **observed):
        self.n += 1
        rid = f'{self.n:032x}'
        data = {'source_session_id': 's1', 'source_autoplay_job_id': 'job', **observed}
        self.db.execute('INSERT INTO rounds VALUES(?,?,?,?,?,?,?,NULL)',
                        (rid, ts, 'unknown', 'mercenaries', 'Chris', 'completed', json.dumps(data)))
        self.db.commit()


@pytest.fixture
def tuner(tmp_path):
    store = Store(tmp_path)
    clock = [15_000.0]                                                # after the first rounds, before the later ones
    learning = Learning(store, tmp_path, now=lambda: clock[0])
    t = TU.Tuner(store, tmp_path, learning, now=lambda: clock[0],
                 defaults=lambda name: {'re5_switch.RELOC_CROWD_N': 6, 're5_switch.HEAL_CRITICAL': 0.25,
                                        're5_switch.BEHIND_R': 300.0, 're5_switch_mines.BLAST_CM': 800.0}[name])
    yield store, t, Rounds(tmp_path), clock, learning
    store.db.close()


def hits(start, n_rounds, per_round, sig='crowd_4_in_2m'):
    """(labelled, round end times): `per_round` separate episodes of `sig` in each 60 s round from `start`."""
    out, ends = [], []
    for r in range(n_rounds):
        t0 = start + 61 * r
        for h in range(per_round):
            out.append(({'game_id': GAME, 'session_id': 's1', 'observed_at': t0 + 5 + 5 * h}, sig, True))
        ends.append(t0 + 60)
    return out, ends


def play(book, ends, stage=None, version=None, params=None):
    """Rounds ending at `ends`; with a version, rounds that ran the tuning hooks with `params` in force (tuning_params:
    a round confirms a numeric trial by the value it played, tuner.ran_with, not by the file's version)."""
    for ts in ends:
        extra = {'tuning_stage': stage} if stage else {}
        if version:
            extra.update(tuning_version=version, tuning_params=params or '')
        book.add(ts, **extra)


def test_a_rule_over_its_floor_steps_its_constant_and_a_confirmed_trial_is_kept(tuner):
    store, t, book, clock, learning = tuner
    before, ends = hits(10_000.0, 10, 2)                             # 2 crowd episodes per round
    play(book, ends, stage='The Mines')
    lines = t.tune(before, [])
    assert [(x['status'], x['param'], x['old'], x['new'], x['baseline']) for x in lines] == \
        [('trial', 're5_switch.RELOC_CROWD_N', None, 5, 2.0)]
    data = json.loads((t.base / TITLE / T.FILE).read_text())
    assert data['params'] == {'*': {'re5_switch.RELOC_CROWD_N': 5}}     # pooled over every stage (tuner.tune)
    version = data['version']
    assert t.tune(before, []) == []                                  # one trial at a time: it waits for its rounds
    after, ends2 = hits(20_000.0, 8, 1)                              # 1 per round with it
    # another write (an avoid trial) has moved the file's version on: the rounds still played the trial's value
    play(book, ends2, stage='The Mines', version='a-later-version', params='RELOC_CROWD_N=5')
    clock[0] = 25_000.0
    lines = t.tune(before + after, [])
    assert [(x['status'], x['after']) for x in lines] == [('kept', 1.0)]
    assert json.loads((t.base / TITLE / T.FILE).read_text())['params'] == {'*': {'re5_switch.RELOC_CROWD_N': 5}}
    assert [c['status'] for c in learning.changes(TITLE)] == ['trial', 'kept']
    assert len((t.base / TITLE / TU.LOG).read_text().splitlines()) == 2


def test_a_trial_that_makes_it_worse_is_reverted_and_left_alone(tuner):
    store, t, book, clock, learning = tuner
    before, ends = hits(10_000.0, 10, 2)
    play(book, ends)
    t.tune(before, [])
    version = json.loads((t.base / TITLE / T.FILE).read_text())['version']
    after, ends2 = hits(20_000.0, 8, 3)                              # worse with it
    play(book, ends2, version=version, params='RELOC_CROWD_N=5')
    clock[0] = 25_000.0
    lines = t.tune(before + after, [])
    assert [(x['status'], x['stage']) for x in lines] == [('reverted', '*')]
    assert json.loads((t.base / TITLE / T.FILE).read_text())['params'] == {}
    more, ends3 = hits(30_000.0, 10, 3)
    play(book, ends3)
    clock[0] = 31_000.0
    assert t.tune(before + after + more, []) == []                   # blocked BLOCK_S: no new trial of it


def test_a_trial_no_round_confirms_expires(tuner):
    store, t, book, clock, learning = tuner
    before, ends = hits(10_000.0, 10, 2)
    play(book, ends)
    t.tune(before, [])
    clock[0] += TU.EXPIRE_S + 1
    lines = t.tune(before, [])
    assert [x['status'] for x in lines] == ['expired']
    assert json.loads((t.base / TITLE / T.FILE).read_text())['params'] == {}


def test_dead_end_notes_become_an_avoid_spot_trial(tuner):
    store, t, book, clock, learning = tuner
    path = t.base / TITLE / T.DEAD_ENDS
    path.parent.mkdir(parents=True, exist_ok=True)
    # notes in the round-keyed format (tuning.STAGE_V: stage_v 2), and two older ones (named by the NEXT round's
    # target) in another cell that never become a spot
    path.write_text(''.join(json.dumps({'at': clock[0] - 60, 'stage': 'Village', 'x': 1000 + i, 'z': 500,
                                        'stage_v': 2}) + '\n' for i in range(3))
                    + json.dumps({'at': clock[0], 'stage': 'Village', 'x': 9000, 'z': 0, 'stage_v': 2}) + '\n'
                    + ''.join(json.dumps({'at': clock[0] - 30, 'stage': 'Village', 'x': -5000, 'z': -5000}) + '\n'
                              for _ in range(3)))
    _l, ends = hits(10_000.0, 10, 0)
    for ts in ends:
        book.add(ts, tuning_stage='Village', round_reloc_stuck=1)
    lines = t.tune([], [])
    assert [(x['status'], x['param']) for x in lines] == [('trial', 'avoid')]
    data = json.loads((t.base / TITLE / T.FILE).read_text())
    assert data['avoid'] == {'Village': [[1001, 500, TU.SPOT_R]]} and data['avoid_v'] == 2


# --- the operator's goal (tuner.OBJECTIVES: RE5 Switch No Mercy, gbox.mercs.ss_ledger) -----------------------------

def game_round(book, ts, outcome, kills, play_s, stage='1636-2187-d3a75164ca01dcaa-e1163f7867c9', params=None,
               version=None, breaks=4, max_combo=40):
    """One game round in the Notebook as the bot now writes it (its own round clock, ss_*)."""
    book.n += 1
    rid = f'{book.n:032x}'
    data = {'source_session_id': 's1', 'kills': kills, 'max_combo': max_combo, 'round_combo_breaks': breaks,
            'ss_round_play_s': play_s, 'ss_t0_kills': 0, 'ss_round_key': f'k{book.n}', 'score': kills * 1000}
    if version:
        data.update(tuning_version=version, tuning_params=params or '')
    book.db.execute('INSERT INTO rounds VALUES(?,?,?,?,?,?,?,NULL)',
                    (rid, ts, stage, 'mercenaries', 'Chris (BSAA)', outcome, json.dumps(data)))
    book.db.commit()


def start_trial(t, book, clock):
    """Ten rounds that died at ~100 kills in 5 minutes with two crowd episodes each: the crowd rule's trial starts."""
    before, ends = hits(10_000.0, 10, 2)
    for ts in ends:
        game_round(book, ts, 'died', 100, 300.0, version='shipped')
    lines = t.tune(before, [])
    assert [(x['status'], x['param']) for x in lines] == [('trial', 're5_switch.RELOC_CROWD_N')]
    trial = t.state()['titles'][TITLE]['stages']['*']['trial']
    assert trial['objective']['rounds'] == 10 and trial['objective']['deaths_rate'] == 1.0
    return before


def test_the_goal_judges_a_trial_and_keeps_what_brings_the_400_closer(tuner):
    store, t, book, clock, learning = tuner
    before = start_trial(t, book, clock)
    for i in range(TU.OBJ_EVAL_ROUNDS):                               # with it: rounds that reach 400
        game_round(book, 20_000.0 + 100 * i, 'completed', 400, 1300.0, params='RELOC_CROWD_N=5', version='other')
    clock[0] = 25_000.0
    lines = t.tune(before, [])
    assert [x['status'] for x in lines] == ['kept'] and lines[0]['after'] < 0.5
    assert 'the goal' in lines[0]['reason'] and f'{TU.OBJ_EVAL_ROUNDS} won' in lines[0]['reason']
    assert json.loads((t.base / TITLE / T.FILE).read_text())['params'] == {'*': {'re5_switch.RELOC_CROWD_N': 5}}


def test_the_goal_reverts_a_trial_that_dies_more(tuner):
    store, t, book, clock, learning = tuner
    before = start_trial(t, book, clock)
    for i in range(TU.OBJ_EVAL_ROUNDS):                               # with it: earlier deaths
        game_round(book, 20_000.0 + 100 * i, 'died', 30, 150.0, params='RELOC_CROWD_N=5', version='other')
    for i in range(3):                                                # rounds without the value do not count
        game_round(book, 21_000.0 + 100 * i, 'completed', 400, 1000.0, params='', version='other')
    clock[0] = 25_000.0
    lines = t.tune(before, [])
    assert [x['status'] for x in lines] == ['reverted'] and lines[0]['after'] > 1.1
    assert json.loads((t.base / TITLE / T.FILE).read_text())['params'] == {}
    assert t.state()['titles'][TITLE]['stages']['*']['blocked']['re5_switch.RELOC_CROWD_N'] > clock[0]


def test_the_goal_expires_a_trial_no_round_played(tuner):
    store, t, book, clock, learning = tuner
    before = start_trial(t, book, clock)
    for i in range(TU.OBJ_EXPIRE_ROUNDS):                             # the hooks not live: the shipped value played
        game_round(book, 20_000.0 + 100 * i, 'died', 100, 300.0, params='', version='other')
    clock[0] = 25_000.0
    lines = t.tune(before, [])
    assert [x['status'] for x in lines] == ['expired'] and 'game rounds played 5' in lines[0]['reason']


def test_ran_with_reads_the_value_a_round_played():
    assert TU.ran_with('HEAL_CRITICAL=0.3,RELOC_CROWD_N=5', 're5_switch.RELOC_CROWD_N', 5, 6)
    assert not TU.ran_with('HEAL_CRITICAL=0.3', 're5_switch.RELOC_CROWD_N', 5, 6)    # not listed: the shipped 6
    assert TU.ran_with('', 're5_switch.RELOC_CROWD_N', 6, 6)
    assert not TU.ran_with(None, 're5_switch.RELOC_CROWD_N', 6, 6)                  # no hooks ran
    assert T.in_force('BLAST_CM=900.0', 're5_switch_mines.BLAST_CM') == 900.0


def test_the_stage_key_migration_drops_what_was_learned_under_the_wrong_stage(tuner):
    store, t, book, clock, learning = tuner
    state = {'titles': {TITLE: {'overrides': {'*': {'re5_switch.RELOC_CROWD_N': 5},
                                              'Ship Deck': {'re5_switch_mines.BLAST_CM': 900.0}},
                                'avoid': {'Ship Deck': [[1232, 17199, 250.0]]},
                                'stages': {'Ship Deck': {'trial': {'param': 'avoid'}, 'blocked': {}}}}}}
    store.put(TU.STATE, 'state', state)
    _l, ends = hits(10_000.0, 3, 0)
    play(book, ends)
    lines = t.tune([], [])
    assert [x['status'] for x in lines] == ['migrated']
    data = json.loads((t.base / TITLE / T.FILE).read_text())
    assert data['params'] == {'*': {'re5_switch.RELOC_CROWD_N': 5}} and data['avoid'] == {} and data['avoid_v'] == 2
    ts = t.state()['titles'][TITLE]
    assert ts['stage_v'] == 2 and ts['stages']['Ship Deck']['trial'] is None
    assert t.tune([], []) == []                                      # once


def test_avoid_spots_of_an_older_stage_key_are_not_steered_by(tmp_path, monkeypatch):
    mod = types.ModuleType('gbox.mercs.titles.re5_switch_fake')
    monkeypatch.setitem(T.PARAMS, TITLE, {})
    write(tmp_path, TITLE, avoid={'Village': [[0, 800, 250]]})        # no avoid_v: made under the old key
    T.apply(TITLE, 'Village', {}, base=tmp_path)
    assert T.steer(TITLE, (0, 0), 0.0, 800.0) == 0.0
    path = Path(tmp_path) / TITLE / T.FILE
    data = json.loads(path.read_text())
    path.write_text(json.dumps(dict(data, avoid_v=2)))
    T._cache.clear()
    T.apply(TITLE, 'Village', {}, base=tmp_path)
    assert T.steer(TITLE, (0, 0), 0.0, 800.0) == pytest.approx(math.radians(30))
    T.note_dead_end(TITLE, (1.0, 2.0), base=tmp_path, now=1.0)
    assert json.loads((Path(tmp_path) / TITLE / T.DEAD_ENDS).read_text())['stage_v'] == 2
    T._state.pop(TITLE, None)


def test_the_blast_standoff_is_never_tuned_under_the_operators_15_m():
    low, high, step = T.PARAMS[TITLE]['re5_switch_mines.BLAST_CM']
    assert low >= 1500.0 and step > 0 and T.clamp(TITLE, 're5_switch_mines.BLAST_CM', 900.0) == 1500.0
