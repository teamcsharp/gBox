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
                json.dumps({'head': 'b' * 40, 'base': 'c' * 40, 'base_name': 'main'}), 'c' * 40]) as gh:
            self.assertEqual(G.pull(7)['baseRefOid'], 'c' * 40)
        self.assertNotIn('baseRefOid', gh.call_args_list[0].args[-1])
        with patch.object(G, 'gh', side_effect=[json.dumps(self.pull),
                json.dumps({'head': 'd' * 40, 'base': 'c' * 40, 'base_name': 'main'})]), self.assertRaises(RuntimeError):
            G.pull(7)

    def test_stale_pr_base_uses_current_main_and_still_invalidates_old_review(self):
        with patch.object(G, 'gh', side_effect=[json.dumps(self.pull),
                json.dumps({'head': 'b' * 40, 'base': 'a' * 40, 'base_name': 'main'}), 'c' * 40]):
            current = G.pull(7)
        G.identity(current, self.expected)
        self.assertEqual(current['reportedBaseRefOid'], 'a' * 40)
        with self.assertRaises(RuntimeError):
            G.identity(current, self.expected | {'baseRefOid': 'a' * 40})

    def test_target_branch_race_and_incomplete_main_identity_fail_closed(self):
        for refs, extra in (({'head': 'b' * 40, 'base': 'c' * 40, 'base_name': 'other'}, []),
                            ({'head': 'b' * 40, 'base': 'c' * 40, 'base_name': 'main'}, [''])):
            with self.subTest(refs=refs, extra=extra), patch.object(G, 'gh',
                    side_effect=[json.dumps(self.pull), json.dumps(refs), *extra]), self.assertRaises(RuntimeError):
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

    def test_discovery_recovers_lost_merge_ack_before_superseding(self):
        key = self.seed_pr(self.good_evidence())
        with patch.object(G, 'gh', side_effect=['[]', 'd' * 40]), \
                patch.object(G, 'pull', return_value=self.pull | {'state': 'MERGED'}):
            G.discover()
        self.assertEqual(R.result(key)['state'], 'merged')

    def test_operator_pause_before_merge_prevents_mutation(self):
        self.seed_pr(self.good_evidence())
        with patch.object(R.M, '_job', side_effect=[{'enabled': True}, {'enabled': False}]), \
                patch.object(G, 'pull', return_value=self.pull), patch.object(G, 'gh') as gh:
            self.assertIsNone(G.deliver_one())
        gh.assert_not_called()


if __name__ == '__main__':
    unittest.main()


class LocalReviewTests(ReviewFixture, unittest.TestCase):
    """When the operator set Hermes to local only, reviews run on the local route instead of waiting for credit."""

    def local(self):
        return {'provider': 'gbox-sparkDeux', 'model': 'Qwen/Qwen3-Coder-Next-FP8', 'local': True,
                'label': 'Local (sparkDeux)', 'proxy_url': 'http://127.0.0.1:8765/api/llm/local/nodes/sparkDeux/v1'}

    def test_local_only_reviews_on_the_local_route_without_deepseek(self):
        from gbox import hermes_provider_scope as scope
        R.record_result(self.item, self.run)
        self.assertEqual(R.gate(self.item), 'Waiting for durable cloud result review')
        calls = []

        def post(url, body, timeout):
            calls.append((url, body))
            return {'model': 'Qwen/Qwen3-Coder-Next-FP8', 'usage': {'total_tokens': 900},
                    'choices': [{'finish_reason': 'stop', 'message': {'content':
                        '```json\n' + json.dumps(self.verdict()) + '\n```'}}]}
        with patch.object(R, 'reviewer', return_value=self.local()), patch.object(R, 'packet', return_value={}), \
                patch.object(R.M, '_job', return_value={'enabled': True}), \
                patch.object(R, '_post_json', side_effect=post), \
                patch.object(scope, 'admission', return_value={'reason': 'restricted'}), \
                patch.object(R.subprocess, 'run') as transport:
            self.assertEqual(R.gate(self.item), 'Waiting for the local result review')
            self.assertEqual(R.process_one(), self.key)
        transport.assert_not_called()
        self.assertEqual(calls[0][0], 'http://127.0.0.1:8765/api/llm/local/nodes/sparkDeux/v1/chat/completions')
        self.assertEqual(calls[0][1]['model'], 'Qwen/Qwen3-Coder-Next-FP8')
        self.assertEqual(calls[0][1]['messages'][0]['role'], 'system')
        row = R.result(self.key)
        self.assertEqual(row['state'], 'reviewed')
        self.assertEqual(json.loads(row['verdict'])['verdict'], 'retry')
        self.assertIsNone(R.gate(self.item))            # guidance recorded: the next dispatch may go ahead
        self.assertEqual(self.item['review_guidance']['diagnosis'], 'Missing parser bounds check')

    def test_local_only_tick_ignores_the_paid_provider_scope(self):
        from gbox import hermes_provider_scope as scope
        with patch.object(R, 'reviewer', return_value=self.local()), \
                patch.object(R.M, '_job', return_value={'enabled': True}), \
                patch.object(R, 'discover'), patch.object(R, 'deliver'), patch.object(R, 'refresh_holds'), \
                patch.object(scope, 'admission', return_value={'reason': 'restricted'}), \
                patch.object(R, 'process_one', return_value=None) as process:
            state = R.tick()
        self.assertNotEqual(state.get('state'), 'waiting_provider_scope')
        self.assertTrue(state['local'])
        process.assert_called()

    def test_local_answer_without_a_json_object_is_retried_not_accepted(self):
        R.record_result(self.item, self.run)
        bad = {'choices': [{'finish_reason': 'stop', 'message': {'content': 'I could not review this run.'}}]}
        with patch.object(R, 'reviewer', return_value=self.local()), patch.object(R, 'packet', return_value={}), \
                patch.object(R.M, '_job', return_value={'enabled': True}), \
                patch.object(R, '_post_json', return_value=bad):
            self.assertIsNone(R.process_one())
        row = R.result(self.key)
        self.assertEqual(row['state'], 'retry')
        self.assertIn('invalid_provider_response', row['error'])

    def test_cloud_reviewer_unless_operator_chose_local_only(self):
        from gbox import hermes_local, hermes_pool
        with patch.object(hermes_local, 'local_only', return_value=False):
            self.assertFalse(R.reviewer()['local'])
        node = SimpleNamespace(enabled=True, allow_large_tasks=True, max_parallel_jobs=32, provider='gbox-sparkDeux',
                               model='Qwen/Qwen3-Coder-Next-FP8', host_name='sparkDeux',
                               proxy_url='http://127.0.0.1:8765/api/llm/local/nodes/sparkDeux/v1')
        small = SimpleNamespace(enabled=True, allow_large_tasks=False, max_parallel_jobs=1, provider='gbox-lilspark',
                                model='gpt-oss:20b', host_name='lilspark',
                                proxy_url='http://127.0.0.1:8765/api/llm/local/nodes/lilspark/v1')
        with patch.object(hermes_local, 'local_only', return_value=True), \
                patch.object(hermes_pool, 'node_settings', return_value={'lilspark': small, 'sparkDeux': node}):
            who = R.reviewer()
        self.assertTrue(who['local'])
        self.assertEqual((who['provider'], who['model']), ('gbox-sparkDeux', 'Qwen/Qwen3-Coder-Next-FP8'))
        self.assertEqual(who['proxy_url'], node.proxy_url)


class UnreviewableRunTests(ReviewFixture, unittest.TestCase):
    """A run the ledger cannot review must not hold its task forever."""

    def test_unrecorded_last_run_releases_after_grace_period(self):
        item = self.item | {'last_run_id': '9' * 32, 'last_finished': time.time() - 3 * 3600}
        self.assertIsNone(R.gate(item))
        recent = self.item | {'last_run_id': '9' * 32, 'last_finished': time.time() - 600}
        self.assertIn('Waiting', R.gate(recent))
        self.assertIn('Waiting', R.gate(self.item | {'last_run_id': '9' * 32}))   # never finished: still fresh

    def test_missing_transcript_reviews_from_the_thread_after_three_attempts(self):
        R.record_result(self.item, self.run)
        from gbox import hermes_tasks as T
        with closing(R.connect()) as db:
            row = dict(db.execute('SELECT * FROM reviews WHERE key=?', (self.key,)).fetchone())
        checkpoint = {'request_id': self.item['request_id'], 'final_report': 'Reader parsed 3 of 7 entries'}
        with patch.object(T, 'get_run', return_value=None), patch.object(R, '_api', return_value={'number': 12}), \
                patch.object(Q, '_read', return_value={'items': {'x': checkpoint}}):
            with self.assertRaises(RuntimeError):
                R.packet(row | {'attempts': 2})
            packet = R.packet(row | {'attempts': 3})
        self.assertTrue(packet['evidence']['transcript_unavailable'])
        self.assertEqual(packet['evidence']['final_report'], 'Reader parsed 3 of 7 entries')
        self.assertEqual(packet['current_checkpoint'], checkpoint)


class ReviewerWithoutPydanticTests(ReviewFixture, unittest.TestCase):
    """Hermes's own interpreter runs the review tick without pydantic or fastapi; local only must still apply."""

    def test_local_reviewer_from_toml_when_typed_config_is_unavailable(self):
        from gbox import hermes_local, hermes_pool
        toml = self.root / 'gbox.toml'
        toml.write_text(
            '[hermes.local]\nprovider = "gbox-sparkDeux"\nmodel = "nvidia/Qwen3.8-27B-NVFP4"\n'
            'proxy_url = "http://127.0.0.1:8765/api/llm/local/v1"\nmax_parallel_jobs = 2\n'
            '[hermes.local.nodes.lilspark]\nprovider = "gbox-lilspark"\nmodel = "gpt-oss:20b"\n'
            'max_parallel_jobs = 1\nallow_large_tasks = false\n'
            '[hermes.local.nodes.sparkDeux]\nprovider = "gbox-sparkDeux"\nmodel = "nvidia/Qwen3.8-27B-NVFP4"\n'
            'max_parallel_jobs = 4\nallow_large_tasks = true\n', encoding='utf-8')
        R.D.state_dir().mkdir(parents=True, exist_ok=True)
        (R.D.state_dir() / 'local-nodes.json').write_text(json.dumps({'nodes': {
            'sparkDeux': {'enabled': True, 'model': 'Qwen/Qwen3-Coder-Next-FP8', 'max_parallel_jobs': 32}}}))
        boom = ImportError("No module named 'pydantic'")
        with patch.object(hermes_local, '_config_path', return_value=toml), \
                patch.object(hermes_local, 'local_only', side_effect=boom), \
                patch.object(hermes_pool, 'node_settings', side_effect=boom):
            self.assertFalse(R.reviewer()['local'])                       # switch off: cloud
            (R.D.state_dir() / 'local-only.json').write_text(json.dumps({'local_only': True}))
            with patch.object(hermes_local, '_flag_path', return_value=R.D.state_dir() / 'local-only.json'):
                who = R.reviewer()
        self.assertTrue(who['local'])
        self.assertEqual((who['provider'], who['model']), ('gbox-sparkDeux', 'Qwen/Qwen3-Coder-Next-FP8'))
        self.assertEqual(who['proxy_url'], 'http://127.0.0.1:8765/api/llm/local/nodes/sparkDeux/v1')
        self.assertEqual(who['label'], 'Local (sparkDeux)')


class LateReviewTests(ReviewFixture, unittest.TestCase):
    def test_a_review_late_by_six_hours_stops_holding_the_task(self):
        R.record_result(self.item, self.run)
        self.assertIn('Waiting', R.gate(self.item))
        with closing(R.connect()) as db, db:
            db.execute('UPDATE reviews SET created=? WHERE key=?', (time.time() - 7 * 3600, self.key))
        self.assertIsNone(R.gate(self.item), 'a late review no longer blocks the next dispatch')
        self.assertEqual(R.result(self.key)['state'], 'pending', 'the review itself still runs later')
        with closing(R.connect()) as db, db:
            db.execute('UPDATE reviews SET created=? WHERE key=?', (time.time() - R.REVIEW_WAIT_MAX_S + 600, self.key))
        self.assertIn('Waiting', R.gate(self.item), 'a recent result still waits for its review')


class StaleRunReviews(ReviewFixture, unittest.TestCase):
    def test_a_run_review_past_the_hold_limit_is_retired_once_a_newer_run_exists(self):
        """232 pending run reviews at 14 hours (2026-10-19): one past the hold limit whose request already ran again
        is superseded; the newer one and the only run of another request stay pending."""
        rid = self.item['request_id']
        old, newer, lone = dict(self.run, id='2' * 32), dict(self.run, id='3' * 32), dict(self.run, id='4' * 32)
        R.enqueue('run:' + old['id'], 'run', rid, {'run': old, 'item': self.item})
        R.enqueue('run:' + newer['id'], 'run', rid, {'run': newer, 'item': self.item})
        R.enqueue('run:' + lone['id'], 'run', 'b' * 16, {'run': lone, 'item': dict(self.item, request_id='b' * 16)})
        now = time.time()
        with closing(R.connect()) as db, db:
            for key in ('run:' + old['id'], 'run:' + lone['id']):
                db.execute("UPDATE reviews SET created=? WHERE key=?", (now - R.REVIEW_WAIT_MAX_S - 60, key))
            self.assertEqual(R.retire_stale_run_reviews(db, now), 1)
            self.assertEqual(R.retire_stale_run_reviews(db, now), 0, 'idempotent')
            states = {k: s for k, s in db.execute("SELECT key, state FROM reviews").fetchall()}
            error = db.execute("SELECT error FROM reviews WHERE key=?", ('run:' + old['id'],)).fetchone()[0]
        self.assertEqual(states['run:' + old['id']], 'superseded')
        self.assertIn('newer run of this request', error)
        self.assertEqual(states['run:' + newer['id']], 'pending', 'the newer run review stays')
        self.assertEqual(states['run:' + lone['id']], 'pending', 'old but the only run of its request: still reviewed')


class InboxFirstReviews(ReviewFixture, unittest.TestCase):
    def test_runs_of_inbox_lane_requests_are_reviewed_before_favorites(self):
        """2026-10-19: three operator tickets waited 2 to 4 hours behind 200 favorite runs; the pick now prefers
        runs of the queue's inbox-lane requests, then the previous newest / oldest order."""
        fav, op = 'f' * 16, 'a' * 16
        for n, (rid, started) in enumerate(((fav, '2026-10-19T12:00:00+00:00'), (op, '2026-10-19T10:00:00+00:00'),
                                             (fav, '2026-10-19T11:00:00+00:00'))):
            run = dict(self.run, id=str(n + 5) * 32, started_at=started)
            R.enqueue('run:' + run['id'], 'run', rid, {'run': run, 'item': self.item | {'request_id': rid}})
        (self.root / 'work-queue.json').write_text(json.dumps({'items': {'inbox:' + op: {'request_id': op, 'lane': 'inbox'},
                                                                          'favorite:' + fav: {'request_id': fav, 'lane': 'favorite'}}}))
        self.assertEqual(R.inbox_requests(), {op})
        now = time.time()
        with closing(R.connect()) as db:
            self.assertEqual(R.next_review(db, 'run', now, newest=True, first=R.inbox_requests())['request_id'], op,
                             'the operator run goes first although it is the oldest')
            self.assertEqual(R.next_review(db, 'run', now, newest=True)['request_id'], fav, 'without the lane: newest first')
            self.assertEqual(R.next_review(db, 'run', now, newest=True)['key'], 'run:' + '5' * 32)
            self.assertEqual(R.next_review(db, 'run', now, first={'../x'})['key'], 'run:' + '5' * 32, 'odd ids are ignored')
        (self.root / 'work-queue.json').write_text('{not json')
        self.assertEqual(R.inbox_requests(), set(), 'an unreadable queue keeps the previous order')
        self.assertEqual(R.priority_requests(), [])

    def test_the_queue_priority_order_decides_among_inbox_runs(self):
        """The inbox lane holds every standing request; the operator's priority list order comes first within it."""
        a, b, c = 'a' * 16, 'b' * 16, 'c' * 16
        for n, (rid, started) in enumerate(((a, '2026-10-19T12:00:00+00:00'), (b, '2026-10-19T11:00:00+00:00'),
                                             (c, '2026-10-19T10:00:00+00:00'))):
            run = dict(self.run, id=str(n + 5) * 32, started_at=started)
            R.enqueue('run:' + run['id'], 'run', rid, {'run': run, 'item': self.item | {'request_id': rid}})
        (self.root / 'work-queue.json').write_text(json.dumps({
            'priority': [c, b, '../bad'], 'items': {('inbox:' + r): {'request_id': r, 'lane': 'inbox'} for r in (a, b, c)}}))
        self.assertEqual(R.priority_requests(), [c, b])
        now = time.time()
        with closing(R.connect()) as db:
            pick = R.next_review(db, 'run', now, newest=True, first=R.inbox_requests(), ordered=R.priority_requests())
            self.assertEqual(pick['request_id'], c, 'first in the priority list, although the oldest run')
            self.assertEqual(R.next_review(db, 'run', now, newest=True, first=R.inbox_requests())['request_id'], a,
                             'without the list the newest inbox run comes first')
