import datetime as dt
import json
import os
import sqlite3

from gbox import hermes_summaries, hermes_tasks

TZ = dt.timezone(dt.timedelta(hours=-6))
T0 = dt.datetime(2026, 10, 11, 12, 0, tzinfo=TZ).timestamp()
RID, OTHER = '82f7608d4e994f88', 'deb329da9ffd4dcf'


def _iso(ts):
    return dt.datetime.fromtimestamp(ts, TZ).isoformat()


def _home(tmp_path, runs):
    """runs: [(run_id, status, started, finished, error, response, tickets)]"""
    (tmp_path / 'cron/output/job1').mkdir(parents=True)
    ex = sqlite3.connect(tmp_path / 'cron/executions.db')
    ex.execute('CREATE TABLE executions (id TEXT, job_id TEXT, status TEXT, started_at TEXT, finished_at TEXT, error TEXT)')
    st = sqlite3.connect(tmp_path / 'state.db')
    st.execute('CREATE TABLE sessions (id TEXT, source TEXT, started_at REAL, model TEXT, billing_provider TEXT,'
               ' input_tokens INT, output_tokens INT)')
    st.execute('CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT,'
               ' tool_name TEXT, tool_calls TEXT, tool_call_id TEXT)')
    owned = {}
    for run_id, status, started, finished, error, response, tickets in runs:
        ex.execute('INSERT INTO executions VALUES (?,?,?,?,?,?)',
                   (run_id, 'job1', status, _iso(started), finished and _iso(finished), error))
        sid = f'cron_job1_{run_id[:6]}'
        if not response:
            continue   # maintenance scripts have no conversation
        st.execute("INSERT INTO sessions VALUES (?, 'cron', ?, 'anthropic/claude-opus-5.5', 'openrouter', 0, 0)",
                   (sid, started + 2))
        for n in range(3):
            st.execute("INSERT INTO messages (session_id, role, content, tool_name) VALUES (?, 'tool', '{}', 'x')", (sid,))
        st.execute("INSERT INTO messages (session_id, role, content) VALUES (?, 'assistant', ?)", (sid, response))
        owned[sid] = tickets
        if finished and response:
            out = tmp_path / 'cron/output/job1' / f'{run_id}.md'
            out.write_text('# Cron Job\n\n## Prompt\nwork\n\n## Response\n\n' + response)
            os.utime(out, (finished, finished))
    ex.commit(); st.commit(); ex.close(); st.close()
    return owned


class Inbox:
    def __init__(self, reports):
        self.reports, self.posts = reports, []

    def __call__(self, path, body=None):
        rid = path.split('/')[3]
        if body is None:
            return json.loads(json.dumps(self.reports[rid]))
        self.reports[rid]['messages'].append(body)
        self.posts.append((rid, body['text']))
        return {'ok': True}


def _setup(tmp_path, monkeypatch, runs):
    home = tmp_path / 'hermes'
    home.mkdir()
    owned = _home(home, runs)
    monkeypatch.setattr(hermes_tasks, '_owned_requests', lambda _db, sid: owned.get(sid, []))
    monkeypatch.setenv('GBOX_HERMES_DISPATCH_STATE', str(tmp_path / 'dispatch'))
    (tmp_path / 'dispatch').mkdir()
    return home


def test_ended_run_summary_posted_once_with_response_when_run_left_no_reply(tmp_path, monkeypatch):
    run = 'a' * 32
    home = _setup(tmp_path, monkeypatch, [
        (run, 'completed', T0, T0 + 1500, None, '## Ticket #1300: PR outcomes now show\n\nDetails here.', [RID]),
        ('b' * 32, 'running', T0 + 1600, None, None, '', [RID]),          # still running: no post
        ('c' * 32, 'completed', T0 + 10, T0 + 20, None, 'nothing', []),    # no ticket work: no post
    ])
    inbox = Inbox({RID: {'number': 1300, 'messages': [{'author': 'operator', 'text': 'check runs', 'ts': T0 - 5}]}})
    result = hermes_summaries.reconcile(inbox, home=home, now=T0 + 1800)
    assert [p['request_id'] for p in result['posted']] == [RID] and not result['errors']
    text = inbox.posts[0][1]
    assert text.startswith('Hermes run aaaaaaaaaaaa ended: completed after 25 min')
    assert '(openrouter/anthropic/claude-opus-5.5, 3 tool calls)' in text
    assert 'Outcome: Ticket #1300: PR outcomes now show. Details here.' in text
    assert 'posted no reply here itself' in text and 'Details here.' in text
    # A second pass, even with lost local state, posts nothing new.
    (tmp_path / 'dispatch/summaries.json').unlink()
    assert hermes_summaries.reconcile(inbox, home=home, now=T0 + 1900)['posted'] == []
    assert len(inbox.posts) == 1


def test_run_with_own_replies_gets_compact_outcome_and_failure_line(tmp_path, monkeypatch):
    run = 'd' * 32
    home = _setup(tmp_path, monkeypatch, [
        (run, 'completed', T0, T0 + 600, None,
         '[CRON_FAILURE]\nWorker i9-NUC timed out twice; patch kept in the workspace.', [RID, OTHER]),
    ])
    inbox = Inbox({RID: {'number': 1300, 'messages': [{'author': 'agent', 'text': 'progress', 'ts': T0 + 100}]},
                   OTHER: {'number': 1299, 'messages': []}})
    hermes_summaries.reconcile(inbox, home=home, now=T0 + 700)
    posts = dict(inbox.posts)
    assert set(posts) == {RID, OTHER}
    assert 'Outcome: reported failure: Worker i9-NUC timed out twice' in posts[RID]
    assert 'posted no reply here itself' not in posts[RID]        # the run already replied on #1300
    assert 'posted no reply here itself' in posts[OTHER]
    assert 'also worked on #1299' in posts[RID]


def test_runs_before_backfill_window_and_silent_runs(tmp_path, monkeypatch):
    home = _setup(tmp_path, monkeypatch, [
        ('e' * 32, 'completed', T0 - 9 * 3600, T0 - 8 * 3600, None, 'old work', [RID]),
        ('f' * 32, 'failed', T0, T0 + 120, 'RuntimeError: provider quota', '[SILENT]', [RID]),
    ])
    inbox = Inbox({RID: {'number': 1300, 'messages': []}})
    hermes_summaries.reconcile(inbox, home=home, now=T0 + 200)
    assert len(inbox.posts) == 1
    text = inbox.posts[0][1]
    assert text.startswith('Hermes run ffffffffffff ended: failed after 2 min')
    assert 'Outcome: error: RuntimeError: provider quota' in text and '[SILENT]' not in text


def test_unreachable_ticket_is_retried_on_next_pass(tmp_path, monkeypatch):
    home = _setup(tmp_path, monkeypatch, [('9' * 32, 'completed', T0, T0 + 60, None, 'done', [RID])])
    def down(path, body=None):
        raise OSError('inbox down')
    assert hermes_summaries.reconcile(down, home=home, now=T0 + 100)['errors'] == [f'{RID}: OSError']
    inbox = Inbox({RID: {'number': 1300, 'messages': []}})
    assert len(hermes_summaries.reconcile(inbox, home=home, now=T0 + 200)['posted']) == 1


def test_agent_runs_older_than_many_maintenance_runs_are_found(tmp_path, monkeypatch):
    agent = ('1' * 32, 'completed', T0, T0 + 300, None, 'real work', [RID])
    scripts = [(f'{n:032x}', 'completed', T0 + 400 + n * 180, T0 + 402 + n * 180, None, '', [])
               for n in range(2, 120)]
    # Twelve later agent runs on other work push it past hermes_tasks._session's 10-row window.
    scripts += [(f'{n:06x}' + 'a' * 26, 'completed', T0 + 30000 + n * 900, T0 + 30100 + n * 900, None, 'x', [])
                for n in range(12)]
    home = _setup(tmp_path, monkeypatch, [agent] + scripts)
    assert [r['id'] for r in hermes_summaries.ended_runs(home, since=T0 - 60)] == ['1' * 32]


def test_missing_hermes_databases_post_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv('GBOX_HERMES_DISPATCH_STATE', str(tmp_path))
    assert hermes_summaries.reconcile(Inbox({}), home=tmp_path / 'none', now=T0) == {'posted': [], 'errors': []}
