from pso_owned_evidence import original_test_path
"""Native gate observations must reach the planner without granting input authority."""
import copy
import json
from pathlib import Path

import pytest

from gbox import pso_coop as C


def context():
    players = {slot: dict(class_='TObjPlayer', room=11, x=0., y=0., z=0.,
                         hp=40, hp_max=40) for slot in (1, 2)}
    return {'existing_buddies': True, 'awaiting_entry': False, 'native_state': {
        'verified': True, 'phase': 14, 'episode': 1, 'floor': 1,
        'players': players, 'entities': []}}


def gate(cls='TObjDoor', **changes):
    return dict(kind='gate', **{'class': cls}, entity_id=16390, room=11,
                x=50., y=0., z=60., ptr='80DA0000') | changes


def test_actual_profile_gate_classes_are_available_as_observations():
    system = Path(__file__).resolve().parents[1]
    profile = json.loads((system / 'profiles/pso-gc-plus-us.json').read_text())
    classes = next(k for k in profile['entities']['kinds'] if k['name'] == 'gate')['name_prefix']
    data = context()
    data['native_state']['entities'] = [gate(cls, entity_id=16390+i) for i, cls in enumerate(classes)]
    before = copy.deepcopy(data)
    prompt, compact = C.planner_input(data)
    assert prompt.startswith('CURRENT VERIFIED FIELD: ') and C.FIELD_PROMPT in prompt
    assert {e['class'] for e in compact['nearby_native_landmarks']} == set(classes)
    assert all(e['kind'] == 'gate' for e in compact['nearby_native_landmarks'])
    assert 'actions' not in compact and 'goals' not in compact
    assert 'ptr' not in repr(compact)
    assert data == before


@pytest.mark.parametrize('change', [
    {'room': 12}, {'x': 301., 'z': 0.}, {'y': 15.01}, {'x': float('nan')},
    {'z': float('inf')}, {'x': True}, {'kind': 'enemy'}, {'kind': 'npc'}])
def test_unrelated_or_invalid_gate_rows_remain_excluded(change):
    data = context()
    data['native_state']['entities'] = [gate(**change)]
    _, compact = C.planner_input(data)
    assert compact['nearby_native_landmarks'] == []


def test_objects_and_gate_limit_remain_bounded():
    data = context()
    data['native_state']['entities'] = [gate(entity_id=16390+i) for i in range(40)]
    data['native_state']['entities'].insert(0, gate('TObjCityDoor_Warp', kind='object', entity_id=16405))
    _, compact = C.planner_input(data)
    assert len(compact['nearby_native_landmarks']) == 32
    assert compact['nearby_native_landmarks'][0]['entity_id'] == 16390
    assert any(e['kind'] == 'object' for e in compact['nearby_native_landmarks'])


def test_unverified_state_does_not_gain_compact_gate_authority():
    data = context()
    data['native_state'].update(verified=False, entities=[gate()])
    prompt, compact = C.planner_input(data)
    assert prompt == C.PROMPT and compact['native_state']['verified'] is False
