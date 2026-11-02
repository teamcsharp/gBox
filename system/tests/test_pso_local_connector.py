from pso_owned_evidence import original_test_path
import json
import math
from pathlib import Path
import struct

import pytest
from gbox import pso_coop_geometry as G
from test_pso_geometry import plane, player, fixture_memory, state, allow

ROOT=original_test_path('field-local-connector/test_local_connector.py').resolve().parent


@pytest.fixture(scope='module')
def actual():
    triangles=json.loads((ROOT.parent/'observer-v1/field-geometry-receipt-1793622503722814000.json').read_text())['result']['triangles']
    native=json.loads((ROOT.parent/'observer-v1/layer-evidence-1793634267920908700.json').read_text())['result']['native']
    return triangles,native


def test_actual_p1_thin_wall_cell_connector_restores_own_canonical_view(actual):
    triangles,native=actual;p=native['players']['1'];a=G.Atlas(triangles);local=G.LocalConnectors(a)
    assert a.heights.get(a.cell(p)) is None and a.project(p) is None
    row=local.recover(p,'exact-layout')
    assert row and row['path'][0]==[p['x'],p['z']]
    assert row['path'][1]==[row['waypoint']['x'],row['waypoint']['z']]
    assert row['path'][-1]==[229.75,496.25]
    assert 0<row['path_length']<=12 and 0<math.dist(*row['path'][:2])<=6
    assert row['continuous_surface_verified'] and row['sampling_size']==.5
    assert row['clearance_verified'] is False and row['dynamic_passability_verified'] is False
    view=local._local((p['x'],p['z']),local._point_height((p['x'],p['z'])))
    for i,(first,second) in enumerate(zip(row['path'],row['path'][1:])):
        assert local.clear(first,second,*row['path_heights'][i:i+2],view)
    end=dict(p,x=row['path'][-1][0],z=row['path'][-1][1],y=row['path_heights'][-1])
    assert a.project(end)['geometry_layer']==row['geometry_layer']=='a2608a43913f2dc59ee91006840962d3fb00f85bb501028651dccc38d4df9607'
    assert a.project(p) is None  # No ordinary-grid promotion of original cell.
    revision=local.revision
    assert local.recover(p,'exact-layout')==row and local.revision==revision


def test_subcell_gap_cannot_be_skipped_by_half_unit_centers():
    a=G.Atlas(plane(x1=2.45)+plane(x0=2.55))
    local=G.LocalConnectors(a)
    assert local.recover(player(x=2.25),'gap') is None
    view={'floors':[t[:3] for t in a.triangles], 'walls':[]}
    assert not local.clear((2.25,22.5),(2.75,22.5),0,0,view)


@pytest.mark.parametrize('height',[0,30])
def test_overlapping_layers_never_selected_for_reduced_clearance(height):
    local=G.LocalConnectors(G.Atlas(plane()+plane(y=30)))
    assert local.recover(player(x=2.25,y=height),'overlap') is None


@pytest.mark.parametrize('p',[player(x=-1),player(y=10),player(x=float('nan')),player(y=True)])
def test_unknown_falling_invalid_actual_point_is_held(p):
    assert G.LocalConnectors(G.Atlas(plane())).recover(p,'unknown') is None


def test_vertical_wall_and_oblique_wall_crossings_rejected():
    local=G.LocalConnectors(G.Atlas(plane()))
    floors=[t[:3] for t in plane()]
    for wall in [((5,0,0),(5,20,0),(5,20,50)),((4,0,0),(6,20,0),(6,20,50))]:
        assert not local.clear((2.5,22.5),(7.5,22.5),0,0,{'floors':floors,'walls':[wall]})
    # A wall entirely below the body's lower boundary does not gain authority
    # over a separate elevated surface.
    upper=[t[:3] for t in plane(y=30)]
    assert local.clear((2.5,22.5),(7.5,22.5),30,30,{'floors':upper,'walls':[((5,0,0),(5,20,0),(5,20,50))]})


def test_height_discontinuity_and_uncovered_line_rejected():
    a=G.Atlas(plane(x1=5)+plane(x0=5,y=20));local=G.LocalConnectors(a)
    view={'floors':[t[:3] for t in a.triangles],'walls':[]}
    assert not local.clear((2.5,22.5),(7.5,22.5),0,20,view)
    assert not local.clear((-1,22.5),(2.5,22.5),0,0,view)


def test_no_safe_surface_has_bounded_failed_cache():
    local=G.LocalConnectors(G.Atlas(plane(x1=1)))
    p=player(x=.25)
    assert local.recover(p,'thin') is None
    revision=local.revision
    for _ in range(3):
        assert local.recover(p,'thin') is None
    assert local.revision==revision and len(local.views)<=4


def actual_provider(actual):
    triangles,native=actual
    ad,regions,base,table=fixture_memory(triangles)
    s={k:native[k] for k in ('verified','phase','travelling','episode','floor')}
    s['players']={int(k):dict(v) for k,v in native['players'].items()}
    regions[0x8050EA10]=struct.pack('>2I',*(int(s['players'][k]['ptr'],16) for k in (1,2)))
    return G.Provider(ad),regions,base,s


def test_actual_provider_reobserves_before_recovery_and_preserves_normal_view_boundary(actual):
    provider,regions,base,s=actual_provider(actual)
    first=provider.snapshot(s)
    assert first['geometry_verified'] and first['geometry_refreshed']
    row=first['geometry_recovery_players'][1]
    assert row['connector_basis']=='exact_local_triangles' and 1 not in first['geometry_players']
    assert 2 in first['geometry_players']
    second=provider.snapshot(s)
    assert second['geometry_verified'] and not second['geometry_refreshed']
    assert second['geometry_recovery_players'][1]==row
    s['players'][1].update(x=row['path'][-1][0],z=row['path'][-1][1],y=row['path_heights'][-1])
    end=provider.snapshot(s)
    assert 1 in end['geometry_players'] and 1 not in end['geometry_recovery_players']
    local=provider.local
    blob=bytearray(regions[base]);blob[-1]^=1;regions[base]=bytes(blob)
    result=provider.snapshot(s)
    assert result['geometry_refreshed'] and provider.local is not local


def test_identity_change_during_local_projection_discards_all_recovery(actual,monkeypatch):
    provider,regions,base,s=actual_provider(actual)
    original=G.LocalConnectors.recover
    def changed(self,player,identity):
        result=original(self,player,identity)
        regions[0x805D49B8]=struct.pack('>I',1)
        return result
    monkeypatch.setattr(G.LocalConnectors,'recover',changed)
    result=provider.snapshot(s)
    assert not result['geometry_verified'] and 'geometry_recovery_players' not in result
    assert provider.local is None
