import json

import pytest

from gbox.live_request import (bind_target, is_live_change_request, is_mutation,
                               phase_for_tool, request_outcome)
from gbox.custom_build_unlocks import CATEGORIES


SID = 'worker-current'
CONTEXT = {'session_id': SID, 'game_id': 'soulcalibur', 'mod': 'sonic-v4'}
SESSION = {'session_id': SID, 'game_id': 'soulcalibur', 'mod': 'sonic-v4',
           'worker_id': 'worker', 'state': 'running', 'title': 'SoulCalibur (USA)',
           'adapter': 'retroarch', 'platform': 'dreamcast'}


@pytest.mark.parametrize('text', ['unlock all characters, stages and everything',
    'Please give me every weapon', 'Can you make my attacks never miss?',
    'I want infinite health', 'Change everyone into Sonic', 'Go to the next checkpoint',
    'Unlimited ammo', 'Infinite health', 'Never miss', 'Walk through walls',
    'Walk through any door', 'Map this face', 'Remap this face', 'Blend this face',
    'Equip the pistol', 'Upgrade my weapon', 'Max my health', 'Bypass the laser field'])
def test_live_game_instructions_are_required_changes(text):
    assert is_live_change_request(text, CONTEXT)
    assert not is_live_change_request(text, {})


@pytest.mark.parametrize('text', ['Hello!', 'Thanks', 'How do I unlock everyone?',
    'What characters are unlockable?', 'Why is the window black?',
    'Open the library', 'Find an unlock code', 'Search for Sonic', 'Show models',
    'Launch SoulCalibur', 'Sort my games by recently played', 'Analyze the executable in Ghidra',
    'Pause', 'Resume the game', 'Yes', 'Continue', 'Inspect textures',
    'How do I map this face?', 'What weapon can I equip?', 'Why do my attacks miss?'])
def test_facts_greetings_navigation_are_not_mutations_even_with_client_hint(text):
    assert not is_live_change_request(text, CONTEXT | {'live_edit': True})


def test_client_hint_neither_forces_nor_disables_an_explicit_mutation_goal():
    assert not is_live_change_request('All fighters, please', CONTEXT | {'live_edit': True})
    assert is_live_change_request('unlock everyone', CONTEXT | {'live_edit': False})


@pytest.mark.parametrize('sessions', [[], [SESSION | {'state': 'ended'}]])
def test_stale_client_false_hint_cannot_evade_exact_target_failure(sessions):
    context = CONTEXT | {'live_edit': False}
    assert is_live_change_request('unlock all', context)
    with pytest.raises(ValueError, match='ended or changed'):
        bind_target(context, sessions)
    assert request_outcome('unlock all', context, [])['required']
    assert not request_outcome('unlock all', context, [])['verified']


def test_exact_binding_uses_canonical_identity_without_changing_input():
    result = bind_target(CONTEXT | {'local_worker': 'i9-NUC'}, [SESSION])
    assert result == {k: SESSION[k] for k in ('session_id', 'game_id', 'title', 'mod', 'worker_id', 'adapter', 'platform')} | {'game_title': SESSION['title']}
    assert CONTEXT == {'session_id': SID, 'game_id': 'soulcalibur', 'mod': 'sonic-v4'}


@pytest.mark.parametrize('sessions', [[], [SESSION | {'state': 'ended'}],
    [SESSION | {'ended': 123}], [SESSION, SESSION],
    [SESSION | {'session_id': 'worker-other', 'game_id': 'soulcalibur'}]])
def test_binding_never_follows_new_game_or_ambiguous_identity(sessions):
    with pytest.raises(ValueError, match='ended or changed'):
        bind_target(CONTEXT, sessions)


@pytest.mark.parametrize('key,value', [('game_id', 'other'), ('mod', ''), ('worker_id', 'other')])
def test_binding_rejects_context_mismatch(key, value):
    with pytest.raises(ValueError, match='changed'):
        bind_target(CONTEXT | {key: value}, [SESSION])


def test_binding_rejects_changed_pinned_mod_even_when_new_context_is_valid():
    with pytest.raises(ValueError, match='pinned live target'):
        bind_target(CONTEXT | {'live_target': CONTEXT | {'mod': 'old'}}, [SESSION])


def event_pair(name, args, result):
    return [{'type': 'tool_call', 'name': name, 'args': args},
            {'type': 'tool_result', 'name': name, 'text': json.dumps(result)}]


def coverage(categories=CATEGORIES):
    return {'session_id': SID, 'game_id': 'soulcalibur', 'mod': 'sonic-v4',
            'inventory_complete': True, 'runtime_artifacts': ['a' * 64],
            'categories': {category: {'status': 'unlocked', 'entries': [category + '-entry'],
                                     'evidence': ['a' * 64]} for category in categories}}


def native(result=None, **args):
    return event_pair('run_tool', {'name': 'game_live_controls', 'input':
        {'session_id': SID, 'game_id': 'soulcalibur', 'op': 'apply', 'action': 'unlock_all', **args}},
        result if result is not None else {'state': 'succeeded', 'output': {'result': {
            'verified': True, 'unlock_coverage': coverage()}}})


def outcome(events, context=CONTEXT):
    return request_outcome('unlock all characters, stages and everything', context, events)


@pytest.mark.parametrize('events', [[],
    [{'type': 'assistant', 'text': 'Done! Everything is unlocked.'}],
    event_pair('session_info', {'session_id': SID}, {'verified': True}),
    event_pair('look_at_screen', {'session_id': SID}, {'frame': 'image', 'verified': True}),
    event_pair('re_study', {'session_id': SID}, {'verified': True}),
    event_pair('rea_annotate_native_function', {'session_id': SID}, {'verified': True})])
def test_prose_analysis_and_successful_reads_never_complete_goal(events):
    assert outcome(events)['required']
    assert not outcome(events)['verified']


def test_native_verified_result_can_complete_exact_session_goal():
    assert outcome(native()) == {'required': True, 'verified': True, 'reason': ''}


@pytest.mark.parametrize('result', [
    {'state': 'failed', 'output': {'result': {'verified': True}}},
    {'state': 'succeeded', 'output': {'result': {'verified': False}}},
    {'state': 'queued', 'output': {'result': {'verified': True}}},
    {'result': {'status': 'unsupported', 'verified': True}},
    {'output': {'result': {'error': 'game ended', 'verified': True}}},
    {'result': {'status': 'overlay', 'verified': True}},
    {'result': {'verified': True, 'session_id': 'worker-new'}},
    {'result': {'verified': True, 'game_id': 'other'}},
    {'result': {'verified': True, 'mod': 'old'}},
    {'result': {'verified': True, 'worker_id': 'other'}},
    {'verified': True, 'result': '{"state":"failed"}'},
    {'state': 'succeeded'}, {}])
def test_failed_pending_unverified_or_wrong_target_never_completes(result):
    assert not outcome(native(result))['verified']


def test_correct_worker_is_not_enough_for_another_session():
    assert not outcome(native(session_id='worker-other'))['verified']


def test_last_pending_change_invalidates_earlier_verified_result():
    assert not outcome(native() + [{'type': 'tool_call', 'name': 'auf_live',
        'args': {'session_id': SID, 'op': 'give_item', 'item': 'q-laser'}}])['verified']


def test_identical_retry_can_recover_with_new_command_nonce():
    failed = native({'state': 'failed', 'error': 'expired'}, command_id='old', expires=1)
    assert outcome(failed + native(command_id='new', expires=2))['verified']
    assert not outcome(native() + native({'state': 'running'}))['verified']


def test_raw_write_needs_semantic_goal_proof_not_byte_readback():
    events = event_pair('write_memory', {'session_id': SID, 'address': 100, 'hex_bytes': '01'},
        {'state': 'succeeded', 'result': {'verified': True}})
    read = event_pair('read_memory', {'session_id': SID}, {'verified': True, 'hex': '01'})
    assert not outcome(events + read)['verified']
    proof = event_pair('verify_live_goal', {'session_id': SID},
        {'goal_verified': True, 'session_id': SID, 'evidence': ['actual-menu-state-artifact'],
         'unlock_coverage': coverage()})
    assert outcome(events + proof)['verified']
    assert not outcome(proof + events)['verified']


def test_semantic_proof_cannot_rescue_failed_mutation_or_wrong_target():
    proof = event_pair('verify_live_goal', {'session_id': SID},
        {'goal_verified': True, 'session_id': SID, 'evidence': ['artifact']})
    assert not outcome(native({'state': 'failed'}) + proof)['verified']
    wrong = event_pair('verify_live_goal', {'session_id': 'worker-other'},
        {'goal_verified': True, 'session_id': 'worker-other', 'evidence': ['artifact']})
    assert not outcome(native({'state': 'succeeded'}) + wrong)['verified']


def test_explicit_negative_goal_evidence_revokes_earlier_native_success():
    proof = event_pair('verify_live_goal', {'session_id': SID},
        {'goal_verified': False, 'session_id': SID, 'evidence': ['still-locked-menu']})
    assert not outcome(native() + proof)['verified']
    assert outcome(native() + proof + native())['verified']


def test_excessively_nested_result_envelopes_fail_closed():
    result = {'state': 'failed'}
    for _ in range(25):
        result = {'verified': True, 'result': result}
    assert not outcome(native(result))['verified']


@pytest.mark.parametrize('args,result', [
    ({'action': 'unlock_taki'}, {'verified': True}),
    ({'action': 'one_flag'}, {'verified': True, 'address': 123, 'value': 1}),
    ({'action': 'unlock_all'}, {'verified': True}),
    ({'action': 'unlock_all'}, {'verified': True, 'coverage': 'everything'}),
    ({'action': 'unlock_all'}, {'verified': True, 'unlock_coverage': coverage(['characters'])}),
])
def test_broad_goal_needs_complete_runtime_categories_not_action_name_or_one_write(args, result):
    assert not outcome(native(result, **args))['verified']


@pytest.mark.parametrize('category', CATEGORIES)
def test_everything_requires_each_inventory_category(category):
    missing = coverage([c for c in CATEGORIES if c != category])
    result = outcome(native({'verified': True, 'unlock_coverage': missing}))
    assert not result['verified'] and category in result['reason']


def test_quantified_specific_goal_requires_all_requested_categories_including_hidden_fighters():
    text = 'Unlock all characters and stages'
    proof = {'verified': True, 'unlock_coverage': coverage(['characters', 'hidden_characters', 'stages'])}
    assert request_outcome(text, CONTEXT, native(proof))['verified']
    del proof['unlock_coverage']['categories']['hidden_characters']
    assert not request_outcome(text, CONTEXT, native(proof))['verified']


@pytest.mark.parametrize('update', [
    {'inventory_complete': False}, {'runtime_artifacts': []}, {'runtime_artifacts': ['not-an-artifact']},
    {'session_id': 'worker-other'}, {'game_id': 'other'}, {'mod': 'other'},
])
def test_unlock_coverage_is_complete_evidenced_and_exact_build_bound(update):
    assert not outcome(native({'verified': True, 'unlock_coverage': coverage() | update}))['verified']


def test_unknown_or_partial_category_is_not_coverage_but_evidenced_absence_is():
    proof = coverage()
    proof['categories']['extras'] = {'status': 'research_pending', 'entries': [], 'evidence': ['a' * 64]}
    assert not outcome(native({'verified': True, 'unlock_coverage': proof}))['verified']
    proof['categories']['extras']['status'] = 'not_present'
    assert outcome(native({'verified': True, 'unlock_coverage': proof}))['verified']


def test_later_relock_mutation_invalidates_prior_full_unlock_coverage():
    assert not outcome(native() + native({'verified': True}, on=False))['verified']


def test_single_named_unlock_does_not_need_an_all_content_inventory():
    assert request_outcome('Unlock Taki', CONTEXT, native({'verified': True}, action='unlock_taki'))['verified']


def test_full_inventory_is_not_proof_that_requested_exclusions_were_preserved():
    assert not request_outcome('Unlock everything except the stages', CONTEXT, native())['verified']


def test_unbound_goal_is_pending_and_nonmutation_has_no_required_result():
    assert not outcome(native(), {'session_id': SID})['verified']
    assert request_outcome('What is this game?', CONTEXT, native()) == {
        'required': False, 'verified': False, 'reason': ''}


def test_actual_tools_receive_meaningful_phases_without_host_analysis_mutation():
    assert phase_for_tool('session_info', {}) == 'attach'
    assert phase_for_tool('run_tool', {'name': 'game_live_controls', 'input': {'op': 'apply'}}) == 'apply'
    assert phase_for_tool('ghidra_bridge', {'op': 'open'}) == 'research'
    assert phase_for_tool('look_at_screen', {}) == 'verify'
    assert not is_mutation('rea_annotate_native_function', {})
    assert not is_mutation('game_live_controls', {'op': 'inspect'})
    assert not is_mutation('gta_live', {'op': 'wanted'})


@pytest.mark.parametrize('goal', ['Give me every weapon', 'Give me all the items',
    'Replace everyone with Sonic', 'Spawn ten pedestrians', 'Give me a pistol and armor',
    'Make me invincible and give unlimited ammo', 'Invincible and unlimited ammo'])
def test_quantified_or_independent_goals_cannot_complete_from_one_native_action(goal):
    assert is_live_change_request(goal, CONTEXT)
    events = event_pair('pso_mods', {'session_id': SID, 'op': 'give', 'item': 'pistol'},
        {'verified': True})
    assert not request_outcome(goal, CONTEXT, events)['verified']


def test_exact_goal_verifier_with_real_evidence_can_complete_compound_change():
    goal = 'Give me every weapon'
    change = event_pair('pso_mods', {'session_id': SID, 'op': 'give', 'item': 'all'}, {'verified': True})
    proof = event_pair('verify_live_goal', {'session_id': SID},
        {'goal_verified': True, 'session_id': SID, 'goal': goal, 'evidence': ['a' * 64]})
    assert request_outcome(goal, CONTEXT, change + proof)['verified']


@pytest.mark.parametrize('update', [{'goal': 'Give me a pistol'}, {'goal': None},
    {'evidence': []}, {'evidence': ['an unsupported claim']}, {'session_id': 'worker-other'}])
def test_quantified_goal_proof_must_match_the_exact_request_and_evidence(update):
    goal = 'Give me every weapon'
    change = event_pair('pso_mods', {'session_id': SID, 'op': 'give'}, {'verified': True})
    proof = event_pair('verify_live_goal', {'session_id': SID},
        {'goal_verified': True, 'session_id': SID, 'goal': goal, 'evidence': ['a' * 64]} | update)
    assert not request_outcome(goal, CONTEXT, change + proof)['verified']


def test_unlock_coverage_does_not_also_prove_unlimited_ammunition():
    goal = 'Unlock everything and give unlimited ammo'
    assert not request_outcome(goal, CONTEXT, native())['verified']
    proof = event_pair('verify_live_goal', {'session_id': SID},
        {'goal_verified': True, 'session_id': SID, 'goal': goal,
         'evidence': ['a' * 64], 'unlock_coverage': coverage()})
    assert request_outcome(goal, CONTEXT, native() + proof)['verified']
