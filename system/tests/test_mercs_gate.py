"""Keep or revert a bot code change by its play (gbox/mercs/gate.py): score, kills per minute, deaths, bonuses over the
title's rounds after the change against those before; a clear loss reverts the agent PR that brought it (or flags a
human), a clear gain notes the effect on the batch tickets it answered."""
import json
from pathlib import Path
import sqlite3
import subprocess

import pytest

from gbox.mercs import damage_clusters as C, gate as G
from gbox.mercs.learning import CHANGE, Learning
from gbox.store import Store

TITLE, GAME = '010018100CD46000', '52d15709be0fda1a'
DRIVER = 'system/gbox/mercs/titles/re5_switch.py'


class Rounds:
    def __init__(self, root):
        path = Path(root) / 'mercs/curriculum' / TITLE
        path.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path / 'rounds.sqlite')
        self.db.execute('CREATE TABLE rounds(id TEXT PRIMARY KEY, ts REAL, stage TEXT, mode TEXT, character TEXT, '
                        'outcome TEXT, data TEXT, vector BLOB)')
        self.n = 0

    def play(self, start, n, score, kills=40, died=0, seconds=120.0):
        """n rounds 130 s apart from `start`, the first `died` of them deaths."""
        for i in range(n):
            self.n += 1
            data = {'source_session_id': 's', 'score': score + 50 * (i % 3), 'kills': kills, 'round_t_aim': seconds / 2,
                    'round_t_fire': seconds / 2, 'round_bonuses_taken': 1}
            self.db.execute('INSERT INTO rounds VALUES(?,?,?,?,?,?,?,NULL)',
                            (f'{self.n:032x}', start + 130 * i, 'unknown', 'mercenaries', 'Chris',
                             'died' if i < died else 'completed', json.dumps(data)))
        self.db.commit()
        return start + 130 * n


class FakeGitHub:
    def __init__(self, prs):
        self.prs, self.reverted, self.windows = prs, [], []

    def prs_between(self, prefix, since, until):
        self.windows.append((prefix, since, until))
        return list(self.prs)

    def pr(self, number):
        return self.prs[number]

    def revert(self, pr, reason):
        self.reverted.append((pr['number'], reason))
        return 9001


def agent_pr(number, files=(DRIVER, 'system/tests/test_re5_switch.py'), body='fix\n\n🤖 Generated with [Claude Code](x)'):
    return {'number': number, 'title': f'RE5 change {number}', 'body': body, 'head': f'branch-{number}',
            'merge_commit_sha': 'a' * 40, 'merged_at': '2026-10-27T20:00:00Z', 'files': list(files)}


@pytest.fixture
def world(tmp_path):
    store = Store(tmp_path)
    clock = [100_000.0]
    learning = Learning(store, tmp_path, now=lambda: clock[0])
    yield store, learning, Rounds(tmp_path), clock
    store.db.close()


def change(learning, at, kind='reload'):
    return learning.record({'kind': kind, 'title': TITLE, 'at': at, 'modules': ['gbox.mercs.titles.re5_switch'],
                            'source': f'job-{at}'})


def batch_ticket(store, number, completed):
    store.put('request', f'b{number}', {'id': f'b{number}', 'number': number, 'source': C.SOURCE, 'status': 'done',
                                        'completed': completed, 'context': {'game_id': GAME}, 'messages': []})


def test_judge_reads_a_clear_loss_a_clear_gain_and_no_change():
    def base(score, deaths=0, n=10, kpm=20.0, median=None):
        return {'rounds': n, 'score': score, 'score_median': median if median is not None else score, 'kpm': kpm,
                'deaths_per_round': deaths / n, 'deaths': deaths}
    s = lambda *a, **k: dict(base(*a, **k), values={'score': [], 'kpm': [], 'died': []})
    def sure(b, a):              # every round at its mean: any difference is significant
        fill = lambda x: dict(x, values={'score': [x['score']] * 10, 'kpm': [x['kpm']] * 10,
                                         'died': [1.0] * x['deaths'] + [0.0] * (10 - x['deaths'])})
        return fill(b), fill(a)
    assert G.judge(*sure(s(20000), s(17000)))[0] == 'worse'          # -15% mean and median, every round
    assert G.judge(*sure(s(20000), s(17000, median=19500)))[0] == 'kept'   # one outlier round is not a clear loss
    assert G.judge(*sure(s(20000, deaths=1), s(20000, deaths=7)))[0] == 'worse'
    assert G.judge(*sure(s(20000, deaths=2), s(20000, deaths=6)))[0] == 'kept'   # p 0.08: chance explains it
    assert G.judge(*sure(s(20000, deaths=0), s(20000, deaths=1)))[0] == 'kept'   # one death more is not 2 more
    assert G.judge(*sure(s(20000), s(23000)))[0] == 'better'
    assert G.judge(*sure(s(20000, kpm=20.0), s(20000, kpm=23.0)))[0] == 'better'
    assert G.judge(*sure(s(20000), s(20500)))[0] == 'kept'
    assert G.judge(s(20000), s(10000, n=5))[0] == 'pending'
    # the same means from scattered rounds are not significant: a loss that chance explains is not "worse"
    noisy_b = dict(s(20000), values={'score': [5000, 35000] * 5, 'kpm': [], 'died': []})
    noisy_a = dict(s(17000), values={'score': [2000, 32000] * 5, 'kpm': [], 'died': []})
    assert G.judge(noisy_b, noisy_a)[0] == 'kept'
    assert G.p_lower([10] * 10, [5] * 10) < 0.01 and G.p_lower([5] * 10, [10] * 10) > 0.5


def test_round_metrics_count_minutes_played_from_the_decision_timers(world):
    store, learning, book, clock = world
    book.play(1000.0, 1, 30000, kills=60, seconds=120.0)
    m = G.round_metrics(learning.rounds(TITLE)[0])
    assert (m['score'], m['kills'], m['kpm'], m['died'], m['bonuses']) == (30000.0, 60.0, 30.0, 0.0, 1.0)


def test_a_clear_loss_reverts_the_one_agent_pr_and_reopens_its_tickets(world):
    store, learning, book, clock = world
    t = book.play(10_000.0, 10, 30000)
    cid = change(learning, t)
    batch_ticket(store, 77, t - 3600)                              # closed by that fix an hour before it went live
    book.play(t + 10, 10, 24000, died=3)
    clock[0] = t + 5000
    gh = FakeGitHub({41: agent_pr(41)})
    decided = G.Gate(store, learning, github=gh, now=lambda: clock[0]).poll()
    assert decided == [(cid, 'reverted')] and [n for n, _r in gh.reverted] == [41]
    assert gh.windows[0][0] == G.DRIVERS[TITLE]
    gate = store.get(CHANGE, cid)['gate']
    assert gate['reverted_pr'] == 41 and gate['revert_pr'] == 9001 and gate['reopened'] == [77]
    assert gate['before']['score'] > gate['after']['score']
    req = store.get('request', 'b77')
    assert req['status'] == 'open' and req['messages'][-1]['text'].startswith('Reopened: #41 made RE5 Switch play worse')
    assert G.Gate(store, learning, github=gh, now=lambda: clock[0]).poll() == []    # decided once
    assert G.Gate(store, learning, github=gh).decisions(TITLE)[0]['state'] == 'reverted'


@pytest.mark.parametrize('prs,why', [
    ({41: agent_pr(41, body='an operator change')}, 'operator'),
    ({41: agent_pr(41, files=(DRIVER, 'system/gbox/server.py'))}, 'server or core files'),
    ({41: agent_pr(41), 42: agent_pr(42)}, '2 PRs'),
    ({}, 'no PR found'),
])
def test_anything_but_one_agent_driver_pr_is_flagged_for_a_human(world, prs, why):
    store, learning, book, clock = world
    t = book.play(10_000.0, 10, 30000)
    cid = change(learning, t)
    book.play(t + 10, 10, 24000)
    clock[0] = t + 5000
    gh = FakeGitHub(prs)
    assert G.Gate(store, learning, github=gh, now=lambda: clock[0]).poll() == [(cid, 'flagged')]
    assert gh.reverted == []
    gate = store.get(CHANGE, cid)['gate']
    assert why in gate['flag']
    flag = next(r for r in store.all('request') if r['source'] == 'mercs_learning_gate')
    assert flag['number'] == gate['request'] and 'worse' in flag['title'] and why in flag['body']


def test_a_second_revert_of_a_title_within_a_day_goes_to_a_human(world):
    store, learning, book, clock = world
    t = book.play(10_000.0, 30, 30000)
    cid = change(learning, t)
    t2 = book.play(t + 10, 30, 24000)
    cid2 = change(learning, t2)
    book.play(t2 + 10, 10, 18000)
    clock[0] = t2 + 5000
    gh = FakeGitHub({41: agent_pr(41)})
    decided = dict(G.Gate(store, learning, github=gh, now=lambda: clock[0]).poll())
    assert decided == {cid: 'reverted', cid2: 'flagged'} and len(gh.reverted) == 1
    assert 'at most one a day' in store.get(CHANGE, cid2)['gate']['flag']


def test_a_probable_loss_is_flagged_not_reverted(world, monkeypatch):
    store, learning, book, clock = world
    monkeypatch.setattr(G, 'P_REVERT', 0.0)                          # nothing is clear enough to undo by itself
    t = book.play(10_000.0, 10, 30000)
    cid = change(learning, t)
    book.play(t + 10, 10, 24000)
    clock[0] = t + 5000
    gh = FakeGitHub({41: agent_pr(41)})
    assert G.Gate(store, learning, github=gh, now=lambda: clock[0]).poll() == [(cid, 'flagged')]
    assert gh.reverted == [] and 'not clear enough' in store.get(CHANGE, cid)['gate']['flag']


def test_a_failed_revert_is_flagged_and_auto_revert_can_be_switched_off(world):
    store, learning, book, clock = world
    t = book.play(10_000.0, 10, 30000)
    cid = change(learning, t)
    book.play(t + 10, 10, 24000)
    clock[0] = t + 5000

    class Broken(FakeGitHub):
        def revert(self, pr, reason):
            raise RuntimeError('push rejected')
    assert G.Gate(store, learning, github=Broken({41: agent_pr(41)}), now=lambda: clock[0]).poll() == \
        [(cid, 'revert_failed')]
    t2 = book.play(t + 2000, 10, 30000)
    cid2 = change(learning, t2)
    book.play(t2 + 10, 10, 24000)
    clock[0] = t2 + 5000
    gh = FakeGitHub({43: agent_pr(43)})
    assert (cid2, 'flagged') in G.Gate(store, learning, github=gh, now=lambda: clock[0], auto_revert=False).poll()
    assert gh.reverted == []


def test_a_clear_gain_notes_its_tickets_and_a_change_too_soon_after_another_is_confounded(world):
    store, learning, book, clock = world
    t = book.play(10_000.0, 10, 30000)
    cid = change(learning, t)
    batch_ticket(store, 78, t - 600)
    t2 = book.play(t + 10, 10, 36000)
    cid2 = change(learning, t2)                                    # a second change, followed by only 3 rounds
    book.play(t2 + 10, 3, 36000)
    cid3 = change(learning, t2 + 500)
    clock[0] = t2 + 2000
    decided = dict(G.Gate(store, learning, github=FakeGitHub({}), now=lambda: clock[0]).poll())
    assert decided == {cid: 'better', cid2: 'confounded'} and cid3 not in decided   # the last one still measuring
    req = store.get('request', 'b78')
    assert req['status'] == 'done' and req['messages'][-1]['text'].startswith('Effect measured: kept - score 30045 -> 36045')


def test_the_revert_is_a_revert_pr_of_the_merge_commit_merged_on_main(tmp_path):
    calls = []

    def run(args, **kw):
        calls.append(args)
        out = ''
        if args[:2] == ['git', 'rev-list']:
            out = 'merge parent1 parent2\n'
        elif args[:3] == ['gh', 'pr', 'create']:
            out = 'https://github.com/teamcsharp/gBox/pull/1500\n'
        return subprocess.CompletedProcess(args, 0, out, '')
    gh = G.GitHub(clone=tmp_path, run=run)
    assert gh.revert(agent_pr(41), 'reason') == 1500
    revert = next(c for c in calls if 'revert' in c)
    assert revert[-3:] == ['-m', '1', 'a' * 40]
    assert ['git', 'push', '-q', '-u', 'origin', G.REVERT_BRANCH + '41'] in calls
    assert any(c[:3] == ['gh', 'pr', 'merge'] and c[3] == '1500' and '--merge' in c for c in calls)
    assert G.revertable(dict(agent_pr(41), head=G.REVERT_BRANCH + '7'), TITLE)[0] is False   # never revert a revert
