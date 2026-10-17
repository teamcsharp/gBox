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


EXPORT = {'game_id': 're2', 'op': 'export', 'mods': ['sonic_cast']}
EXPORT_RESULT = {'game_id': 're2', 'image': 'modified.iso', 'rel_dir': 'exports/re2/sonic_cast',
                 'cheat_files': [], 'patches': []}
BUILD = {'game_id': 're5', 'op': 'build', 'name': 'mario_cast',
         'changes': {'PS3_GAME/USRDIR/player.arc': {'patch': [{'offset': 0, 'hex': '01'}]}}}
BUILD_RESULT = {'mod': 'mario_cast', 'dir': '/cache/mods/re5/mario_cast',
                'files': ['PS3_GAME/USRDIR/player.arc']}


@pytest.mark.parametrize('name,args', [('rom_export', EXPORT), ('rom_export', {'game_id': 're2'}), ('file_mod', BUILD)])
@pytest.mark.parametrize('result', [
    {'ready': False, 'status': 'needs_selection', 'options': []},
    {'status': 'unsupported', 'reason': 'No native writer'},
    {'state': 'unsupported'}, {'state': 'queued'}, {'state': 'running'},
    {'state': 'failed', 'error': 'ValueError: no mods given'},
    {'state': 'succeeded'}, {'status': 'complete', 'files': [{'path': 'README.txt', 'size': 100}]},
])
def test_file_creation_without_a_deliverable_stays_pending_even_after_successful_read(name, args, result):
    events = operation(name, args, result) + operation('list_sessions', {}, [])
    assert next(data for action, data in run_hub(events) if action == 'status')['status'] == 'in_progress'


def test_actual_empty_export_preflight_keeps_chat_request_pending():
    from types import SimpleNamespace
    from gbox.agent import Agent
    plan = {'ready': False, 'status': 'needs_selection', 'options': []}
    stub = SimpleNamespace(_job=lambda *a, **kw: {'state': 'succeeded', 'output': {'result': plan}})
    result = Agent.rom_export(stub, game_id='re2')
    actions = run_hub(operation('rom_export', {'game_id': 're2'}, result))
    assert next(data for action, data in actions if action == 'status')['status'] == 'in_progress'


@pytest.mark.parametrize('name,args,result', [
    ('rom_export', EXPORT, EXPORT_RESULT),
    ('rom_export', EXPORT, EXPORT_RESULT | {'image': 'game/'}),
    ('rom_export', {'game_id': 're2', 'original': True}, EXPORT_RESULT | {'mode': 'original'}),
    ('rom_export', EXPORT, EXPORT_RESULT | {'image': None, 'cheat_files': ['GHAE08.ini']}),
    ('file_mod', BUILD, BUILD_RESULT),
    ('rom_export', EXPORT, {'state': 'succeeded', 'output': {'result': EXPORT_RESULT}}),
    ('file_mod', BUILD, {'state': 'succeeded', 'output': {'result': BUILD_RESULT}}),
])
def test_returned_export_and_build_deliverables_satisfy_file_operation_contract(name, args, result):
    assert next(data for action, data in run_hub(operation(name, args, result)) if action == 'status')['status'] == 'done'


@pytest.mark.parametrize('result', [
    EXPORT_RESULT | {'ready': False}, EXPORT_RESULT | {'state': 'failed'},
    EXPORT_RESULT | {'game_id': 'other_game'}, EXPORT_RESULT | {'image': None},
    EXPORT_RESULT | {'image': None, 'cheat_files': [None]},
    EXPORT_RESULT | {'state': 'succeeded', 'status': 'partial'},
    EXPORT_RESULT | {'rel_dir': 'exports/another_game/sonic_cast'},
])
def test_export_failure_or_wrong_identity_cannot_be_hidden_by_output_fields(result):
    assert required_operation_outcome(operation('rom_export', EXPORT, result), _modifies_game)['unresolved']


@pytest.mark.parametrize('result', [BUILD_RESULT | {'mod': 'another_build'}, BUILD_RESULT | {'files': []}])
def test_build_requires_the_requested_mod_and_changed_files(result):
    assert required_operation_outcome(operation('file_mod', BUILD, result), _modifies_game)['unresolved']


def test_typed_file_creation_and_exact_retry_use_the_same_completion_guard():
    args = {'name': 'rom_export', 'input': EXPORT}
    failed = operation('run_tool', args, {'state': 'failed', 'error': 'worker disappeared'})
    assert required_operation_outcome(failed, _modifies_game)['unresolved']
    assert not required_operation_outcome(failed + operation('run_tool', args, EXPORT_RESULT), _modifies_game)['unresolved']


def test_export_for_another_game_cannot_resolve_the_failed_export():
    events = operation('rom_export', EXPORT, {'state': 'failed'})
    events += operation('rom_export', EXPORT | {'game_id': 'other_game'}, EXPORT_RESULT | {'game_id': 'other_game'})
    assert required_operation_outcome(events, _modifies_game)['unresolved']


@pytest.mark.parametrize('name,args,result', [
    ('rom_export', {'game_id': 're2', 'op': 'plan'}, {'ready': False, 'status': 'needs_selection'}),
    ('rom_export', {'op': 'list'}, {'exports': []}),
    ('file_mod', {'game_id': 're5', 'op': 'list'}, {'mods': []}),
])
def test_file_planning_and_listing_remain_informational(name, args, result):
    assert next(data for action, data in run_hub(operation(name, args, result)) if action == 'status')['status'] == 'done'


def test_file_creation_does_not_become_a_live_mutation_or_bookmark():
    assert not _modifies_game('rom_export', EXPORT)
    assert not _modifies_game('file_mod', BUILD)


def test_export_without_explicit_game_id_preserves_saved_mod_selection():
    args = {'mod_id': 'saved_mod_for_re2'}
    assert not required_operation_outcome(operation('rom_export', args, EXPORT_RESULT), _modifies_game)['unresolved']


def test_file_operation_with_missing_result_stays_pending():
    events = [{'type': 'tool_call', 'name': 'rom_export', 'args': EXPORT}]
    events += operation('rom_export', {'op': 'list'}, {'exports': []})
    assert required_operation_outcome(events, _modifies_game)['unresolved']


def test_agent_short_export_receipt_remains_sufficient():
    from types import SimpleNamespace
    from gbox.agent import Agent
    result = EXPORT_RESULT | {'files': [{'path': 'modified.iso', 'size': 100}]}
    def job(_tool, inp, *_a):
        return {'state': 'succeeded', 'output': {'result': {'ready': True} if inp['op'] == 'plan' else result}}
    short = Agent.rom_export(SimpleNamespace(_job=job), **EXPORT)
    assert 'files' not in short
    assert not required_operation_outcome(operation('rom_export', EXPORT, short), _modifies_game)['unresolved']


def test_not_ready_repeat_cannot_reuse_a_previous_success():
    events = operation('rom_export', EXPORT, EXPORT_RESULT)
    events += operation('rom_export', EXPORT, {'repeat': True, 'ready': False})
    assert required_operation_outcome(events, _modifies_game)['unresolved']


@pytest.mark.parametrize('extra', [
    {'mode': 'original'}, {'status': 'partial'}, {'ready': False},
    {'game_id': 'other_game'}, {'state': 'failed'}, {'error': 'writer failed'},
    {'verified': False}, {'success': False}, {'ok': False}, {'overlay_error': 'native swap unavailable'},
])
def test_short_export_receipt_retains_identity_and_negative_evidence(extra):
    from types import SimpleNamespace
    from gbox.agent import Agent
    result = EXPORT_RESULT | {'files': [{'path': 'modified.iso', 'size': 100}]} | extra
    def job(_tool, inp, *_a):
        return {'state': 'succeeded', 'output': {'result': {'ready': True} if inp['op'] == 'plan' else result}}
    short = Agent.rom_export(SimpleNamespace(_job=job), **EXPORT)
    assert all(short[k] == value for k, value in extra.items())
    assert required_operation_outcome(operation('rom_export', EXPORT, short), _modifies_game)['unresolved']


def test_short_original_export_is_accepted_only_when_explicitly_requested():
    from types import SimpleNamespace
    from gbox.agent import Agent
    args = {'game_id': 're2', 'original': True}
    result = EXPORT_RESULT | {'mode': 'original', 'files': [{'path': 'original.gcz', 'size': 100}]}
    def job(_tool, inp, *_a):
        return {'state': 'succeeded', 'output': {'result': {'ready': True} if inp['op'] == 'plan' else result}}
    short = Agent.rom_export(SimpleNamespace(_job=job), **args)
    assert short['mode'] == 'original' and short['game_id'] == 're2'
    assert not required_operation_outcome(operation('rom_export', args, short), _modifies_game)['unresolved']
    assert required_operation_outcome(operation('rom_export', args | {'original': False}, short), _modifies_game)['unresolved']
    assert required_operation_outcome(operation('rom_export', args, short | {'mode': 'modified'}), _modifies_game)['unresolved']
