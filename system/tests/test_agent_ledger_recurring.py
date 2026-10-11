"""The observed scheduler trigger must not become a fresh persistent request."""
import sys

import pytest

from scripts import agent_ledger as ledger


# An independent copy of the actual six-line scheduled prompt, not a production
# predicate mirror: changing the expected harness text requires explicit review.
REMINDER = '''gBox request review (recurring, set up at the operator's request: "examine the requests I give gBox and how it responds; make sure it has the means to accomplish them").
1. Run: cd //10.89.1.246/ehm_eckx/gBox/system && python scripts/chat_review.py --hours 0.25 --full  (only requests from the last 15 minutes).
2. If there are no new requests, stop quietly with a one-line note.
3. For each new request: judge whether gBox's agent understood the goal, used the right tools, verified, and answered. For every failure, find the root cause (missing tool/capability, bad tool output, prompt rule gap, crash, wrong model behaviour) and fix it in the canonical code on the share (never C:\\_tools\\gBox directly; write patch scripts with the Write tool; validate with ast.parse / jscheck.py). Prefer making the tool capable over adding prompt text. If a fix needs gbox.service restarted, only restart when no chat is busy and no agent/test session needs the Spark (check /api/chat busy flags and running sessions); Windows-worker code changes need the scratchpad sync.ps1 and a worker restart (kill the `-m gbox ... worker` python; the gBox.exe watchdog respawns it) only when the operator isn't mid-request.
4. If gBox gave the operator a wrong or empty result, and the fix is in place, you may re-run the operator's request on their live session ONLY when it's harmless and clearly what they asked for; otherwise just report.
5. Report briefly: requests seen, what failed, what you fixed.'''


@pytest.fixture
def hooked(monkeypatch):
    state = {'session': {'chat_request': 'old-request', 'operator_request': 'old-operator',
                         'since': 1, 'claimed': ['old-claim']}, 'seen': []}
    calls = []
    created = []
    monkeypatch.setattr(ledger, 'load_state', lambda: state)
    monkeypatch.setattr(ledger, 'save_state', lambda value: None)
    monkeypatch.setattr(ledger.time, 'time', lambda: 1000)

    def api(path, body=None):
        calls.append((path, body))
        if path == '/api/requests':
            created.append(body)
            return {'id': f'new-{len(created)}'}
        return []

    monkeypatch.setattr(ledger, 'api', api)
    return state, calls, created


@pytest.mark.parametrize('prompt', [REMINDER, '\n' + REMINDER + '\n', REMINDER.replace('\n', '\r\n')])
def test_actual_scheduled_trigger_skips_creation_and_clears_stale_targets(hooked, prompt):
    state, calls, created = hooked
    ledger.hook_prompt({'session_id': 'session', 'cwd': 'test', 'prompt': prompt})
    assert not created
    assert not any(path.endswith('/status') for path, _ in calls)
    assert state['session'] == {'chat_request': None, 'operator_request': 'old-operator',
                                'since': 1000, 'claimed': []}
    assert {path for path, _ in calls} == {
        '/api/requests?status=open,in_progress&source=app',
        '/api/requests?status=open,in_progress&source=gap'}


def test_stop_after_trigger_cannot_charge_previous_request(hooked, monkeypatch):
    state, calls, _ = hooked
    ledger.hook_prompt({'session_id': 'session', 'prompt': REMINDER})
    monkeypatch.setattr(ledger, 'turn_usage', lambda *args: pytest.fail('no target should read usage'))
    ledger.hook_stop({'session_id': 'session', 'transcript_path': 'not-read'})
    assert not any(path.endswith('/metrics') for path, _ in calls)


@pytest.mark.parametrize('prompt', [
    'Please examine the requests I give gBox and how it responds; make sure it has the means to accomplish them',
    'Create a recurring gBox request review every ten minutes.',
    'gBox request review: the cheat failed; fix the tool and attach the result.',
    REMINDER + '\nReview result: cheats failed with a missing index.',
    REMINDER.replace('5. Report briefly:', '5. I need you to report:'),
    '<agent-message from="worker">A real extraction failed.</agent-message>',
    'gBox auto report: character replacement failed; investigate the preserved game state.',
    'Fix the character selector',
])
def test_operator_requests_changed_templates_and_meaningful_outcomes_still_create(hooked, prompt):
    state, calls, created = hooked
    ledger.hook_prompt({'session_id': 'session', 'prompt': prompt})
    assert len(created) == 1
    assert created[0]['body'] == prompt
    assert state['session']['chat_request'] == 'new-1'
    assert ('/api/requests/new-1/status', {'status': 'in_progress'}) in calls


def test_repeated_trigger_does_not_hide_the_next_operator_request(hooked):
    state, _, created = hooked
    for _ in range(2):
        ledger.hook_prompt({'session_id': 'session', 'prompt': REMINDER})
    ledger.hook_prompt({'session_id': 'session', 'prompt': 'Apply the fix to this report'})
    assert len(created) == 1
    assert not created[0]['automated']
    assert state['session']['operator_request'] == 'new-1'


def test_review_can_explicitly_claim_and_meter_a_real_existing_issue(hooked, monkeypatch):
    state, calls, _ = hooked
    ledger.hook_prompt({'session_id': 'session', 'prompt': REMINDER})
    monkeypatch.setattr(sys, 'argv', ['agent_ledger.py', 'claim', 'actual-issue'])
    ledger.main()
    monkeypatch.setattr(ledger, 'turn_usage', lambda path, since: {
        'tokens_in': 20, 'tokens_out': 7, 'tokens_detail': {'input': 20},
        'tools': {'Read': 1}, 'files': set()})
    monkeypatch.setattr(ledger, 'changed_files', lambda since: set())
    ledger.hook_stop({'session_id': 'session', 'transcript_path': 'review-transcript'})
    metrics = [(path, body) for path, body in calls if path.endswith('/metrics')]
    assert len(metrics) == 1
    assert metrics[0][0] == '/api/requests/actual-issue/metrics'
    assert metrics[0][1]['tokens_in'] == 20 and metrics[0][1]['tokens_out'] == 7
    assert state['session']['operator_request'] == 'old-operator'


def test_review_still_surfaces_new_app_and_gap_reports(hooked, monkeypatch, capsys):
    state, _, created = hooked
    def api(path, body=None):
        if path.endswith('source=app'):
            return [{'id': 'issue', 'number': 5, 'metrics': {}, 'title': 'Native issue',
                     'status': 'open', 'kind': 'text', 'source': 'app', 'messages': []}]
        return []
    monkeypatch.setattr(ledger, 'api', api)
    ledger.hook_prompt({'session_id': 'session', 'prompt': REMINDER})
    assert 'Native issue' in capsys.readouterr().out
    assert state['seen'] == ['issue']
    assert not created
