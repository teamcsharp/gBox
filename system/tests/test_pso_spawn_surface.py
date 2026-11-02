from pso_owned_evidence import original_test_path
import json
import math
from pathlib import Path
import struct

import pytest
from gbox import pso_coop_geometry as G
from test_pso_geometry import plane, player, fixture_memory, state

ROOT = original_test_path('spawn-surface-connector-v2/test_spawn_surface.py').resolve().parent


@pytest.fixture(scope='module')
def forest():
    path = ROOT.parent/'observer-v1/field-geometry-receipt-1793622503722814000.json'
    return json.loads(path.read_text())['result']['triangles']


POSITIONS = [dict(ptr='80DA8830', x=550.008, y=32.928, z=-15.904),
             dict(ptr='80DA62A0', x=531.607, y=32.122, z=-28.214),
             dict(ptr='80DA8830', x=548.877, y=32.774, z=-22.134),
             dict(ptr='80DA62A0', x=531.718, y=33.387, z=-22.392)]


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
    view = {'floors':[r[:3] for r in atlas.triangles if r[4][1]>.6 and not r[3]&G.TRIGGER_FLAG],
            'walls':[r[:3] for r in atlas.triangles if abs(r[4][1])<=.6 and not r[3]&G.TRIGGER_FLAG]}
    for i,(start,end) in enumerate(zip(proof['path'],proof['path'][1:])):
        assert G.LocalConnectors(atlas).clear(start,end,*proof['path_heights'][i:i+2],view)


@pytest.mark.parametrize('p', POSITIONS)
def test_actual_overlap_positions_recover_on_exact_foot_connected_surface(forest, p):
    atlas = G.Atlas(forest); local = G.LocalConnectors(atlas)
    assert atlas.project(p) is None
    proof = local._native_surface(p, 'exact-layout')
    check_proof(atlas,p,proof)
    assert proof['geometry_layer'] == 'a2608a43913f2dc59ee91006840962d3fb00f85bb501028651dccc38d4df9607'
    assert atlas.project(p) is None
    revision = local.revision
    assert local._native_surface(p,'exact-layout') == proof and local.revision == revision


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
    ad,regions,base,_=fixture_memory(forest);provider=G.Provider(ad);s=state()
    s['floor']=1
    s['players'][1].update(ptr='80DA62A0',x=530.632,y=34.396,z=-20.274)
    s['players'][2].update(POSITIONS[0])
    regions[0x805D5FC0]=struct.pack('>I',1)
    regions[0x8050EA10]=struct.pack('>2I',0x80DA62A0,0x80DA8830)
    return provider,regions,base,s


def test_actual_provider_uses_overlap_branch_then_requires_fresh_observation(forest):
    provider,_,_,s=provider_at_spawn(forest)
    first=provider.snapshot(s)
    assert first['geometry_verified'] and first['geometry_refreshed']
    assert 1 in first['geometry_players'] and 2 not in first['geometry_players']
    check_proof(provider.atlas,s['players'][2],first['geometry_recovery_players'][2])
    second=provider.snapshot(s)
    assert second['geometry_verified'] and not second['geometry_refreshed']
    assert second['geometry_recovery_players']==first['geometry_recovery_players']


def test_current_both_held_players_recover_through_provider_after_fresh_read(forest):
    provider,_,_,s=provider_at_spawn(forest)
    s['players'][1].update(POSITIONS[1]);s['players'][2].update(POSITIONS[2])
    first=provider.snapshot(s)
    assert first['geometry_verified'] and first['geometry_refreshed']
    assert first['geometry_players']=={}
    for slot in (1,2):
        check_proof(provider.atlas,s['players'][slot],first['geometry_recovery_players'][slot])
    second=provider.snapshot(s)
    assert second['geometry_verified'] and not second['geometry_refreshed']
    assert second['geometry_recovery_players']==first['geometry_recovery_players']


def test_new_p1_and_nearby_p2_native_feet_recover_without_borrowing_upper_surface(forest):
    atlas=G.Atlas(forest);local=G.LocalConnectors(atlas)
    p2=dict(ptr='80DA8830',x=528.615,y=33.368,z=-24.056)
    for p in (POSITIONS[3],p2):
        proof=local._native_surface(p,'exact')
        check_proof(atlas,p,proof)
        assert proof['seed_triangle']==231 and 272 not in proof['surface_triangles']


def test_new_p1_reaches_provider_recovery_and_reobserves_before_input(forest):
    provider,_,_,s=provider_at_spawn(forest);s['players'][1].update(POSITIONS[3])
    first=provider.snapshot(s)
    assert first['geometry_verified'] and first['geometry_refreshed']
    assert 1 not in first['geometry_players']
    check_proof(provider.atlas,s['players'][1],first['geometry_recovery_players'][1])
    second=provider.snapshot(s)
    assert second['geometry_verified'] and not second['geometry_refreshed']
    assert second['geometry_recovery_players']==first['geometry_recovery_players']


def test_surface_work_exhaustion_fails_closed_and_is_cached(monkeypatch):
    local=G.LocalConnectors(G.Atlas(overlapping()))
    monkeypatch.setattr(G.LocalConnectors,'SURFACE_WORK_LIMIT',20)
    p=player(x=22.25,z=22.5)
    assert local._native_surface(p,'bounded') is None
    revision=local.revision
    assert local._native_surface(p,'bounded') is None and local.revision==revision


def test_changed_native_binding_during_overlap_work_discards_proof(forest,monkeypatch):
    provider,regions,_,s=provider_at_spawn(forest)
    original=G.LocalConnectors._native_surface
    def drift(self,player,identity):
        proof=original(self,player,identity)
        regions[0x805D49B8]=struct.pack('>I',1)
        return proof
    monkeypatch.setattr(G.LocalConnectors,'_native_surface',drift)
    result=provider.snapshot(s)
    assert not result['geometry_verified'] and 'geometry_recovery_players' not in result
