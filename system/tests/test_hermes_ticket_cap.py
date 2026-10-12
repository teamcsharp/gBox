"""#1300 gap 3: one ticket must not take every inbox run in a row."""
import asyncio
import json

import httpx
import pytest

from gbox.hermes_tasks import STREAK_CAP, TASK_MODE_NAME, ticket_streaks


def run(i, rids, state='completed', name=TASK_MODE_NAME, tickets=False):
    row = {'id': f'run{i}', 'name': name, 'state': state, 'started': 1000.0 + i * 100}
    if tickets:
        row['tickets'] = [{'id': r, 'number': 1} for r in rids]
        row['request_ids'] = []
    else:
        row['request_ids'] = list(rids)
    return row


def test_three_ended_runs_in_a_row_cap_the_ticket():
    runs = [run(1, ['A']), run(2, ['A']), run(3, ['A'], tickets=True)]
    out = ticket_streaks(runs)
    assert STREAK_CAP == 3
    assert out == {'A': {'runs': 3, 'run_ids': ['run3', 'run2', 'run1'], 'since': 1100.0}}


def test_two_runs_or_a_different_ticket_in_between_do_not_cap():
    assert ticket_streaks([run(1, ['A']), run(2, ['A'])]) == {}
    assert ticket_streaks([run(1, ['A']), run(2, ['B']), run(3, ['A']), run(4, ['A'])]) == {}
    # only the newest run's tickets can be on a streak
    assert ticket_streaks([run(1, ['A']), run(2, ['A']), run(3, ['A']), run(4, ['B'])]) == {}


def test_running_unconfirmed_and_one_shot_runs_are_neutral():
    runs = [run(1, ['A']), run(2, []), run(3, ['A']), run(4, ['A'], name='gBox investigation #1300'),
            run(5, ['A']), run(6, ['A'], state='running'), run(7, ['A'], state='claimed')]
    assert ticket_streaks(runs)['A']['run_ids'] == ['run5', 'run3', 'run1']


def test_operator_message_restarts_the_count():
    runs = [run(1, ['A']), run(2, ['A']), run(3, ['A']), run(4, ['A'])]
    assert ticket_streaks(runs, {'A': 1250.0}) == {}                 # only run3, run4 after the reply
    assert ticket_streaks(runs, {'A': 1150.0})['A']['runs'] == 3      # run2-run4
    assert ticket_streaks(runs, {'B': 9999.0})['A']['runs'] == 4


def test_multi_ticket_run_caps_each_ticket_on_its_own_streak():
    runs = [run(1, ['A']), run(2, ['A', 'B']), run(3, ['A', 'B'])]
    assert set(ticket_streaks(runs)) == {'A'}


def _serve(monkeypatch, tasks_status=200):
    capped = {'id': 'capped', 'number': 1300, 'title': 'Hermes tasks', 'body': 'x', 'status': 'in_progress',
              'source': 'chat', 'created': 2,
              'messages': [{'author': 'operator', 'ts': 500.0}, {'author': 'agent', 'ts': 5000.0}]}
    other = {'id': 'other', 'number': 1299, 'title': 'worker', 'body': 'y', 'status': 'in_progress',
             'source': 'chat', 'created': 1, 'messages': [{'author': 'operator', 'ts': 400.0}]}
    hermes = [run(i, ['capped']) for i in (1, 2, 3)] + [run(4, [], state='running')]
    seen = []

    def handler(req):
        seen.append((req.url.path, dict(req.url.params)))
        if req.url.path == '/api/registry':
            return httpx.Response(200, json={'tools': []})
        if req.url.path == '/api/requests':
            return httpx.Response(200, json=[capped, other])
        if req.url.path == '/api/tasks':
            return httpx.Response(tasks_status, json={'jobs': [], 'hermes': hermes})
        raise AssertionError(req.url.path)

    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient',
                        lambda *a, **k: original(*a, **k, transport=httpx.MockTransport(handler)))
    return seen


def _call(name, args):
    from mcp.client import Client
    from gbox.mcp_server import build

    async def go():
        async with Client(build('http://fixture', 'fixture')) as client:
            return json.loads((await client.call_tool(name, args)).content[0].text)
    return asyncio.run(go())


def test_mcp_list_requests_marks_capped_ticket_and_list_tasks_names_it(monkeypatch):
    pytest.importorskip('mcp')
    seen = _serve(monkeypatch)
    items = {i['number']: i for i in _call('list_requests', {'status': 'open,in_progress', 'limit': 20})['items']}
    assert items[1300]['hermes_capped']['runs'] == 3
    assert 'Choose another actionable request' in items[1300]['hermes_capped']['note']
    assert 'hermes_capped' not in items[1299]
    assert ('/api/tasks', {'hermes_limit': '20'}) in seen
    tasks = _call('list_tasks', {})
    assert tasks['capped_requests'] == [{'request_id': 'capped', 'runs': 3, 'run_ids': ['run3', 'run2', 'run1'],
                                         'since': 1100.0}]
    assert [r['id'] for r in tasks['hermes']] == ['run4']


def test_mcp_list_requests_survives_a_failing_tasks_endpoint(monkeypatch):
    pytest.importorskip('mcp')
    _serve(monkeypatch, tasks_status=500)
    items = _call('list_requests', {'limit': 20})['items']
    assert [i['number'] for i in items] == [1300, 1299]
    assert not any('hermes_capped' in i for i in items)
