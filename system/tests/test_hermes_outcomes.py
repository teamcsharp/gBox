"""Ticket outcomes Hermes reports back: branches vs main, the run cap, and task leftovers (#1300)."""
import json
import os
import subprocess
import time

import pytest
from fastapi.testclient import TestClient

from gbox import hermes_delivery, hermes_merges, hermes_summaries
from gbox.server import create_app

URL = 'https://github.com/teamcsharp/gBox/pull/'


class Inbox:
    def __init__(self, reports=None):
        self.reports, self.posts, self.statuses = reports or {}, [], []

    def __call__(self, path, body=None):
        if path.startswith('/api/requests?'):
            return list(self.reports.values())
        rid = path.split('/')[3]
        if body is None:
            return self.reports[rid]
        if path.endswith('/status'):
            self.statuses.append((rid, body))
            self.reports[rid]['status'] = body['status']
            return {'ok': True}
        self.posts.append((rid, body))
        return {'ok': True}


class FakeBranches:
    def __init__(self, heads, pending, pulls=None):
        self._heads, self._pending, self._pulls = heads, pending, pulls or {}
        self.opened, self.refreshed = [], 0

    def refresh(self):
        self.refreshed += 1

    def heads(self):
        return self._heads

    def pending(self, sha):
        return self._pending.get(sha, [])

    def pulls(self):
        return self._pulls

    def open_pull(self, branch, record, pending):
        self.opened.append((branch, [sha for sha, _ in pending]))
        number = 40 + len(self.opened)
        # GitHub lists the new PR from now on, as the real `gh pr list` would.
        self._pulls.setdefault(branch, []).append({'number': number, 'state': 'OPEN', 'headRefOid': pending[-1][0]})
        return {'number': number, 'url': URL + str(number)}


def _records(tmp_path, monkeypatch, *records):
    monkeypatch.setenv('GBOX_HERMES_DISPATCH_STATE', str(tmp_path))
    for record in records:
        (tmp_path / (record['request_id'] + '.json')).write_text(json.dumps(record))


A, B, C, D, E = ('a' * 16, 'b' * 16, 'c' * 16, 'd' * 16, 'e' * 16)


def test_branch_pass_reports_main_recovers_stranded_and_respects_closed_or_busy(tmp_path, monkeypatch):
    now = 1_000_000.0
    _records(tmp_path, monkeypatch,
             {'request_id': A, 'number': 1275, 'branch': 'hermes/request-1275-1', 'baseline': 'base'},
             {'request_id': B, 'number': 1296, 'branch': 'hermes/request-1296-1', 'baseline': 'base'},
             {'request_id': C, 'number': 1300, 'branch': 'hermes/request-1300-1', 'baseline': 'base'},
             {'request_id': D, 'number': 1301, 'branch': 'hermes/request-1301-1', 'baseline': 'base'},
             {'request_id': E, 'number': 1302, 'branch': 'hermes/request-1302-1', 'baseline': 'base'})
    old = now - 7200
    branches = FakeBranches(
        heads={'hermes/request-1275-1': ('late', old),         # pushed after its PR merged
               'hermes/request-1296-1': ('reworked', old),     # PR closed: an integration PR reworked it
               'hermes/request-1300-1': ('merged', old),       # everything on main
               'hermes/request-1301-1': ('base', old),         # prepared, never changed
               'hermes/request-1302-1': ('busy', old)},        # stranded, but its run is still active
        pending={'late': [('late', 'NaomiLib GLB export')], 'reworked': [('reworked', 'Reconnect')],
                 'busy': [('busy', 'work in progress')]},
        pulls={'hermes/request-1296-1': [{'number': 25, 'state': 'CLOSED', 'headRefOid': 'reworked'}],
               'hermes/request-1275-1': [{'number': 14, 'state': 'MERGED', 'headRefOid': 'earlier'}]})
    inbox = Inbox()
    out = hermes_merges.reconcile_branches(inbox, branches=branches, busy=lambda: {E}, now=now)
    texts = {rid: body['text'] for rid, body in inbox.posts}
    assert branches.opened == [('hermes/request-1275-1', ['late'])]
    assert out['recovered'] == [{'request_id': A, 'number': 1275, 'pr': 41}]
    assert 'Opened draft PR #41' in texts[A] and 'late NaomiLib GLB export' in texts[A]
    assert texts[C].startswith('All published work for this ticket is on main')
    assert set(texts) == {A, C} and out['errors'] == []

    # Inside the interval nothing runs; a forced pass repeats nothing already reported,
    # and the busy ticket is recovered once its run has ended.
    assert hermes_merges.reconcile_branches(inbox, branches=branches, busy=set, now=now + 60) == {'skipped': 'interval'}
    again = hermes_merges.reconcile_branches(inbox, branches=branches, busy=set, now=now + 60, force=True)
    assert [r['request_id'] for r in again['recovered']] == [E] and len(inbox.posts) == 3


def test_stranded_work_waits_for_grace_period_and_known_ownership(tmp_path, monkeypatch):
    now = 1_000_000.0
    _records(tmp_path, monkeypatch, {'request_id': A, 'number': 1, 'branch': 'hermes/x', 'baseline': 'base'})
    fresh = FakeBranches({'hermes/x': ('new', now - 60)}, {'new': [('new', 'just pushed')]})
    inbox = Inbox()
    assert hermes_merges.reconcile_branches(inbox, branches=fresh, busy=set, now=now)['recovered'] == []

    def unknown():
        raise RuntimeError('executions database locked')

    stale = FakeBranches({'hermes/x': ('new', now - 7200)}, {'new': [('new', 'old enough')]})
    assert hermes_merges.reconcile_branches(inbox, branches=stale, busy=unknown, now=now, force=True)['recovered'] == []
    assert fresh.opened == stale.opened == [] and inbox.posts == []
    # An open review PR is left to the PR notices: nothing is posted or opened.
    review = FakeBranches({'hermes/x': ('new', now - 7200)}, {'new': [('new', 'x')]},
                          {'hermes/x': [{'number': 31, 'state': 'OPEN', 'headRefOid': 'new'}]})
    assert hermes_merges.reconcile_branches(inbox, branches=review, busy=set, now=now, force=True)['posted'] == []
    assert review.opened == []


def test_no_hermes_repository_is_a_quiet_skip(tmp_path, monkeypatch):
    monkeypatch.setenv('GBOX_HERMES_DISPATCH_STATE', str(tmp_path))
    monkeypatch.setenv('GBOX_HERMES_REPO', str(tmp_path / 'missing'))
    assert hermes_merges.reconcile_branches(Inbox(), now=1.0e6) == {'skipped': 'no_repository'}


def _git(cwd, *args):
    return subprocess.run(['git', *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def test_real_git_counts_rebased_work_as_on_main(tmp_path):
    repo = tmp_path / 'repo'
    repo.mkdir()
    _git(repo, 'init', '-q', '-b', 'main')
    _git(repo, 'config', 'user.email', 't@t'); _git(repo, 'config', 'user.name', 't')
    (repo / 'a.txt').write_text('one\n'); _git(repo, 'add', '.'); _git(repo, 'commit', '-qm', 'base')
    _git(repo, 'switch', '-qc', 'task')
    (repo / 'b.txt').write_text('fix\n'); _git(repo, 'add', '.'); _git(repo, 'commit', '-qm', 'the fix')
    (repo / 'c.txt').write_text('late\n'); _git(repo, 'add', '.'); _git(repo, 'commit', '-qm', 'late commit')
    task = _git(repo, 'rev-parse', 'HEAD')
    _git(repo, 'switch', '-q', 'main')
    (repo / 'm.txt').write_text('main moved\n'); _git(repo, 'add', '.'); _git(repo, 'commit', '-qm', 'main moved')
    _git(repo, 'cherry-pick', task + '~1')          # the fix lands on main through a rebased copy
    _git(repo, 'update-ref', 'refs/remotes/origin/main', 'main')
    pending = hermes_merges.Branches(repo).pending(task)
    assert [subject for _, subject in pending] == ['late commit']


def test_cap_blocks_once_per_streak_with_a_question(_dispatch_state):
    runs = [{'id': f'run{i}', 'name': 'gBox inbox task mode', 'state': 'completed', 'started': 100.0 + i,
             'request_ids': [A]} for i in range(3)]
    inbox = Inbox({A: {'id': A, 'status': 'in_progress', 'messages': [{'author': 'operator', 'ts': 50.0}]}})
    out = hermes_summaries.enforce_cap(inbox, runs=runs)
    assert out == {'blocked': [{'request_id': A, 'runs': 3}], 'errors': []}
    rid, body = inbox.statuses[0]
    assert rid == A and body['status'] == 'blocked' and 'Reply on this ticket' in body['note']
    inbox.reports[A]['status'] = 'in_progress'        # e.g. a run set it back while finishing
    assert hermes_summaries.enforce_cap(inbox, runs=runs)['blocked'] == []
    # An operator message after the streak restarts the count.
    inbox.reports[A]['messages'].append({'author': 'operator', 'ts': 500.0})
    assert hermes_summaries.enforce_cap(inbox, runs=runs)['blocked'] == []


@pytest.fixture
def _dispatch_state(tmp_path, monkeypatch):
    monkeypatch.setenv('GBOX_HERMES_DISPATCH_STATE', str(tmp_path / 'dispatch'))


def test_operator_reply_reopens_a_blocked_request(cfg, _dispatch_state):
    app = create_app(cfg)
    client = TestClient(app, headers={'Authorization': f'Bearer {cfg.token()}'})
    rid = client.post('/api/requests', json={'title': 'Fix the swap', 'body': 'Fix the swap'}).json()['id']
    client.post(f'/api/requests/{rid}/status', json={'status': 'blocked', 'note': 'What next?'})
    assert client.post(f'/api/requests/{rid}/messages', json={'author': 'agent', 'text': 'still waiting'}).json()['status'] == 'blocked'
    assert client.post(f'/api/requests/{rid}/messages', json={'author': 'operator', 'text': 'keep going'}).json()['status'] == 'open'


@pytest.mark.skipif(os.name == 'nt', reason='reads a Linux /proc layout')
def test_reaper_stops_only_old_unowned_task_processes(tmp_path, monkeypatch):
    monkeypatch.setenv('GBOX_HERMES_REPO', str(tmp_path / 'gbox-hermes-repo'))
    tasks = tmp_path / 'gbox-hermes-tasks'
    proc = tmp_path / 'proc'
    proc.mkdir()
    ticks = os.sysconf('SC_CLK_TCK')
    (proc / 'stat').write_text('cpu 0\nbtime 1000\n')
    now = 1000 + 10 * 3600

    def process(pid, cwd, started_hours, name='python3 (http)'):
        entry = proc / str(pid)
        entry.mkdir()
        cwd.mkdir(parents=True, exist_ok=True)
        os.symlink(cwd, entry / 'cwd')
        fields = ['S'] + ['0'] * 18 + [str(int(started_hours * 3600 * ticks))]
        (entry / 'stat').write_text(f'{pid} ({name}) ' + ' '.join(fields))
        (entry / 'cmdline').write_bytes(b'python3\0-m\0http.server\08124\0')

    process(101, tasks / A / 'system', 1)        # 9 h old, unowned: stopped
    process(102, tasks / B, 1)                   # owned by an active run: kept
    process(103, tasks / C, 9)                   # 1 h old: kept
    process(104, tmp_path / 'elsewhere', 1)      # not a task workspace: kept
    killed = []
    stopped = hermes_delivery.reap_task_processes(lambda: {B}, proc=proc, now=now,
                                                  kill=lambda pid, sig: killed.append(pid))
    assert killed == [101] and stopped[0]['request_id'] == A and 'http.server' in stopped[0]['command']

    def unknown():
        raise RuntimeError('locked')

    assert hermes_delivery.reap_task_processes(unknown, proc=proc, now=now, kill=lambda *a: killed.append(a)) == []
    assert killed == [101]
