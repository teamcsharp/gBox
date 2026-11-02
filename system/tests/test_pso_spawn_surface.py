from pso_owned_evidence import original_test_path
import json
import math
from pathlib import Path
import struct

import pytest
from gbox import pso_coop_geometry as G
from test_pso_geometry import plane, player, fixture_memory, state
from gbox.pso_coop_nav import RoomMap

ROOT = original_test_path('spawn-surface-connector-v3/test_spawn_surface.py').resolve().parent


@pytest.fixture(scope='module')
def forest():
    path = ROOT.parent/'observer-v1/field-geometry-receipt-1793622503722814000.json'
    return json.loads(path.read_text())['result']['triangles']


POSITIONS = [dict(ptr='80DA8830', x=550.008, y=32.928, z=-15.904),
             dict(ptr='80DA62A0', x=531.607, y=32.122, z=-28.214),
             dict(ptr='80DA8830', x=548.877, y=32.774, z=-22.134),
             dict(ptr='80DA62A0', x=531.718, y=33.387, z=-22.392),
             dict(ptr='80DA8830', x=513.428, y=31.377, z=-44.747)]


def check_proof(atlas, p, proof):
    assert proof and proof['connector_basis'] == 'exact_connected_native_foot_surface'
    assert proof['start'] == {key:p[key] for key in ('x','y','z')}
    assert proof['path'][0] == [p['x'],p['z']]
    assert proof['path'][1] == [proof['waypoint']['x'],proof['waypoint']['z']]
    assert 2 <= len(proof['path']) <= 16 and 0 < proof['path_length'] <= 12
    assert 0 < math.dist(*proof['path'][:2]) <= 6
    assert math.isclose(proof['path_length'],sum(math.dist(p,q) for p,q in zip(proof['path'],proof['path'][1:])))
    assert proof['clearance_verified'] is False and proof['dynamic_passability_verified'] is False
    assert 0 < proof['surface_work'] <= G.LocalConnectors.SURFACE_WORK_LIMIT
    component=[atlas.triangles[i][:3] for i in proof['surface_triangles']]
    for step,(start,end) in enumerate(zip(proof['path'],proof['path'][1:])):
        for index in range(21):
            t=index/20;x,z=[start[d]+t*(end[d]-start[d]) for d in (0,1)]
            height=proof['path_heights'][step]+t*(proof['path_heights'][step+1]-proof['path_heights'][step])
            assert any(G._inside(x,z,*triangle) and abs(G._height(x,z,*triangle)-height)<=.25 for triangle in component)
    end = dict(p,x=proof['path'][-1][0],z=proof['path'][-1][1],y=proof['path_heights'][-1])
    assert atlas.project(end)['geometry_layer'] == proof['geometry_layer']
    view = {'floors':[r[:3] for r in atlas.triangles if G._player_floor(r[3],r[4])],
            'walls':[r[:3] for r in atlas.triangles if abs(r[4][1])<=.6 and not r[3]&G.TRIGGER_FLAG]}
    for i,(start,end) in enumerate(zip(proof['path'],proof['path'][1:])):
        assert G.LocalConnectors(atlas).clear(start,end,*proof['path_heights'][i:i+2],view)


@pytest.mark.parametrize('p', POSITIONS)
def test_actual_auxiliary_overlap_positions_use_normal_main_floor(forest, p):
    atlas = G.Atlas(forest)
    view = atlas.project(p)
    assert view and view['geometry_layer'] == '3574e623f76944e6786c8c2acc28f6385ffd13f632d95529bd42c4fd5c01d5b9'
    assert len(atlas.heights[atlas.cell(p)]) == 1
    assert RoomMap(**view['collision_grid']).route((p['x'],p['z']),(512.5,-192.5))
    assert atlas.project(p) is view


def overlapping(upper_height=1.2):
    return plane(x1=60,z1=60)+plane(x0=20,x1=24,z1=60,y=upper_height)


def test_minimal_overlap_can_leave_on_original_plane_without_changing_grid():
    atlas=G.Atlas(overlapping());local=G.LocalConnectors(atlas);p=player(x=22.25,z=22.5)
    before={cell:tuple(heights) for cell,heights in atlas.heights.items()}
    proof=local._native_surface(p,'overlap')
    check_proof(atlas,p,proof)
    assert all(h==0 for h in proof['path_heights'])
    assert proof['surface_triangles']==[0,1]  # Joined by the exact XYZ diagonal.
    assert not set(proof['surface_triangles']) & {2,3}  # Upper sheet remains separate.
    assert before=={cell:tuple(heights) for cell,heights in atlas.heights.items()}


@pytest.mark.parametrize('height', [.001,.01,.05])
def test_ambiguous_native_foot_assignment_refuses(height):
    local=G.LocalConnectors(G.Atlas(overlapping(height)))
    assert local._native_surface(player(x=22.25,z=22.5),'ambiguous') is None


@pytest.mark.parametrize('height', [.051,.18,.2])
def test_distinct_nonmatching_sheet_does_not_override_exact_native_feet(height):
    atlas=G.Atlas(overlapping(height));local=G.LocalConnectors(atlas);p=player(x=22.25,z=22.5)
    proof=local._native_surface(p,'distinct-height')
    check_proof(atlas,p,proof)
    assert proof['surface_triangles']==[0,1] and all(h==0 for h in proof['path_heights'])


def test_unsettled_foot_height_and_same_height_triangle_edge_refuse():
    local=G.LocalConnectors(G.Atlas(overlapping()))
    assert local._native_surface(player(x=22.25,z=22.5,y=.010001),'airborne') is None
    assert local._native_surface(player(x=22.25,z=22.5,y=.051),'airborne') is None
    assert local._native_surface(player(x=22.5,z=22.5),'shared-edge') is None


def test_overlap_covering_all_reachable_endpoints_is_not_a_layer_switch():
    local=G.LocalConnectors(G.Atlas(plane(x1=60,z1=60)+plane(x1=60,z1=60,y=1.2)))
    assert local._native_surface(player(x=22.25,z=22.5),'no-end') is None


def test_no_connector_through_vertical_walls():
    triangles=overlapping()
    for x in (20,24):
        triangles += [((x,0,0),(x,20,0),(x,20,60),0,(1,0,0)),
                      ((x,0,0),(x,20,60),(x,0,60),0,(1,0,0))]
    local=G.LocalConnectors(G.Atlas(triangles))
    assert local._native_surface(player(x=22.25,z=22.5),'wall') is None


def test_gap_and_height_discontinuity_cannot_extend_seed_triangle():
    for next_plane in (plane(x0=25,x1=60,z1=60), plane(x0=24,x1=60,z1=60,y=20)):
        atlas=G.Atlas(plane(x1=24,z1=60)+plane(x1=24,z1=60,y=1.2)+next_plane)
        assert G.LocalConnectors(atlas)._native_surface(player(x=22.25,z=22.5),'gap') is None


def test_cached_proof_rebinds_actor_and_layout_and_limits_failed_cache():
    local=G.LocalConnectors(G.Atlas(overlapping()));p=player(x=22.25,z=22.5)
    proof=local._native_surface(p,'one');other=local._native_surface(dict(p,ptr='80DA9990'),'two')
    assert proof['geometry_identity']=='one' and other['geometry_identity']=='two'
    assert proof['player_ptr']==p['ptr'] and other['player_ptr']=='80DA9990'
    for index in range(140): local._native_surface(player(x=-100-index,z=-100),'outside')
    assert len(local.single_cache)==128


def provider_at_spawn(forest):
    ad,regions,base,_=fixture_memory(forest, owned_code=True);provider=G.Provider(ad);s=state()
    s['floor']=1
    s['players'][1].update(ptr='80DA62A0',x=530.632,y=34.396,z=-20.274)
    s['players'][2].update(POSITIONS[0])
    regions[0x805D5FC0]=struct.pack('>I',1)
    regions[0x8050EA10]=struct.pack('>2I',0x80DA62A0,0x80DA8830)
    return provider,regions,base,s


def test_actual_provider_uses_normal_floor_then_requires_fresh_observation(forest):
    provider,_,_,s=provider_at_spawn(forest)
    first=provider.snapshot(s)
    assert first['geometry_verified'] and first['geometry_refreshed']
    assert set(first['geometry_players']) == {1,2} and not first['geometry_recovery_players']
    second=provider.snapshot(s)
    assert second['geometry_verified'] and not second['geometry_refreshed']
    assert second['geometry_players']==first['geometry_players']


def test_historical_both_held_players_use_normal_floor_after_fresh_read(forest):
    provider,_,_,s=provider_at_spawn(forest)
    s['players'][1].update(POSITIONS[1]);s['players'][2].update(POSITIONS[2])
    first=provider.snapshot(s)
    assert first['geometry_verified'] and first['geometry_refreshed']
    assert set(first['geometry_players']) == {1,2} and not first['geometry_recovery_players']
    second=provider.snapshot(s)
    assert second['geometry_verified'] and not second['geometry_refreshed']
    assert second['geometry_players']==first['geometry_players']


def test_historical_p1_and_nearby_p2_use_main_floor_without_auxiliary_surface(forest):
    atlas=G.Atlas(forest)
    p2=dict(ptr='80DA8830',x=528.615,y=33.368,z=-24.056)
    for p in (POSITIONS[3],p2):
        view=atlas.project(p)
        assert view and len(atlas.heights[atlas.cell(p)]) == 1
        assert RoomMap(**view['collision_grid']).route((p['x'],p['z']),(512.5,-192.5))


def test_historical_p1_reaches_normal_provider_and_reobserves_before_input(forest):
    provider,_,_,s=provider_at_spawn(forest);s['players'][1].update(POSITIONS[3])
    first=provider.snapshot(s)
    assert first['geometry_verified'] and first['geometry_refreshed']
    assert 1 in first['geometry_players'] and 1 not in first['geometry_recovery_players']
    second=provider.snapshot(s)
    assert second['geometry_verified'] and not second['geometry_refreshed']
    assert second['geometry_players']==first['geometry_players']


def test_surface_work_exhaustion_fails_closed_and_is_cached(monkeypatch):
    local=G.LocalConnectors(G.Atlas(overlapping()))
    monkeypatch.setattr(G.LocalConnectors,'SURFACE_WORK_LIMIT',20)
    p=player(x=22.25,z=22.5)
    assert local._native_surface(p,'bounded') is None
    revision=local.revision
    assert local._native_surface(p,'bounded') is None and local.revision==revision


def test_ineligible_endpoints_do_not_consume_twelve_projection_slots(monkeypatch):
    atlas=G.Atlas(plane(x1=60,z1=60));local=G.LocalConnectors(atlas)
    p=player(x=22.25,z=22.5);rejected=set();calls=[];original=atlas.project
    def eligible(point,height):
        if point[1]<31:
            rejected.add(atlas.cell(dict(x=point[0],z=point[1])));return False
        return True
    def project(point):
        calls.append(point);assert point['z']>=31
        return original(point)
    local.endpoint_ok=eligible;monkeypatch.setattr(atlas,'project',project)
    proof=local.recover(p,'bounded')
    assert proof and len(rejected)>=12 and len(calls)==1
    assert proof['path_length']<=12


def test_thirteen_or_more_eligible_cells_still_get_only_twelve_projection_probes(monkeypatch):
    atlas=G.Atlas(plane(x1=60,z1=60));local=G.LocalConnectors(atlas)
    eligible_cells=set();calls=[]
    def eligible(point,height):
        eligible_cells.add(atlas.cell(dict(x=point[0],z=point[1])));return True
    local.endpoint_ok=eligible
    monkeypatch.setattr(atlas,'project',lambda point:calls.append(point))
    assert local.recover(player(x=22.25,z=22.5),'bounded') is None
    assert len(eligible_cells)>12 and len(calls)==12


def test_ineligible_point_does_not_poison_later_eligible_point_in_same_cell(monkeypatch):
    atlas=G.Atlas(plane(x1=60,z1=60));local=G.LocalConnectors(atlas)
    p=player(x=22.25,z=22.5);calls=[];original=atlas.project
    local.endpoint_ok=lambda point,height:point[0]>=23.25
    def project(point):calls.append(point);return original(point)
    monkeypatch.setattr(atlas,'project',project)
    proof=local.recover(p,'same-cell')
    assert proof and len(calls)==1 and atlas.cell(calls[0])==atlas.cell(p)


def test_historical_p2_bent_escape_is_replaced_by_normal_floor_and_fresh_read(forest):
    provider,_,_,s=provider_at_spawn(forest)
    s['players'][1].update(ptr='80DA62A0',x=525.117,y=34.628,z=-18.204)
    s['players'][2].update(POSITIONS[4])
    first=provider.snapshot(s)
    assert first['geometry_verified'] and first['geometry_refreshed']
    assert set(first['geometry_players']) == {1,2} and not first['geometry_recovery_players']
    view=first['geometry_players'][2]
    assert RoomMap(**view['collision_grid']).route((s['players'][2]['x'],s['players'][2]['z']),(512.5,-192.5))
    second=provider.snapshot(s)
    assert second['geometry_verified'] and not second['geometry_refreshed']
    assert second['geometry_players']==first['geometry_players']


def test_changed_native_binding_during_normal_projection_discards_view(forest,monkeypatch):
    provider,regions,_,s=provider_at_spawn(forest)
    original=G.Atlas.project
    def drift(self,player):
        view=original(self,player)
        regions[0x805D49B8]=struct.pack('>I',1)
        return view
    monkeypatch.setattr(G.Atlas,'project',drift)
    result=provider.snapshot(s)
    assert not result['geometry_verified'] and 'geometry_players' not in result
