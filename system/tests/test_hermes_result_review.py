"""Crash/retry/delivery contract tests, runnable with unittest or pytest."""
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from gbox import hermes_result_review as R, hermes_review_merge as G, hermes_work_queue as Q


class ReviewFixture:
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        env = patch.dict(os.environ, GBOX_HERMES_DISPATCH_STATE=str(self.root), GBOX_HERMES_HOME=str(self.root / 'home'))
        env.start()
        self.addCleanup(env.stop)
        R.save_config({'enabled': True})
        self.item = {'request_id': 'a' * 16, 'job_id': 'job1', 'last_run_id': '1' * 32,
                     'lane': 'inbox', 'number': 12}
        self.run = {'id': '1' * 32, 'job_id': 'job1', 'status': 'completed',
                    'started_at': '2026-10-18T00:01:00+00:00', 'finished_at': '2026-10-18T00:02:00+00:00'}
        self.key = 'run:' + self.run['id']

    def verdict(self, key=None, verdict='retry'):
        return {'key': key or self.key, 'verdict': verdict, 'diagnosis': 'Missing parser bounds check',
                'next_action': 'Validate entry offset before reading, preserve the source image',
                'verification': 'Run truncated-entry regression test', 'evidence': ['Tool read failed at entry 7']}

    def accept(self, key=None, verdict=None):
        with closing(R.connect()) as db, db:
            db.execute("UPDATE reviews SET state='reviewed',verdict=? WHERE key=?",
                       (json.dumps(verdict or self.verdict(key)), key or self.key))


class ResultReviewTests(ReviewFixture, unittest.TestCase):
    def test_opt_in_and_fresh_tasks(self):
        self.assertIsNone(R.gate({'request_id': 'a' * 16}))
        R.save_config({'enabled': False})
        R.record_result(self.item, self.run)
        self.assertIsNone(R.result(self.key))
        self.assertIsNone(R.gate(self.item))

    def test_every_occurrence_is_durable_and_idempotent(self):
        R.record_result(self.item, self.run)
        R.record_result(self.item, self.run)
        R.record_result(self.item, self.run | {'id': '2' * 32})
        self.assertEqual(R.summary()['counts'], {'pending': 2})
        self.assertIn('Waiting', R.gate(self.item))

    def test_scan_catches_run_that_finishes_after_later_row(self):
        cron = R.M._home() / 'cron'
        cron.mkdir(parents=True)
        with closing(sqlite3.connect(cron / 'executions.db')) as db, db:
            db.execute('CREATE TABLE executions(id,job_id,status,started_at,finished_at)')
            db.executemany('INSERT INTO executions VALUES(?,?,?,?,?)', [
                ('first', 'job1', 'running', '2026-10-18T01:00:00', None),
                ('second', 'job1', 'completed', '2026-10-18T02:00:00', '2026-10-18T03:00:00'),
                ('unrelated', 'other', 'completed', '2026-10-18T02:00:00', '2026-10-18T03:00:00')])
        with patch.object(Q, '_read', return_value={'items': {'task': self.item}}):
            R.discover()
            self.assertEqual(R.summary()['counts'], {'pending': 1})
            with closing(sqlite3.connect(cron / 'executions.db')) as db, db:
                db.execute("UPDATE executions SET status='failed',finished_at='2026-10-18T04:00:00' WHERE id='first'")
            R.discover()
            R.discover()
        self.assertEqual(R.summary()['counts'], {'pending': 2})

    def test_guidance_reaches_next_prompt_and_never_accepts_task(self):
        R.record_result(self.item, self.run)
        self.accept()
        self.assertIsNone(R.gate(self.item))
        with patch.object(Q.mode, '_handoff', return_value=''):
            prompt = Q._prompt(self.item)
        self.assertIn('Missing parser bounds check', prompt)
        self.assertIn('Run truncated-entry regression test', prompt)
        self.assertNotIn('completed', self.item)

    def test_candidate_waits_for_review_even_after_retry_timer(self):
        data = {'items': {'task': self.item}}
        requests = [{'id': self.item['request_id'], 'status': 'open'}]
        self.assertEqual(Q.candidates(data, requests, [], set(), set(), now=time.time()), [])
        R.record_result(self.item, self.run)
        self.accept()
        self.assertEqual(len(Q.candidates(data, requests, [], set(), set(), now=time.time())), 1)

    def test_repeated_diagnosis_escalates_instead_of_infinite_retry(self):
        for n in range(3):
            run = self.run | {'id': str(n) * 32, 'started_at': f'2026-10-18T0{n}:00:00'}
            key = 'run:' + run['id']
            R.record_result(self.item, run)
            self.accept(key, self.verdict(key))
        self.item['last_run_id'] = '2' * 32
        self.assertIn('Repeated diagnosis', R.gate(self.item))
        self.assertEqual(R.result('run:' + '2' * 32)['state'], 'escalated')

    def test_strict_result_identity_and_missing_evidence(self):
        row = {'key': self.key, 'kind': 'run'}
        for value in (self.verdict('wrong'), self.verdict(verdict='approve_merge'), self.verdict() | {'evidence': []},
                      self.verdict() | {'next_action': ''}, self.verdict() | {'verification': 17}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                R.validate(value, row)

    def test_paid_response_persisted_before_outbox_and_no_repeat(self):
        R.record_result(self.item, self.run)
        response = {'content': json.dumps(self.verdict()), 'usage': {'total_tokens': 32}, 'finish_reason': 'stop'}
        with patch.object(R, 'packet', return_value={'evidence': 'retained'}), patch.object(R, 'review', return_value=response) as paid:
            self.assertEqual(R.process_one(), self.key)
            self.assertIsNone(R.process_one())
            self.assertEqual(paid.call_count, 1)
        row = R.result(self.key)
        self.assertEqual(row['state'], 'reviewed')
        self.assertTrue(Path(row['evidence_file']).is_file())
        self.assertTrue(Path(row['response_file']).is_file())

    def test_lost_delivery_ack_does_not_duplicate_or_pay_again(self):
        R.record_result(self.item, self.run)
        self.accept()
        messages = []
        def api(path, body=None):
            if body:
                messages.append(body)
                raise TimeoutError('Lost acknowledgement')
            return {'messages': messages}
        with patch.object(R, '_api', side_effect=api):
            R.deliver()
            self.assertEqual(R.result(self.key)['delivered'], 0)
            R.deliver()
        self.assertEqual(len(messages), 1)
        self.assertEqual(R.result(self.key)['delivered'], 1)

    def test_provider_failure_preserves_result_and_backs_off_globally(self):
        R.record_result(self.item, self.run)
        with patch.object(R, 'packet', return_value={}), patch.object(R, 'review', side_effect=RuntimeError('network_unavailable')):
            self.assertIsNone(R.process_one())
        row = R.result(self.key)
        self.assertEqual(row['state'], 'retry')
        self.assertGreater(row['next_at'], time.time())
        self.assertGreater(R.config()['next_at'], time.time())
        self.assertIn('Waiting', R.gate(self.item))

    def test_crash_lease_is_recovered(self):
        R.record_result(self.item, self.run)
        with closing(R.connect()) as db, db:
            db.execute("UPDATE reviews SET state='reviewing',next_at=0")
        with patch.object(R, 'packet', return_value={}), patch.object(R, 'review', return_value={'content': json.dumps(self.verdict()), 'finish_reason': 'stop'}):
            self.assertEqual(R.process_one(), self.key)
        self.assertEqual(R.result(self.key)['state'], 'reviewed')

    def test_new_guidance_reopens_blocker_but_own_report_does_not(self):
        R.record_result(self.item, self.run)
        self.accept(verdict=self.verdict(verdict='blocked'))
        before = {'body': 'Fix bounds', 'messages': []}
        evidence = self.root / 'evidence.json'
        evidence.write_text(json.dumps({'feedback_signature': R.feedback_signature(before)}))
        with closing(R.connect()) as db, db:
            db.execute('UPDATE reviews SET evidence_file=?', (str(evidence),))
        own = before | {'messages': [{'text': 'Cloud result review run:123 guidance'}]}
        with patch.object(R, '_api', return_value=own):
            R.refresh_holds()
        self.assertEqual(R.result(self.key)['state'], 'reviewed')
        changed = before | {'messages': [{'text': 'ZAI guidance: apply checked parser offset in existing workspace'}]}
        with patch.object(R, '_api', return_value=changed):
            R.refresh_holds()
        self.assertEqual(R.result(self.key)['state'], 'pending')

    def test_latest_and_historical_reviews_both_have_service(self):
        for n in range(3):
            R.record_result(self.item, self.run | {'id': str(n), 'started_at': f'2026-10-18T0{n}:00:00'})
        def response(packet):
            return {'content': json.dumps(self.verdict(packet['review_key'])), 'finish_reason': 'stop'}
        with patch.object(R, 'packet', side_effect=lambda row: {'review_key': row['key']}), patch.object(R, 'review', side_effect=response):
            self.assertEqual(R.process_one(newest=True), 'run:2')
            self.assertEqual(R.process_one(newest=False), 'run:0')

    def test_tasks_off_prevents_review_and_discovery(self):
        with patch.object(R.M, '_job', return_value={'enabled': False}), patch.object(R, 'discover') as discover:
            self.assertEqual(R.tick(), {'state': 'paused'})
        discover.assert_not_called()

    def test_truncated_paid_response_and_usage_are_retained_without_acceptance(self):
        R.record_result(self.item, self.run)
        response = {'content': '', 'finish_reason': 'length', 'usage': {'total_tokens': 5000}}
        with patch.object(R, 'packet', return_value={}), patch.object(R, 'review', return_value=response):
            self.assertIsNone(R.process_one())
        row = R.result(self.key)
        self.assertEqual(row['state'], 'retry')
        self.assertEqual(json.loads(Path(row['response_file']).read_text())['usage']['total_tokens'], 5000)
        self.assertIsNone(row['verdict'])

    def test_scope_and_pause_checked_before_transport(self):
        from gbox import hermes_provider_scope as scope
        with patch.object(scope, 'admission', return_value={'reason': 'restricted'}), \
                patch.object(R.subprocess, 'run') as transport, self.assertRaises(RuntimeError):
            R.review({})
        transport.assert_not_called()
        with patch.object(scope, 'admission', return_value=None), \
                patch.object(R.M, '_job', return_value={'enabled': False}), \
                patch.object(R.subprocess, 'run') as transport, self.assertRaises(RuntimeError):
            R.review({})
        transport.assert_not_called()

    def test_large_run_evidence_excerpt_is_explicit_and_bounded(self):
        from gbox import hermes_provider_scope as scope
        value = {'kind': 'run', 'review_key': self.key, 'request': {'body': 'x' * 400000},
                 'evidence': {'output': 'log' * 100000, 'steps': []}}
        with patch.object(scope, 'admission', return_value=None), \
                patch.object(R.M, '_job', return_value={'enabled': True}), \
                patch.object(R.subprocess, 'run', return_value=SimpleNamespace(returncode=0,
                    stdout=json.dumps({'finish_reason': 'stop', 'content': '{}'}))) as transport:
            R.review(value)
        model_packet = json.loads(json.loads(transport.call_args.kwargs['input'])['messages'][1]['content'])
        self.assertTrue(model_packet['partial_evidence'])
        self.assertEqual(model_packet['review_key'], self.key)
        self.assertLess(len(json.dumps(model_packet)), 240000)

    def test_credential_envelopes_are_redacted_but_evidence_ids_survive(self):
        value = {'api_key': 'private-value', 'output': 'Authorization: Bearer secret-token-value-123456\n'
                 'DEEPSEEK_API_KEY=abcdef0123456789\npassword: "abcdefghijklmnop"\n'
                 '-----BEGIN RSA PRIVATE KEY-----\nprivate\n-----END RSA PRIVATE KEY-----',
                 'source_sha256': 'a' * 64, 'usage': {'prompt_tokens': 123}}
        cleaned = R.redact(value)
        self.assertNotIn('private-value', json.dumps(cleaned))
        self.assertNotIn('secret-token-value', json.dumps(cleaned))
        self.assertNotIn('abcdef0123456789', json.dumps(cleaned))
        self.assertNotIn('abcdefghijklmnop', json.dumps(cleaned))
        self.assertEqual(cleaned['source_sha256'], 'a' * 64)
        self.assertEqual(cleaned['usage']['prompt_tokens'], 123)

    def test_installer_does_not_enable_gate_on_uncertain_cron_creation(self):
        from gbox import hermes_provider_scope as scope
        R.save_config({'enabled': False})
        with patch.object(scope, 'admission', return_value=None), patch.object(R.M, '_jobs', return_value=[]), \
                patch.object(R.M, '_run'), self.assertRaises(RuntimeError):
            R.install(auto_merge=True)
        self.assertFalse(R.config()['enabled'])


class MergeReviewTests(ReviewFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        R.save_config({'enabled': True, 'auto_merge': True})
        job = patch.object(R.M, '_job', return_value={'enabled': True})
        job.start()
        self.addCleanup(job.stop)
        self.expected = {'number': 7, 'headRefOid': 'b' * 40, 'baseRefOid': 'c' * 40}
        self.pull = self.expected | {'state': 'OPEN', 'baseRefName': 'main', 'isCrossRepository': False,
                    'mergeable': 'MERGEABLE', 'mergeStateStatus': 'CLEAN', 'isDraft': False,
                    'reviewDecision': '', 'statusCheckRollup': []}

    def seed_pr(self, evidence):
        key = 'pr:7:' + 'b' * 40 + ':' + 'c' * 40
        R.enqueue(key, 'pr', self.item['request_id'], self.expected)
        path = self.root / 'pr-evidence.json'
        path.write_text(json.dumps({'evidence': evidence}))
        self.accept(key, self.verdict(key, 'approve_merge'))
        with closing(R.connect()) as db, db:
            db.execute('UPDATE reviews SET evidence_file=? WHERE key=?', (str(path), key))
        return key

    def good_evidence(self):
        return {'complete': True, 'head': self.expected['headRefOid'], 'base': self.expected['baseRefOid'],
                'integration': {'exit_code': 0, 'passed': 8}}

    def test_base_commit_uses_supported_rest_api_with_head_consistency(self):
        with patch.object(G, 'gh', side_effect=[json.dumps(self.pull),
                json.dumps({'head': 'b' * 40, 'base': 'c' * 40})]) as gh:
            self.assertEqual(G.pull(7)['baseRefOid'], 'c' * 40)
        self.assertNotIn('baseRefOid', gh.call_args_list[0].args[-1])
        with patch.object(G, 'gh', side_effect=[json.dumps(self.pull),
                json.dumps({'head': 'd' * 40, 'base': 'c' * 40})]), self.assertRaises(RuntimeError):
            G.pull(7)

    def test_head_or_base_move_invalidates_review(self):
        for field in ('headRefOid', 'baseRefOid'):
            with self.subTest(field=field), self.assertRaises(RuntimeError):
                G.identity(self.pull | {field: 'd' * 40}, self.expected)

    def test_merge_rejects_missing_or_failed_independent_tests(self):
        for evidence in ({}, self.good_evidence() | {'complete': False},
                         self.good_evidence() | {'integration': {'exit_code': 1, 'passed': 8}},
                         self.good_evidence() | {'integration': {'exit_code': 0, 'passed': 0}}):
            self.seed_pr(evidence)
            with patch.object(G, 'gh') as gh:
                self.assertIsNone(G.deliver_one())
            gh.assert_not_called()

    def test_github_checks_and_change_requests_block(self):
        for extra in ({'reviewDecision': 'CHANGES_REQUESTED'}, {'mergeable': 'CONFLICTING'},
                      {'mergeStateStatus': 'BEHIND'}, {'statusCheckRollup': [{'state': 'PENDING'}]},
                      {'statusCheckRollup': [{'__typename': 'CheckRun', 'status': 'COMPLETED', 'conclusion': 'FAILURE'}]}):
            with self.subTest(extra=extra), self.assertRaises(RuntimeError):
                G.checks(self.pull | extra)

    def test_exact_head_merge_and_receipt(self):
        key = self.seed_pr(self.good_evidence())
        from gbox import hermes_merges
        with patch.object(G, 'pull', side_effect=[self.pull, self.pull, self.pull | {'state': 'MERGED'}]), \
                patch.object(G, 'gh', return_value='') as gh, \
                patch.object(hermes_merges, 'reconcile'), patch.object(hermes_merges, 'reconcile_branches'):
            self.assertEqual(G.deliver_one(), key)
        args = gh.call_args.args
        self.assertEqual(args[0:2], ('pr', 'merge'))
        self.assertEqual(args[-2:], ('--match-head-commit', 'b' * 40))
        self.assertNotIn('--admin', args)
        self.assertEqual(R.result(key)['state'], 'merged')

    def test_lost_merge_ack_recovers_without_remerging(self):
        key = self.seed_pr(self.good_evidence())
        from gbox import hermes_merges
        with patch.object(G, 'pull', return_value=self.pull | {'state': 'MERGED'}), \
                patch.object(G, 'gh') as gh, patch.object(hermes_merges, 'reconcile'), \
                patch.object(hermes_merges, 'reconcile_branches'):
            self.assertEqual(G.deliver_one(), key)
        gh.assert_not_called()

    def test_operator_pause_before_merge_prevents_mutation(self):
        self.seed_pr(self.good_evidence())
        with patch.object(R.M, '_job', side_effect=[{'enabled': True}, {'enabled': False}]), \
                patch.object(G, 'pull', return_value=self.pull), patch.object(G, 'gh') as gh:
            self.assertIsNone(G.deliver_one())
        gh.assert_not_called()


if __name__ == '__main__':
    unittest.main()
