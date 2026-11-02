from copy import deepcopy
import json
from gbox import pso_coop as C


def test_unknown_native_state_drops_entire_raster_without_granting_gameplay_authority():
    cells = [[x, z] for x in range(160) for z in range(160)]
    state = {'verified': False, 'phase': 14, 'episode': 1, 'floor': 0,
        'geometry_verified': True, 'geometry_identity': 'observed-layout',
        'diagnostic': 'Collision changed again; reobserve',
        'players': {1: {'ptr': '80100000', 'class': 'TObjPlayer', 'room': 40, 'x': 326.815, 'y': 1., 'z': 25.85},
                    2: {'ptr': '80102000', 'room': 10, 'x': 196., 'y': 0., 'z': 194.}},
        'geometry_players': {2: {'collision_grid': {'floor': cells, 'heights': cells}}},
        'entities': [{'class': 'TObjEnemy', 'kind': 'enemy', 'hp': 56, 'raw_dump': 'large'*10000} for _ in range(100)]}
    context = {'existing_buddies': True, 'initialization_authorized': False, 'native_state': state}
    prior = deepcopy(context)
    prompt, compact = C.planner_input(context)
    assert prompt == C.PROMPT
    assert compact['native_state']['verified'] is False
    assert compact['native_state']['diagnostic'] == state['diagnostic']
    assert compact['initialization_authorized'] is False
    assert compact['native_state']['geometry_payload_omitted'] is True
    assert compact['native_state']['entities_omitted'] == 36
    assert len(json.dumps(compact)) < 12000
    assert context == prior


def test_missing_and_loading_observations_remain_unknown():
    for state in ({}, {'travelling': True, 'verified': False, 'phase': 9}):
        prompt, compact = C.planner_input({'native_state': state})
        assert prompt == C.PROMPT
        assert compact['native_state'].get('verified') is not True
        assert compact['native_state']['players'] == {}


def test_nonfinite_positions_and_unbounded_strings_are_not_serialized():
    value = C._planner_native_observation({'verified': False, 'diagnostic': 'x'*10000,
        'players': {1: {'class': 'x'*10000, 'x': float('nan'), 'z': float('inf')}},
        'entities': [{'class': 'x'*10000}]*1000})
    assert len(value['diagnostic']) == 400
    assert 'x' not in value['players'][1] and 'z' not in value['players'][1]
    assert len(value['entities']) == 64
    json.dumps(value, allow_nan=False)
