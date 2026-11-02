from pso_owned_evidence import original_test_path
"""Offline replay of owned town geometry and recorded two-player observations."""
import copy
import hashlib
import json
import math
from pathlib import Path
from types import SimpleNamespace

import pytest

from gbox import pso_coop as C, pso_coop_town as T, pso_campaign as P
from gbox import gcdisc, psomap
from gbox.registry import Unsupported

ROOT = original_test_path('town-route/tests/test_pso_town_route.py').resolve().parents[1]


def observed(name='after_104'):
    state = json.loads((ROOT.parent/(name+'-native-readonly.json')).read_text())['state']
    state['players'] = {int(k): v for k,v in state['players'].items()}
    return state


@pytest.fixture(scope='module')
def corridor():
    raw = (ROOT/'map_city00_00c.rel').read_bytes()
    assert len(raw) == 70144 and hashlib.sha256(raw).hexdigest() == T.REL_SHA
    return T.Corridor(psomap.collision(raw))


@pytest.mark.parametrize('name', ['after_104','after_119','after_120','after_121','after_137','after_144'])
def test_recorded_both_players_have_exact_connector_routes(corridor,name):
    state = observed(name)
    assert T.scene(state)
    for player in state['players'].values():
        start = player['x'],player['z']
        route = corridor.route(start)
        assert route and route[0] == start and route[-1] == T.PLATFORM
        assert all(corridor.clear(a,b) for a,b in zip(route,route[1:]))
    if name == 'after_104':
        start = state['players'][2]['x'],state['players'][2]['z']
        assert not corridor.clear(start,T.PLATFORM)


@pytest.mark.parametrize('change', ['disc','profile','phase','episode','floor','height','nan_heading',
    'missing_pointer','duplicate_player','landmark','duplicate_landmark','enemy','travelling','unverified'])
def test_unknown_or_changed_scene_fails_closed(change):
    state = observed()
    if change == 'disc': state['globals']['disc_id'] = 'GPOJ8P'
    elif change == 'profile': state['profile'] = 'other'
    elif change in ('phase','episode','floor'): state[change] += 1
    elif change == 'height': state['players'][2]['y'] = 10.
    elif change == 'nan_heading': state['players'][2]['heading_deg'] = math.nan
    elif change == 'missing_pointer': state['players'][2].pop('ptr')
    elif change == 'duplicate_player': state['players'][2]['ptr'] = state['players'][1]['ptr']
    elif change == 'landmark':
        next(e for e in state['entities'] if e.get('entity_id') == 18372)['x'] += 1
    elif change == 'duplicate_landmark':
        state['entities'].append(copy.deepcopy(next(e for e in state['entities'] if e.get('entity_id') == 18372)))
    elif change == 'enemy': state['entities'].append(dict(kind='enemy',hp=1))
    elif change == 'travelling': state['travelling'] = True
    elif change == 'unverified': state['verified'] = False
    assert T.scene(state) is None


def test_exact_grid_crossing_rejects_a_tiny_diagonal_corner():
    grid = object.__new__(T.Corridor)
    grid.safe = {(0,0),(1,1)}
    assert not grid.clear((1.,1.01),(4.,4.01))
    grid.safe |= {(0,1),(1,0)}
    assert grid.clear((1.,1.01),(4.,4.01))
    assert not grid.clear((1.,1.01),(4.,4.01),{(0,1)})


def test_unknown_start_and_height_overlap_are_not_snapped(corridor):
    assert corridor.route((0.,0.)) is None
    assert corridor.route((math.nan,30.)) is None
    floor = ((180.,0.,5.),(380.,0.,5.),(180.,0.,290.),0,(0.,1.,0.))
    raised = (tuple((x,10.,z) for x,y,z in floor[:3]))
    upper = (*raised,0,(0.,1.,0.))
    assert T.Corridor([floor]).safe
    assert not T.Corridor([floor,upper]).safe


@pytest.mark.parametrize('change', ['native_header','disc_header','file_size','payload'])
def test_exact_disc_and_rel_gate_precedes_decoder(monkeypatch,change):
    raw = (ROOT/'map_city00_00c.rel').read_bytes()
    header = b'GPOE8P\0\x02'
    calls = []
    disc = SimpleNamespace(_r=lambda *_: header if change != 'disc_header' else b'GPOE8P\0\x01',
        files={T.REL:(0,70144 if change != 'file_size' else 70143)},
        read=lambda _: raw if change != 'payload' else bytes([raw[0]^1])+raw[1:],
        f=SimpleNamespace(close=lambda:calls.append('closed')))
    monkeypatch.setattr(gcdisc,'GCDisc',lambda _:disc)
    monkeypatch.setattr(psomap,'collision',lambda _:pytest.fail('Unverified geometry reached decoder'))
    ad = SimpleNamespace(memory_card_rom='owned.gcz',
        read_memory=lambda *_:header if change != 'native_header' else b'GPOE8P\0\x01')
    with pytest.raises(Unsupported): T.load_corridor(ad)
    assert calls == ([] if change == 'native_header' else ['closed'])


def test_static_stall_attempts_are_bounded_and_do_not_claim_arrival(corridor):
    state = observed()
    route = T.TownRoute(None,corridor=corridor)
    for now in range(0,100,2):
        for slot,point in route.plan(state,float(now)).items():
            route.target(slot,point)
            route.moved(slot)
    assert all(row['halted'] and row['attempts'] <= 24 for row in route.rows.values())
    assert not route.plan(state,10000.)
    assert not route.status['arrival_verified']
    assert not route.status['dynamic_doors_verified']
    assert not route.status['actor_radius_verified']
    # Only an observed position change resets a halted actor.
    state['players'][1]['x'] += 6.
    assert 1 in route.plan(state,10001.)
    assert route.rows[1]['attempts'] == 0 and route.rows[2]['halted']


def test_native_room_transition_preserves_progress_but_epoch_resets(corridor):
    ad = SimpleNamespace(_pso_timing_epoch=1)
    route = T.TownRoute(ad,corridor=corridor)
    state = observed('after_119')
    identity = route.bind(state)
    route.plan(state,0.)
    route.moved(1)
    state['players'][1]['room'] = 40
    assert route.bind(state) == identity and route.rows[1]['attempts'] == 1
    ad._pso_timing_epoch = 2
    assert route.bind(state) != identity and not route.rows


def bot(monkeypatch,tmp_path,state,corridor):
    calls = []
    monkeypatch.setattr(P,'wait',lambda *_:None)
    inputs = SimpleNamespace(hold=lambda commands:calls.append(commands),speed=lambda:1,stopped=lambda:False)
    result = C.Controller(SimpleNamespace(snapshot=lambda:copy.deepcopy(state)),inputs,C.Maps(tmp_path))
    result.town = T.TownRoute(None,corridor=corridor)
    result.town_enabled = True
    return result,calls


def test_controller_moves_both_buddies_without_room_wall_learning(monkeypatch,tmp_path,corridor):
    state = observed()
    controller,calls = bot(monkeypatch,tmp_path,state,corridor)
    assert controller.tick(state)
    assert [slot for slot,_,_ in calls[-1]] == [1,2]
    assert all(set(keys) <= {'lup','ldown','lleft','lright'} for _,keys,_ in calls[-1])
    assert controller.blocked == 0 and not controller.goals
    assert not list(tmp_path.rglob('*.json'))


def test_controller_reobserves_identity_before_movement(monkeypatch,tmp_path,corridor):
    state = observed()
    controller,calls = bot(monkeypatch,tmp_path,state,corridor)
    fresh = copy.deepcopy(state)
    fresh['players'][1]['ptr'] = '80FFFFFF'
    controller.reader.snapshot = lambda:fresh
    assert not controller.tick(state)
    assert len(calls) == 1 and all(keys == ['l'] for _,keys,_ in calls[0])


def test_controller_held_route_sends_no_inputs(monkeypatch,tmp_path,corridor):
    state = observed()
    for player in state['players'].values(): player['x'],player['z'] = T.PLATFORM
    controller,calls = bot(monkeypatch,tmp_path,state,corridor)
    assert not controller.tick(state) and not calls
    assert all(v == 'at_platform_waiting_for_observed_menu' for v in controller.town.status['players'].values())
    assert not controller.town.status['arrival_verified']
