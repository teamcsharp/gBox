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


def play(book, ends, stage=None, version=None):
    for ts in ends:
        extra = {'tuning_stage': stage} if stage else {}
        if version:
            extra['tuning_version'] = version
        book.add(ts, **extra)


def test_a_rule_over_its_floor_steps_its_constant_and_a_confirmed_trial_is_kept(tuner):
    store, t, book, clock, learning = tuner
    before, ends = hits(10_000.0, 10, 2)                             # 2 crowd episodes per round
    play(book, ends, stage='The Mines')
    lines = t.tune(before, [])
    assert [(x['status'], x['param'], x['old'], x['new'], x['baseline']) for x in lines] == \
        [('trial', 're5_switch.RELOC_CROWD_N', None, 5, 2.0)]
    data = json.loads((t.base / TITLE / T.FILE).read_text())
    assert data['params'] == {'The Mines': {'re5_switch.RELOC_CROWD_N': 5}}
    version = data['version']
    assert t.tune(before, []) == []                                  # one trial per stage: it waits for its rounds
    after, ends2 = hits(20_000.0, 8, 1)                              # 1 per round with it
    play(book, ends2, stage='The Mines', version=version)
    clock[0] = 25_000.0
    lines = t.tune(before + after, [])
    assert [(x['status'], x['after']) for x in lines] == [('kept', 1.0)]
    assert json.loads((t.base / TITLE / T.FILE).read_text())['params'] == {'The Mines': {'re5_switch.RELOC_CROWD_N': 5}}
    assert [c['status'] for c in learning.changes(TITLE)] == ['trial', 'kept']
    assert len((t.base / TITLE / TU.LOG).read_text().splitlines()) == 2


def test_a_trial_that_makes_it_worse_is_reverted_and_left_alone(tuner):
    store, t, book, clock, learning = tuner
    before, ends = hits(10_000.0, 10, 2)
    play(book, ends)
    t.tune(before, [])
    version = json.loads((t.base / TITLE / T.FILE).read_text())['version']
    after, ends2 = hits(20_000.0, 8, 3)                              # worse with it
    play(book, ends2, version=version)
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
    path.write_text(''.join(json.dumps({'at': clock[0] - 60, 'stage': 'Village', 'x': 1000 + i, 'z': 500})
                            + '\n' for i in range(3)) + json.dumps({'at': clock[0], 'stage': 'Village', 'x': 9000,
                                                                     'z': 0}) + '\n')
    _l, ends = hits(10_000.0, 10, 0)
    for ts in ends:
        book.add(ts, tuning_stage='Village', round_reloc_stuck=1)
    lines = t.tune([], [])
    assert [(x['status'], x['param']) for x in lines] == [('trial', 'avoid')]
    assert json.loads((t.base / TITLE / T.FILE).read_text())['avoid'] == {'Village': [[1001, 500, TU.SPOT_R]]}
