import json

from gbox import hermes_merges

URL = 'https://github.com/teamcsharp/gBox/pull/'


def _setup(tmp_path, monkeypatch, records):
    monkeypatch.setenv('GBOX_HERMES_DISPATCH_STATE', str(tmp_path))
    for record in records:
        (tmp_path / (record['request_id'] + '.json')).write_text(json.dumps(record))


class Inbox:
    def __init__(self, reports):
        self.reports = reports
        self.posts = []

    def __call__(self, path, body=None):
        rid = path.split('/')[3]
        if body is None:
            return self.reports[rid]
        self.reports[rid]['messages'].append(body)
        self.posts.append((rid, body))
        return {'ok': True}


def _published(n):
    return {'author': 'agent', 'text': f'Published tested task changes: {URL}{n}\nCommit: abc'}


PULLS = {
    14: {'number': 14, 'state': 'MERGED', 'mergedAt': '2026-10-11T17:17:37Z', 'baseRefName': 'main',
         'mergeCommit': {'oid': 'aaaabbbbccccdddd'}, 'headRefOid': 'old-head'},
    25: {'number': 25, 'state': 'CLOSED', 'closedAt': '2026-10-11T20:00:00Z', 'baseRefName': 'main'},
    31: {'number': 31, 'state': 'OPEN', 'baseRefName': 'main'},
}


def test_merged_closed_and_open_prs_are_reported_once(tmp_path, monkeypatch):
    a, b = '70a52a0bb87a4998', '95038303b9f449d1'
    _setup(tmp_path, monkeypatch, [
        # #1275: a commit pushed after PR #14 merged never reached main.
        # Older delivery records only have the URL.
        {'request_id': a, 'number': 1275, 'url': URL + '14', 'commit': 'f6e0a2e000000000'},
        {'request_id': b, 'number': 1296, 'pr_number': 31, 'commit': 'c31'},
    ])
    inbox = Inbox({a: {'number': 1275, 'messages': [_published(14)]},
                   b: {'number': 1296, 'messages': [_published(25), _published(31)]}})
    asked = []

    def gh(n):
        asked.append(n)
        return PULLS[n]

    out = hermes_merges.reconcile(inbox, gh=gh, now=1000.0, carriers=lambda sha: [])
    texts = {rid: body['text'] for rid, body in inbox.posts}
    assert sorted((p['pr'], p['state']) for p in out['posted']) == [(14, 'MERGED'), (25, 'CLOSED')]
    assert out['open'] == 1 and out['errors'] == []
    assert texts[a].startswith('PR #14 merged to main as aaaabbbbcccc at 2026-10-11 17:17:37 UTC.')
    assert 'f6e0a2e00000' in texts[a] and 'NOT on main and no open PR carries it' in texts[a]
    assert texts[b].startswith('PR #25 closed without merge')
    assert all(body['task_step']['status'] == 'finished' for _, body in inbox.posts)

    # Inside the interval nothing runs; a forced second pass posts nothing new
    # and only re-asks GitHub about the still-open PR.
    assert hermes_merges.reconcile(inbox, gh=gh, now=1100.0) == {'skipped': 'interval'}
    asked.clear()
    again = hermes_merges.reconcile(inbox, gh=gh, now=1100.0, force=True)
    assert again['posted'] == [] and len(inbox.posts) == 2 and asked == [31]


def test_notice_already_on_ticket_is_not_repeated_without_saved_state(tmp_path, monkeypatch):
    rid = '35cf46f5ba864323'
    _setup(tmp_path, monkeypatch, [{'request_id': rid, 'number': 1294, 'pr_number': 31, 'commit': 'head'}])
    inbox = Inbox({rid: {'number': 1294, 'messages': [
        _published(31), {'author': 'agent', 'text': 'PR #31 merged to main as 123 at x.'}]}})

    def gh(n):
        raise AssertionError('a reported PR must not be queried again')

    assert hermes_merges.reconcile(inbox, gh=gh, now=5000.0)['posted'] == []
    assert inbox.posts == []


def test_merged_exact_head_has_no_lost_commit_warning_and_errors_do_not_stop_others(tmp_path, monkeypatch):
    a, b = 'aaaaaaaaaaaaaaaa', 'bbbbbbbbbbbbbbbb'
    _setup(tmp_path, monkeypatch, [{'request_id': a, 'number': 1, 'pr_number': 14, 'commit': 'old-head'},
                                   {'request_id': b, 'number': 2, 'pr_number': 99, 'commit': 'x'}])
    inbox = Inbox({a: {'messages': []}, b: {'messages': []}})

    def gh(n):
        if n == 99:
            raise RuntimeError('gh pr view 99 failed (exit 1)')
        return PULLS[n]

    out = hermes_merges.reconcile(inbox, gh=gh, now=1.0e6)
    assert [p['pr'] for p in out['posted']] == [14] and out['errors'] == ['#99: gh pr view 99 failed (exit 1)']
    assert 'NOT on main' not in inbox.posts[0][1]['text']


def test_late_commit_names_the_pr_that_carried_it():
    pull = PULLS[14]
    record = {'pr_number': 14, 'commit': 'f6e0a2e48b52aaaa'}
    on_main = hermes_merges.notice(pull, record, lambda sha: [
        {'number': 14, 'state': 'closed', 'merged_at': 'x'}, {'number': 19, 'state': 'closed', 'merged_at': 'y'}])
    assert on_main.endswith('reached main through PR #19.')
    waiting = hermes_merges.notice(pull, record, lambda sha: [{'number': 30, 'state': 'open', 'merged_at': None}])
    assert 'waiting in open PR #30' in waiting and 'not on main yet' in waiting

    def broken(sha):
        raise RuntimeError('offline')

    assert 'check whether it reached main' in hermes_merges.notice(pull, record, broken)
    assert hermes_merges.notice(PULLS[31], record) is None
