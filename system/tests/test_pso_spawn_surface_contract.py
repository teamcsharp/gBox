from pso_owned_evidence import original_test_path
"""Actual Forest overlap proofs must be consumable by the installed controller."""
from pathlib import Path
from types import SimpleNamespace
import copy
import json
import struct

import pytest
from gbox import pso_coop as C
from gbox import pso_coop_geometry as G
from test_pso_geometry import fixture_memory, state as fixture_state

BASE = original_test_path('activation12-overlap-v3/test_real_proof_contract.py').resolve().parent.parent
POINTS = [(2, {'ptr': '80DA8830', 'x': 550.008, 'y': 32.928, 'z': -15.904}),
          (1, {'ptr': '80DA62A0', 'x': 531.607, 'y': 32.122, 'z': -28.214}),
          (2, {'ptr': '80DA8830', 'x': 548.877, 'y': 32.774, 'z': -22.134})]


@pytest.fixture(scope='module')
def atlas():
    evidence = BASE / 'observer-v1/field-geometry-receipt-1793622503722814000.json'
    return G.Atlas(json.loads(evidence.read_text())['result']['triangles'])


@pytest.mark.parametrize('slot,position', POINTS)
def test_real_overlap_connector_is_consumed_by_exact_current_core(atlas, slot, position):
    player = dict(position, hp=33, room=8)
    proof = G.LocalConnectors(atlas).recover(player, 'exact-layout')
    assert proof is not None
    state = dict(verified=True, geometry_verified=True, phase=14, episode=1,
                 floor=1, travelling=False, geometry_identity='exact-layout',
                 geometry_recovery_players={slot: proof})
    control = object.__new__(C.Controller)
    control.field = SimpleNamespace(status={'players': {}})
    control.margin_attempts = {}
    result = control.margin_waypoint(state, slot, player)
    assert result == (proof['waypoint']['x'], proof['waypoint']['z'])
    assert control.field.status['players'][str(slot)]['dependency'] == 'margin_recovery'
    assert atlas.project(player) is None
    wrong = copy.deepcopy(state)
    wrong['geometry_recovery_players'][slot]['player_ptr'] = '80DA9990'
    assert control.margin_waypoint(wrong, slot, player) is None


def test_both_current_players_get_provider_proofs_and_one_fresh_reobservation(atlas):
    memory, regions, _, _ = fixture_memory(atlas.triangles)
    state = fixture_state()
    for slot, position in POINTS[1:]:
        state['players'][slot].update(position, hp=33, room=8)
    regions[0x8050EA10] = struct.pack('>2I', 0x80DA62A0, 0x80DA8830)
    provider = G.Provider(memory)
    first = provider.snapshot(state)
    assert first['geometry_verified'] and first['geometry_refreshed']
    assert set(first['geometry_recovery_players']) == {1, 2}
    assert first['geometry_players'] == {}
    second = provider.snapshot(state)
    assert second['geometry_verified'] and not second['geometry_refreshed']
    assert second['geometry_recovery_players'] == first['geometry_recovery_players']


def test_exact_latest_p1_provider_proof_reaches_installed_controller(atlas):
    memory, regions, _, _ = fixture_memory(atlas.triangles)
    state = fixture_state()
    player = dict(ptr='80DA62A0', x=531.718, y=33.387, z=-22.392, hp=33, room=8)
    state['players'][1].update(player)
    state['players'][2].update(POINTS[0][1], hp=38, room=8)
    regions[0x8050EA10] = struct.pack('>2I', 0x80DA62A0, 0x80DA8830)
    provider = G.Provider(memory)
    first = provider.snapshot(state)
    assert first['geometry_verified'] and first['geometry_refreshed']
    proof = first['geometry_recovery_players'][1]
    assert 1 not in first['geometry_players']
    assert proof['connector_basis'] == 'exact_connected_native_foot_surface'
    second = provider.snapshot(state)
    assert not second['geometry_refreshed']
    control = object.__new__(C.Controller)
    control.field = SimpleNamespace(status={'players': {}})
    control.margin_attempts = {}
    context = dict(state, **second)
    result = control.margin_waypoint(context, 1, state['players'][1])
    assert result == (proof['waypoint']['x'], proof['waypoint']['z'])
    assert control.field.status['players']['1']['dependency'] == 'margin_recovery'
    wrong = copy.deepcopy(context)
    wrong['geometry_recovery_players'][1]['player_ptr'] = '80DA9990'
    assert control.margin_waypoint(wrong, 1, state['players'][1]) is None


def test_latest_p2_budgeted_provider_proof_reaches_installed_controller(atlas):
    memory, regions, _, _ = fixture_memory(atlas.triangles)
    state = fixture_state()
    state['players'][1].update(ptr='80DA62A0', x=525.117, y=34.628, z=-18.204, hp=33, room=8)
    state['players'][2].update(ptr='80DA8830', x=513.428, y=31.377, z=-44.747, hp=38, room=8)
    regions[0x8050EA10] = struct.pack('>2I', 0x80DA62A0, 0x80DA8830)
    provider = G.Provider(memory)
    first = provider.snapshot(state)
    assert first['geometry_verified'] and first['geometry_refreshed']
    proof = first['geometry_recovery_players'][2]
    assert 2 not in first['geometry_players'] and 1 in first['geometry_players']
    assert proof['connector_basis'] == 'exact_connected_native_foot_surface'
    assert proof['path_length'] <= 12 and proof['surface_work'] <= 400000
    second = provider.snapshot(state)
    assert not second['geometry_refreshed']
    control = object.__new__(C.Controller)
    control.field = SimpleNamespace(status={'players': {}})
    control.margin_attempts = {}
    context = dict(state, **second)
    result = control.margin_waypoint(context, 2, state['players'][2])
    assert result == (proof['waypoint']['x'], proof['waypoint']['z'])
    assert control.field.status['players']['2']['dependency'] == 'margin_recovery'
    wrong = copy.deepcopy(context)
    wrong['geometry_recovery_players'][2]['player_ptr'] = '80DA9990'
    assert control.margin_waypoint(wrong, 2, state['players'][2]) is None
