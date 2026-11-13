import json
import queue
import threading

from gbox.mercs import follow_report_delivery as D
from gbox.mercs import hit_reports as H


def test_a_blocked_post_cannot_block_the_next_combat_observation(monkeypatch, tmp_path):
    monkeypatch.setattr(D, 'ROOT', tmp_path)
    entered, release, returned = threading.Event(), threading.Event(), threading.Event()
    calls = []
    def slow_post(url, token, body):
        calls.append((url, token, body))
        entered.set()
        assert release.wait(5)
        return {'id':'request-1'}
    monkeypatch.setattr(H, 'post', slow_post)
    monkeypatch.setattr(H, '_CFG', dict(url='http://old', token='secret-old', title='RE5', session_id='old-session'))
    stats = {'round_evidence_id':'round-one', 'hits_taken':0}
    H.observe(stats, {'player':{'hp':1000}}, 0)
    def tick():
        stats['hits_taken'] = 1
        H.observe(stats, {'player':{'hp':750}}, 1)
        returned.set()
    thread = threading.Thread(target=tick)
    thread.start()
    try:
        assert entered.wait(2)
        assert returned.wait(.5), 'HTTP delivery still owns the combat tick'
        H._CFG.update(url='http://new', token='secret-new', session_id='new-session')
        assert H.observe(stats, {'player':{'hp':750}}, 1.1) is None
        assert calls[0][0:2] == ('http://old', 'secret-old')
        assert calls[0][2]['context']['session_id'] == 'old-session'
        assert stats.get('hit_reports', 0) == 0
        assert stats['hit_reports_pending'] == 1
    finally:
        release.set()
        thread.join(2)
        D._QUEUE.join()
    assert stats['hit_reports'] == 1 and stats['hit_reports_pending'] == 0
    raw = next(tmp_path.glob('*.json')).read_text()
    assert 'secret-old' not in raw and 'secret-new' not in raw
    assert json.loads(raw)['state'] == 'delivered'


def test_uncertain_submission_is_archived_and_not_replayed(monkeypatch, tmp_path):
    monkeypatch.setattr(D, 'ROOT', tmp_path)
    monkeypatch.setattr(D, '_dispatch', lambda fn:fn())
    calls = []
    def fail(*args):
        calls.append(args)
        raise TimeoutError('acknowledgement lost for secret')
    stats = {}
    assert D.submit(fail, {'url':'http://x','token':'secret'}, {'context':{'round_id':'r'}},
                    stats, 'combo', {'round':'r'}) is None
    assert len(calls) == 1 and stats['combo_report_failures'] == 1
    record = json.loads(next(tmp_path.glob('*.json')).read_text())
    assert record['state'] == 'uncertain' and record['payload']['context']['round_id'] == 'r'
    assert 'secret' not in json.dumps(record)
    assert 'combo_reports' not in stats


def test_queue_pressure_retains_unsubmitted_evidence(monkeypatch, tmp_path):
    monkeypatch.setattr(D, 'ROOT', tmp_path)
    def full(fn): raise queue.Full
    monkeypatch.setattr(D, '_dispatch', full)
    stats = {}
    assert D.submit(lambda *a:None, {'url':'http://x','token':'secret'}, {'context':{}},
                    stats, 'hit', {'round':'r'}) is None
    record = json.loads(next(tmp_path.glob('*.json')).read_text())
    assert record['state'] == 'not_submitted'
    assert stats['hit_reports_pending'] == 0


def test_delivered_request_is_not_replayed_when_receipt_archive_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(D, 'ROOT', tmp_path)
    monkeypatch.setattr(D, '_dispatch', lambda fn:fn())
    write = D._write
    def fail_receipt(path, record):
        if record['state'] == 'delivered':
            raise OSError('disk full')
        write(path, record)
    monkeypatch.setattr(D, '_write', fail_receipt)
    calls = []
    def post(*args):
        calls.append(args)
        return {'id':'acknowledged'}
    stats = {}
    receipt = D.submit(post, {'url':'http://x', 'token':'secret'}, {'context':{}},
                       stats, 'hit', {'round':'r'})
    assert receipt['state'] == 'delivered' and len(calls) == 1
    assert stats['hit_reports'] == 1 and stats['hit_reports_pending'] == 0
    assert 'disk full' in stats['hit_report_archive_error']
    assert json.loads(next(tmp_path.glob('*.json')).read_text())['state'] == 'attempted'
