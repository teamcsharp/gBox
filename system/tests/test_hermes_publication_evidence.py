import json
import sqlite3

import pytest

from gbox import hermes_publication_evidence as E, hermes_device_work as W
from test_hermes_device_work import RID, NODES, call, receipt, run


def pull(**extra):
    return dict(number=123, state='MERGED', baseRefName='main', headRefOid='b'*40,
                mergeCommit={'oid': 'c'*40}, url=receipt()['url'], mergedAt='1970-01-01T00:02:40Z') | extra


def graph(base='a'*40, head='b'*40, **extra):
    return dict(status='ahead', html_url=f'https://github.com/teamcsharp/gBox/compare/{base}...{head}',
                base_commit={'sha': base}, merge_base_commit={'sha': base}) | extra


def aggregate(runs=(), sessions=None, receipts=None, merges=None, since=100):
    history = []
    devices, rows = W.aggregate(list(runs), sessions or {}, NODES, receipts or [receipt(provenance={})],
        {RID: dict(id=RID, number=12, title='Fix reader', status='done')}, merges or {}, [], since, 200,
        contributions=history)
    return {d['id']: d for d in devices}, rows, history


def test_missing_execution_shows_unknown_history_without_fake_run_or_duration():
    devices, rows, history = aggregate()
    assert rows == [] and len(history) == 1
    h = history[0]
    assert h['device_id'] == 'unknown' and h['run_id'] is None and h['ticket']['number'] == 12
    assert not {'started', 'finished', 'wall_s', 'state'} & h.keys()
    assert h['outcomes'][0]['kind'] == 'pr_published'
    assert devices['unknown']['metrics']['prs_opened'] == 1
    assert devices['unknown']['metrics']['observed_run_count'] == devices['unknown']['metrics']['wall_s'] == 0
    assert devices['unknown']['metrics']['requests_resolved'] == 0


def test_duplicate_receipt_never_creates_history_or_double_credit_when_run_linked():
    devices, rows, history = aggregate([run()], {'run-a': {'calls': [call()]}}, [receipt(), receipt()])
    assert history == [] and len(rows[0]['outcomes']) == 1
    assert devices['sparkDeux']['metrics']['prs_opened'] == 1


def test_temporal_overlap_alone_never_assigns_legacy_publication_to_local_worker():
    devices, rows, history = aggregate([run()], {'run-a': {'calls': [call()]}})
    assert len(history) == 1 and history[0]['device_id'] == 'unknown'
    assert devices['sparkDeux']['metrics']['prs_opened'] == 0


def source(record=None):
    record = record or receipt(provenance={})
    return {k: record[k] for k in ('request_id', 'pr_number', 'commit', 'url', 'published_at')} | {
        'source': 'successful_publish_response_and_model_calls', 'session_id': 'supervisor', 'call_id': 'exact',
        'routes': W.observed_routes({'calls': [call('nous', 'https://nous/v1')]}, NODES)}


def test_exact_supervisor_publisher_overrides_overlapping_local_execution():
    evidence = source()
    devices, rows, history = aggregate([run()], {'run-a': {'calls': [call()]}},
        merges={'publication_sources': {E.key(receipt()): {'evidence': evidence}}})
    assert len(history) == 1 and history[0]['device_id'] == 'provider:nous'
    assert not any(o['kind'].startswith('pr_') for o in rows[0]['outcomes'])
    assert devices['sparkDeux']['metrics']['prs_opened'] == 0
    assert devices['provider:nous']['metrics']['prs_opened'] == 1
    evidence['commit'] = 'd'*40
    _, rows, history = aggregate(merges={'publication_sources': {E.key(receipt()): {'evidence': evidence}}})
    assert history[0]['device_id'] == 'unknown'


def test_later_reroute_keeps_publication_separate_from_mixed_session():
    evidence = source() | {'session_id': 'run-a'}
    devices, rows, history = aggregate([run()], {'run-a': {'calls': [call('nous', 'https://nous/v1'), call()]}},
        merges={'publication_sources': {E.key(receipt()): {'evidence': evidence}}})
    assert rows[0]['device_id'] == 'mixed'
    assert len(history) == 1 and history[0]['device_id'] == 'provider:nous'
    assert devices['mixed']['metrics']['prs_opened'] == 0
    assert devices['provider:nous']['metrics']['prs_opened'] == 1


@pytest.mark.parametrize('routes', [[{'device_id': 'sparkDeux'}],
    [{'device_id': 'sparkDeux', 'source': 'current_configuration', 'calls_ok': 1, 'first': 120, 'last': 130}],
    [{'device_id': 'sparkDeux', 'source': 'logged_endpoint', 'calls_ok': 1, 'first': 120, 'last': 160}]])
def test_legacy_provenance_requires_observed_calls_before_publication(routes):
    rec = receipt(provenance={'status': 'observed', 'request_id': RID, 'runs': [{'routes': routes}]})
    devices, _, history = aggregate(receipts=[rec])
    assert history[0]['device_id'] == 'unknown' and devices['sparkDeux']['metrics']['prs_opened'] == 0


def test_verified_ancestry_is_separate_from_exact_head_merge_and_completion():
    rec, p = receipt(provenance={}), pull()
    ancestry = E.ancestry(rec, p, compare_fn=lambda *a: graph(), now=180)
    assert ancestry['verified']
    merges = {'observations': {'123': p}, 'ancestry': {E.key(rec): ancestry}}
    devices, _, history = aggregate(merges=merges)
    outcome = history[0]['outcomes'][-1]
    assert outcome['kind'] == 'pr_reviewed_merge' and outcome['verified']
    assert outcome['status'] == 'merged_after_review'
    m = devices['unknown']['metrics']
    assert m['prs_reviewed_contributions'] == 1 and m['prs_merged'] == m['requests_resolved'] == 0
    assert E.valid_ancestry(rec, p, ancestry)
    for k, v in [('repository', 'other/repo'), ('merge_commit', 'd'*40), ('published_commit', 'd'*40),
                 ('merged_head', 'd'*40), ('base', 'dev')]:
        assert not E.valid_ancestry(rec, p, ancestry | {k: v})
    assert not E.valid_ancestry(rec, p | {'headRefOid': 'e'*40}, ancestry)
    assert not E.valid_ancestry(rec, p | {'url': 'https://github.com/other/repo/pull/123'}, ancestry)


@pytest.mark.parametrize('change', [dict(status='diverged'), dict(merge_base_commit={'sha': 'd'*40}),
    dict(base_commit={'sha': 'd'*40}), dict(html_url='https://github.com/other/repo/compare/a...b')])
def test_negative_or_wrong_graph_never_credits_contribution(change):
    evidence = E.ancestry(receipt(), pull(), compare_fn=lambda *a: graph(**change), now=180)
    assert evidence['verified'] is False
    assert not E.valid_ancestry(receipt(), pull(), evidence)


def test_history_window_can_include_merge_without_publication_and_excludes_old_history():
    devices, _, history = aggregate(merges={'observations': {'123': pull(headRefOid='a'*40)}}, since=150)
    assert [o['kind'] for o in history[0]['outcomes']] == ['pr_merged']
    assert devices['unknown']['metrics']['prs_opened'] == 0
    _, _, history = aggregate(since=150)
    assert history == []


def fixture_db():
    db = sqlite3.connect(':memory:'); db.row_factory = sqlite3.Row
    db.execute('CREATE TABLE sessions(id TEXT,source TEXT,started_at REAL,ended_at REAL)')
    db.execute('CREATE TABLE messages(id INTEGER PRIMARY KEY,session_id TEXT,role TEXT,content TEXT,tool_name TEXT,tool_call_id TEXT,tool_calls TEXT,timestamp REAL)')
    return db


def add_publish(db, sid='supervisor', rec=None, result=None, cid='call-1'):
    rec = rec or receipt(provenance={})
    db.execute('INSERT INTO sessions VALUES(?,?,?,?)', (sid, 'gbox-build-supervisor', 100, 170))
    tool = 'mcp__gbox__publish_task_changes'
    calls = [{'id': cid, 'function': {'name': tool, 'arguments': json.dumps({'request_id': RID})}}]
    db.execute('INSERT INTO messages VALUES(NULL,?,?,?,?,?,?,?)', (sid, 'assistant', '', None, None, json.dumps(calls), 140))
    db.execute('INSERT INTO messages VALUES(NULL,?,?,?,?,?,?,?)', (sid, 'tool', json.dumps(rec if result is None else result), tool, cid, None, 146))


def test_publisher_requires_exact_response_and_preceding_successful_served_calls():
    db = fixture_db(); add_publish(db)
    sessions = {'supervisor': {'calls': [call('nous', 'https://nous/v1', ts=140),
        call('gbox-sparkDeux', 'http://two/v1', ts=160), call(state='failed', ts=130)]}}
    result = E.publisher(receipt(provenance={}), sessions, NODES, db=db)
    assert result['session_id'] == 'supervisor' and result['call_id'] == 'call-1'
    assert [r['device_id'] for r in result['routes']] == ['provider:nous']
    result = E.publisher(receipt(provenance={}), {}, NODES, db=db)
    assert result['routes'] == []  # session/source/model labels are not served-call evidence
    assert E.publisher(receipt(commit='d'*40), sessions, NODES, db=db) is None
    add_publish(db, 'another', cid='call-2')
    assert E.publisher(receipt(provenance={}), sessions, NODES, db=db) is None


def test_unrelated_malformed_wrappers_do_not_hide_an_exact_publication():
    db = fixture_db(); add_publish(db)
    bad = [{'id': 'other', 'function': {'name': 'tool_call', 'arguments': json.dumps({'calls': 'publish_task_changes mentioned in prose'})}}]
    db.execute('INSERT INTO messages VALUES(NULL,?,?,?,?,?,?,?)', ('supervisor', 'assistant', '', None, None, json.dumps(bad), 142))
    assert E.publisher(receipt(provenance={}), {}, NODES, db=db)['call_id'] == 'call-1'
    # A duplicate exact publication response remains ambiguous and is rejected.
    db.execute('INSERT INTO messages SELECT NULL,session_id,role,content,tool_name,tool_call_id,tool_calls,timestamp FROM messages WHERE role="tool"')
    assert E.publisher(receipt(provenance={}), {}, NODES, db=db) is None


@pytest.mark.parametrize('result', [{'error': 'denied'}, {'request_id': RID, 'commit': 'a'*40}, 'claimed successful'])
def test_publisher_rejects_failed_partial_or_prose_response(result):
    db = fixture_db(); add_publish(db, result=result)
    assert E.publisher(receipt(provenance={}), {}, NODES, db=db) is None


def test_publisher_bounds_fail_closed(monkeypatch):
    db = fixture_db(); add_publish(db)
    monkeypatch.setattr(E, 'MESSAGE_LIMIT', 1)
    assert E.publisher(receipt(provenance={}), {}, NODES, db=db) is None
    monkeypatch.setattr(E, 'MESSAGE_LIMIT', 250); monkeypatch.setattr(E, 'MAX_BYTES', 1)
    assert E.publisher(receipt(provenance={}), {}, NODES, db=db) is None


def test_backfill_is_bounded_and_idempotent_for_exact_graphs(monkeypatch):
    monkeypatch.setattr(E, 'BACKFILL_LIMIT', 2)
    records = [receipt(pr_number=i, url=f'https://github.com/teamcsharp/gBox/pull/{i}') for i in range(1, 6)]
    saved = {'observations': {str(r['pr_number']): pull(number=r['pr_number'], url=r['url']) for r in records}}
    sources, comparisons = [], []
    def sf(r): sources.append(r['pr_number']); return None
    def cf(a,b): comparisons.append((a,b)); return graph()
    assert E.backfill(saved, records, now=180, source_fn=sf, compare_fn=cf) == []
    assert len(sources) == len(comparisons) == 2
    E.backfill(saved, records, now=190, source_fn=sf, compare_fn=cf)
    assert len(sources) == len(comparisons) == 4


def test_reconciliation_persists_evidence_without_posting_or_changing_status(tmp_path, monkeypatch):
    from gbox import hermes_merges as M
    monkeypatch.setenv('GBOX_HERMES_DISPATCH_STATE', str(tmp_path))
    seen = []
    def backfill(saved, records, *, now):
        seen.append(now); saved['publication_sources'] = {'proof': {'checked_at': now}}; return []
    def no_api(*a, **k): raise AssertionError('No request mutation or query needed')
    result = M.reconcile(no_api, now=200, force=True, evidence_backfill=backfill)
    assert result['posted'] == [] and result['errors'] == [] and seen == [200]
    assert json.loads((tmp_path/'merges.json').read_text())['publication_sources']['proof']['checked_at'] == 200
