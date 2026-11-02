from pso_owned_evidence import original_test_path
"""Historical auxiliary-overlap positions must use the actual normal-floor contract."""
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


def normal_context(atlas, positions):
    memory, regions, _, _ = fixture_memory(atlas.triangles, owned_code=True)
    st = fixture_state()
    st['players'][1].update(ptr='80DA62A0',x=530.632,y=34.396,z=-20.274,hp=33,room=8)
    st['players'][2].update(POINTS[0][1],hp=38,room=8)
    for slot, position in positions:
        st['players'][slot].update(position,hp=33,room=8)
    regions[0x8050EA10] = struct.pack('>2I',0x80DA62A0,0x80DA8830)
    provider=G.Provider(memory)
    first=provider.snapshot(st)
    assert first['geometry_verified'] and first['geometry_refreshed']
    assert set(first['geometry_players'])=={1,2} and not first['geometry_recovery_players']
    second=provider.snapshot(st)
    assert second['geometry_verified'] and not second['geometry_refreshed']
    assert second['geometry_players']==first['geometry_players']
    return dict(st,**second)


def assert_normal_contract(context,slot,tmp_path):
    from gbox.pso_coop_nav import Maps
    player=context['players'][slot]
    nav=Maps(tmp_path).get(context,player)
    assert nav.floor and nav.route((player['x'],player['z']),(512.5,-192.5))
    control=object.__new__(C.Controller)
    control.field=SimpleNamespace(status={'players':{}})
    control.margin_attempts={}
    assert control.margin_waypoint(context,slot,player) is None
    missing=copy.deepcopy(context)
    del missing['geometry_players'][slot]
    assert Maps(tmp_path).get(missing,player).floor is None


@pytest.mark.parametrize('slot,position',POINTS)
def test_historical_overlap_positions_reach_normal_current_controller(atlas,slot,position,tmp_path):
    assert_normal_contract(normal_context(atlas,[(slot,position)]),slot,tmp_path)


def test_both_historical_held_players_get_normal_provider_and_fresh_observation(atlas,tmp_path):
    context=normal_context(atlas,POINTS[1:])
    for slot in (1,2):assert_normal_contract(context,slot,tmp_path)


def test_historical_p1_provider_normal_floor_reaches_current_controller(atlas,tmp_path):
    context=normal_context(atlas,[(1,dict(ptr='80DA62A0',x=531.718,y=33.387,z=-22.392))])
    assert_normal_contract(context,1,tmp_path)


def test_historical_p2_provider_normal_floor_reaches_current_controller(atlas,tmp_path):
    context=normal_context(atlas,[(1,dict(ptr='80DA62A0',x=525.117,y=34.628,z=-18.204)),
                                (2,dict(ptr='80DA8830',x=513.428,y=31.377,z=-44.747))])
    assert_normal_contract(context,2,tmp_path)
