"""Completion regressions for the recorded failed cheats/OoT requests."""
import copy
import json

import pytest

from gbox.agent import ChatHub, _modifies_game
from gbox.agent_contracts import required_operation_outcome


def operation(name, args, result):
    return [{'type': 'tool_call', 'name': name, 'args': args},
            {'type': 'tool_result', 'name': name, 'text': json.dumps(result)}]


def run_hub(events, reuse=False):
    class Store:
        def __init__(self):
            self.chat = {'id': 'chat', 'events': [], 'messages': [], 'busy': True, 'queue': []}
        def get(self, *_):
            return copy.deepcopy(self.chat)
        def put(self, _kind, _cid, value):
            self.chat = copy.deepcopy(value)
    class FakeAgent:
        def run(self, messages, emit, context):
            for event in events:
                emit(event)
            emit({'type': 'assistant', 'text': 'The attempted operation is described here.'})
            return {'usage': {'in': 5, 'out': 3}, 'tools': {}}
    actions = []
    def request_api(action, data):
        actions.append((action, data))
        return 'request'
    hub = ChatHub(Store(), lambda _: FakeAgent())
    hub._gap_report = lambda *_: None
    context = {'resolve_auto_report': True, 'request_id': 'original'} if reuse else {}
    hub._turn('chat', 'Perform the requested operation', context, request_api)
    return actions


def vr_cheat_failure():
    # Exact operation and error recorded in chat 919fc0554a1540ac, turn 0.
    return (operation('cheats', {'op': 'enable', 'session_id': 'worker-vr', 'codes': ['800E556C 1000']},
                      {'state': 'failed', 'error': 'ValueError: index required'}) +
            operation('cheats', {'op': 'list', 'session_id': 'worker-vr'},
                      {'source': None, 'count': 0, 'cheats': []}) +
            operation('memory_search', {'op': 'start', 'session_id': 'worker-vr', 'value': 0},
                      {'scanned_mb': 0.0, 'candidates': 0}))


@pytest.mark.parametrize('events', [vr_cheat_failure(),
    operation('zelda_oot', {'op': 'skip_deku_tree', 'session_id': 'worker-oot'},
              {'state': 'failed', 'error': 'RuntimeError: no OoT v1.2 save loaded (title screen? other ROM revision?) - load a file first'}) +
    operation('look_at_screen', {'session_id': 'worker-oot'}, {'frame': 'captured'}),
    operation('zelda_oot', {'op': 'goto', 'place': 'end of the shadow temple', 'session_id': 'worker-oot'},
              {'state': 'failed', 'error': 'no such session; running sessions: none'}) +
    operation('list_sessions', {}, [])])
@pytest.mark.parametrize('reuse', [False, True])
def test_actual_failed_required_operations_stay_pending_after_successful_reads(events, reuse):
    actions = run_hub(events, reuse)
    status = next(data for action, data in actions if action == 'status')
    assert status['status'] == 'in_progress'
    assert 'did not complete' in status['note']


@pytest.mark.parametrize('name,args,result', [
    ('cheats', {'op': 'enable', 'session_id': 'worker-vr', 'index': 0}, {'enabled': True}),
    ('cheats', {'op': 'disable', 'session_id': 'worker-vr', 'index': 0}, {'enabled': False}),
    ('cheats', {'op': 'add', 'session_id': 'worker-vr', 'codes': ['800E556C 1000']}, {'enabled': True}),
    ('write_memory', {'session_id': 'worker-vr', 'address': '0x1000', 'hex_bytes': '01'},
     {'state': 'succeeded', 'error': None, 'result': {'written': True}}),
    ('cheats', {'op': 'list', 'session_id': 'worker-vr'}, {'source': None, 'count': 0, 'cheats': []}),
    ('session_info', {'session_id': 'worker-vr'}, {'running': True, 'error': None}),
    ('web_search', {'query': 'mission'}, {'results': []}),
])
def test_successful_required_changes_and_informational_requests_keep_their_completion(name, args, result):
    actions = run_hub(operation(name, args, result))
    assert next(data for action, data in actions if action == 'status')['status'] == 'done'


def test_exact_successful_retry_recovers_a_transient_write_failure():
    args = {'session_id': 'worker-vr', 'address': '0x1000', 'hex_bytes': '01'}
    events = (operation('write_memory', args, {'state': 'failed', 'error': 'temporary debugger disconnect'}) +
              operation('write_memory', args, {'state': 'succeeded', 'error': None, 'result': {'written': True}}))
    assert not required_operation_outcome(events, _modifies_game)['unresolved']
    assert next(data for action, data in run_hub(events) if action == 'status')['status'] == 'done'


def test_correct_add_with_the_same_code_and_session_recovers_the_malformed_enable():
    events = vr_cheat_failure() + operation('cheats', {'op': 'add', 'session_id': 'worker-vr',
                                                      'codes': ['800E556C 1000'], 'desc': 'mission code'},
                                          {'index': 0, 'enabled': True})
    assert not required_operation_outcome(events, _modifies_game)['unresolved']


@pytest.mark.parametrize('recovery', [
    operation('cheats', {'op': 'add', 'session_id': 'worker-other', 'codes': ['800E556C 1000']}, {'enabled': True}),
    operation('cheats', {'op': 'add', 'session_id': 'worker-vr', 'codes': ['800E5538 FFFF']}, {'enabled': True}),
    operation('write_memory', {'session_id': 'worker-vr', 'address': '0x1000', 'hex_bytes': '01'}, {'state': 'succeeded'}),
])
def test_a_different_target_code_or_operation_cannot_clear_the_failed_cheat(recovery):
    assert required_operation_outcome(vr_cheat_failure() + recovery, _modifies_game)['unresolved']


def test_another_write_address_cannot_clear_a_failed_required_write():
    events = (operation('write_memory', {'session_id': 'worker-vr', 'address': '0x1000', 'hex_bytes': '01'},
                        {'state': 'failed', 'error': 'write rejected'}) +
              operation('write_memory', {'session_id': 'worker-vr', 'address': '0x2000', 'hex_bytes': '01'},
                        {'state': 'succeeded'}))
    assert required_operation_outcome(events, _modifies_game)['unresolved']


def test_repeat_of_a_known_success_preserves_completion_without_crediting_a_failed_repeat():
    args = {'session_id': 'worker-vr', 'address': '0x1000', 'hex_bytes': '01'}
    success = operation('write_memory', args, {'state': 'succeeded', 'result': {'written': True}})
    repeat = operation('write_memory', args, {'repeat': True, 'previous': '{"state":"succeeded"}'})
    assert not required_operation_outcome(success + repeat, _modifies_game)['unresolved']
    failed = operation('write_memory', args, {'state': 'failed', 'error': 'write rejected'})
    assert required_operation_outcome(success + failed + repeat, _modifies_game)['unresolved']


@pytest.mark.parametrize('name,args,result', [
    ('cheats', {'op': 'enable', 'index': 0, 'session_id': 'worker-vr'}, {'enabled': False}),
    ('cheats', {'op': 'disable', 'index': 0, 'session_id': 'worker-vr'}, {'enabled': True}),
    ('write_memory', {'session_id': 'worker-vr', 'address': '0x1000', 'hex_bytes': '01'},
     {'state': 'succeeded', 'result': {'verified': False}}),
])
def test_explicit_incomplete_operation_flags_cannot_mark_the_requested_change_done(name, args, result):
    assert next(data for action, data in run_hub(operation(name, args, result)) if action == 'status')['status'] == 'in_progress'


@pytest.mark.parametrize('result', [
    {'state': 'failed', 'result': {'verified': True}},
    {'state': 'succeeded', 'output': {'result': {'error': 'write failed'}}},
    {'state': 'queued'}, {'state': 'running'},
    {'repeat': True, 'previous': '{"state":"failed","error":"write rejected"}'},
])
def test_failed_wrappers_pending_jobs_and_repeat_notifications_do_not_complete_required_changes(result):
    events = operation('write_memory', {'session_id': 'worker-vr', 'address': '0x1000', 'hex_bytes': '01'}, result)
    assert next(data for action, data in run_hub(events) if action == 'status')['status'] == 'in_progress'


def test_typed_run_tool_wrapper_cannot_bypass_the_known_required_operation_guard():
    events = operation('run_tool', {'name': 'cheats', 'input': {'op': 'enable', 'index': 0,
                                                             'session_id': 'worker-vr'}},
                       {'state': 'failed', 'error': 'worker unavailable'})
    assert required_operation_outcome(events, _modifies_game)['unresolved']


def test_a_missing_required_result_is_not_hidden_by_a_later_read():
    events = [{'type': 'tool_call', 'name': 'write_memory',
               'args': {'session_id': 'worker-vr', 'address': '0x1000', 'hex_bytes': '01'}}]
    events += operation('session_info', {'session_id': 'worker-vr'}, {'running': True})
    assert required_operation_outcome(events, _modifies_game)['unresolved']


def test_read_only_failures_are_outside_the_narrow_game_change_guard():
    assert not required_operation_outcome(operation('web_search', {}, {'error': 'search unavailable'}),
                                         _modifies_game)['unresolved']


def test_no_tool_calls_does_not_block_an_informational_answer():
    assert next(data for action, data in run_hub([]) if action == 'status')['status'] == 'done'
