from pso_owned_evidence import original_test_path
"""Actual Forest spawn context and constrained transport; no game inputs/network."""
from pathlib import Path
from types import SimpleNamespace
import copy
import json

import pytest
from jsonschema import Draft202012Validator, ValidationError
from gbox import pso_coop as C
from test_pso_planner_transport import provider


HERE = original_test_path('planner-error/tests/test_schema_field_context.py').resolve().parents[2]


def forest_context():
    data = json.loads((HERE / 'after_167_player_two-native-readonly.json').read_text())
    state = data['state']
    state['players'] = {int(k): v for k, v in state['players'].items()}
    return {'existing_buddies': True, 'native_state': state, 'awaiting_entry': False}


def plan(**changes):
    return {'thought': 'Continue current observed field path', 'screen': 'gameplay',
            'needs_operator': False, 'actions': [], 'goals': [], **changes}


def test_native_format_is_exact_schema_and_prompt_contains_it(provider):
    planner = provider['planner']
    planner.response_schema = C.PLAN_SCHEMA
    planner(b'current-frame', {})
    path, body = provider['calls'][-1]
    assert path == '/api/chat' and body['format'] == C.PLAN_SCHEMA
    assert 'Response JSON schema:' in body['messages'][0]['content']
    assert '"secs"' in body['messages'][0]['content']


def test_default_shared_planner_remains_json_mode(provider):
    provider['planner'](b'frame', {})
    assert provider['calls'][-1][1]['format'] == 'json'
    assert 'Response JSON schema:' not in provider['calls'][-1][1]['messages'][0]['content']


def test_compatibility_provider_retains_endpoint_with_schema_in_prompt(provider):
    provider['native'] = False
    provider['planner'].response_schema = C.PLAN_SCHEMA
    provider['planner'](b'frame', {})
    path, body = provider['calls'][-1]
    assert path == '/v1/chat/completions'
    assert 'Response JSON schema:' in body['messages'][0]['content'][0]['text']
    assert 'format' not in body


def test_bad_schema_refuses_before_provider_request(provider):
    provider['planner'].response_schema = 'not-a-schema'
    with pytest.raises(ValueError, match='schema must be an object'):
        provider['planner'](b'frame', {})
    assert provider['calls'] == []


@pytest.mark.parametrize('bad_action', [
    {'player': 1, 'keys': ['move_to', '16405'], 'secs': .5},
    {'player': 2, 'keys': ['dright']},
    {'player': 1, 'keys': ['lright']},
    {'player': 3, 'keys': ['lup'], 'secs': .4},
    {'player': 1, 'keys': ['a', 'b', 'x', 'y'], 'secs': .4},
    {'player': 1, 'keys': ['lup'], 'secs': .7},
])
def test_schema_rejects_actual_invalid_command_contract(bad_action):
    invalid = plan(actions=[bad_action])
    with pytest.raises(ValidationError):
        Draft202012Validator(C.PLAN_SCHEMA).validate(invalid)
    # The real pre-input parser remains an independent check even if a provider
    # returns invalid data despite its requested schema.
    with pytest.raises((ValueError, KeyError)):
        C.actions(invalid)


def test_valid_commands_and_actual_landmark_goals_preserve_independent_limits():
    state = forest_context()['native_state']
    goal = {'player': 1, 'x': 450.673, 'z': 420.815, 'room': 16,
            'reason': 'observed same-room supply container, not a verified exit'}
    valid = plan(actions=[{'player': 2, 'keys': ['lup'], 'secs': .3}], goals=[goal])
    Draft202012Validator.check_schema(C.PLAN_SCHEMA)
    Draft202012Validator(C.PLAN_SCHEMA).validate(valid)
    assert C.actions(valid) == [(2, ['lup'], .3)]
    controller = SimpleNamespace(goals={})
    C.Controller.accept_goals(controller, valid, state)
    assert controller.goals[1]['x'] == goal['x']
    controller.goals.clear()
    C.Controller.accept_goals(controller, plan(goals=[goal | {'room': 11}]), state)
    assert controller.goals == {}


def test_actual_forest_context_cannot_be_primed_with_town_route():
    data = forest_context()
    before = copy.deepcopy(data)
    prompt, compact = C.planner_input(data)
    assert prompt.startswith('CURRENT VERIFIED FIELD: ')
    assert '"episode": 1' in prompt.split('\n')[0]
    assert '"floor": 1' in prompt.split('\n')[0]
    assert '"room": 16' in prompt.split('\n')[0]
    assert 'Pioneer 2' not in prompt and 'TOWN EXIT CANDIDATE' not in prompt
    assert 'main transporter destination list' not in prompt
    assert 'Never rename a supply' in prompt
    box = next(e for e in compact['nearby_native_landmarks'] if e['entity_id'] == 16507)
    assert box['class'] == 'TObjContainerItem'
    assert box['room'] == 16 and box['x'] == 583.74
    assert compact['native_enemies_alive'] == 0
    assert compact['initialization_authorized'] is False
    assert data == before


def test_field_does_not_prioritize_town_warp_class():
    data = forest_context()
    data['native_state']['entities'] += [
        {'entity_id': 99999, 'class': 'TObjCityDoor_Warp', 'kind': 'object',
         'room': 16, 'x': 568., 'y': 4., 'z': 550.}]
    _, compact = C.planner_input(data)
    assert compact['nearby_native_landmarks'][0]['entity_id'] != 99999


def test_unverified_field_never_gets_field_prompt():
    data = forest_context()
    data['native_state']['verified'] = False
    prompt, actual = C.planner_input(data)
    assert prompt == C.PROMPT and actual['native_state']['verified'] is False
