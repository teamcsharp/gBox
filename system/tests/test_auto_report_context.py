"""A context-free auto report must never reach the durable Hermes queue.

Regression for gBox request #2933: an auto report with game "unknown game" and empty model,
session, job, character and target was queued, ran for 107 minutes and exhausted the local
inference node with HTTP 429 before anyone noticed the report named nothing.

The rule lives in gbox/auto_report.py and is enforced at two independent call sites:
the server that files the report (POST /api/requests/auto-mod-failure) and the durable
work queue that dispatches it. These tests drive both call sites for real.
"""
import time

import pytest

try:                                    # the package is importable under the publish harness (PYTHONPATH=system)
    from gbox import auto_report
except ImportError:                     # noqa: BLE001 - standalone run
    import importlib.util
    from pathlib import Path
    _spec = importlib.util.spec_from_file_location(
        "auto_report_under_test", Path(__file__).resolve().parents[1] / "gbox" / "auto_report.py")
    auto_report = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(auto_report)

from fastapi.testclient import TestClient

from gbox.agent import ChatHub
from gbox.server import create_app


# The context exactly as it was stored on request #2933 (the one that burned a 107-minute run).
REQUEST_2933_CONTEXT = {"session_id": "", "session": "", "game_id": None, "game": "unknown game", "model": "",
                        "moment": "", "character": "", "target": "", "target_kind": "", "x": None, "y": None,
                        "needs_rebuild": False, "native_replacement": True, "replacement_requested": False,
                        "job_id": "", "auto_report": True, "resolution_dispatch": "hermes_queue"}


@pytest.fixture(autouse=True)
def isolated_hermes_home(monkeypatch, tmp_path):
    monkeypatch.setenv('GBOX_HERMES_HOME', str(tmp_path / 'hermes'))


# ---------------------------------------------------------------- the rule


def test_empty_report_is_not_identified():
    assert not auto_report.identified({})


def test_placeholders_are_not_identifying():
    payload = {"session_id": "", "job_id": "", "game": "unknown game", "model": "not identified",
               "character": "", "target": "none"}
    assert not auto_report.identified(payload)


def test_request_2933_context_is_not_identified():
    """The exact context stored on request #2933 (the one that burned a 107-minute run)."""
    assert not auto_report.identified(REQUEST_2933_CONTEXT)


def test_each_identifying_field_carries():
    for key in auto_report.IDENTIFYING_FIELDS:
        payload = {k: "" for k in auto_report.IDENTIFYING_FIELDS}
        payload[key] = "something"
        assert auto_report.identified(payload), key


def test_resolved_session_identifies():
    assert auto_report.identified({}, {"game_id": "ff72441b33ff806b"})
    assert auto_report.identified({}, {"title": "Ocarina of Time"})


# ---------------------------------------------------------------- the server that files the report


def _client(cfg, monkeypatch, dispatched):
    from gbox import hermes_task_mode
    monkeypatch.setattr(hermes_task_mode, '_job', lambda: {'no_agent': True, 'enabled': False})
    monkeypatch.setattr(ChatHub, 'post', lambda self, cid, text, context, *args: dispatched.append((cid, text)))
    app = create_app(cfg)
    return TestClient(app, headers={'Authorization': f'Bearer {cfg.token()}'})


def test_server_files_a_context_free_report_as_blocked_and_never_dispatches_it(cfg, monkeypatch):
    """The report that started all this: no session, no job, no game, no model. It must be kept for the
    record and must not start an agent run, a chat dispatch or a queue entry."""
    dispatched = []
    client = _client(cfg, monkeypatch, dispatched)
    response = client.post('/api/requests/auto-mod-failure', json={
        'action': 'pick whip model replacement', 'detail': 'writer unsupported', 'needs_rebuild': True})
    assert response.status_code == 200, response.text
    report = response.json()
    assert report['status'] == 'blocked'
    assert report['context']['resolution_dispatch'] == 'unresolved_context'
    assert report['context']['unresolved_reason']
    assert report['context']['auto_report'] is True
    assert any('not queued' in (m.get('text') or '') for m in report['messages'])
    assert dispatched == []


def test_server_still_dispatches_an_identified_report(cfg, monkeypatch):
    """The guard must not disable the normal path: a report that names a model and a game is queued."""
    dispatched = []
    client = _client(cfg, monkeypatch, dispatched)
    response = client.post('/api/requests/auto-mod-failure', json={
        'game': 'Metal Gear Solid', 'model': 'Cyborg Ninja', 'target': 'Snake', 'job_id': 'failed-job'})
    assert response.status_code == 200, response.text
    report = response.json()
    assert report['status'] == 'open'
    assert report['context']['resolution_dispatch'] == 'hermes_queue'
    assert report['context']['auto_report'] is True
    assert dispatched == []          # managed queue owns it, no local chat dispatch


# ---------------------------------------------------------------- the durable queue that dispatches it


def _queue_requests(context, rid='74c5860e83504d69'):
    return [{'id': rid, 'number': 2933, 'title': 'Auto report: model replacement failed',
             'body': 'Action: pick whip model replacement', 'source': 'automation', 'author': 'system',
             'automated': True, 'status': 'open', 'created': 1792569609.0, 'context': dict(context)}]


def test_queue_never_dispatches_an_unidentified_auto_report():
    from gbox import hermes_work_queue
    data = {'version': 1, 'items': {}, 'parent_request_id': None}
    hermes_work_queue.sync(data, {'items': [], 'count': 0}, _queue_requests(REQUEST_2933_CONTEXT), now=time.time())
    assert 'inbox:74c5860e83504d69' not in data['items']


def test_queue_still_dispatches_an_identified_auto_report():
    """Positive control: the guard skips exactly the context-free report, not every auto report."""
    from gbox import hermes_work_queue
    context = dict(REQUEST_2933_CONTEXT, model='Amy Rose', character='sa2_amy_rose', target='Claude')
    data = {'version': 1, 'items': {}, 'parent_request_id': None}
    hermes_work_queue.sync(data, {'items': [], 'count': 0}, _queue_requests(context), now=time.time())
    item = data['items'].get('inbox:74c5860e83504d69')
    assert item is not None
    assert item['lane'] == 'inbox' and item['repair'] is True
