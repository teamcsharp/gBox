"""Native scene bounds reproduce the fatal Missile Area entry exactly."""
from types import SimpleNamespace
import math

import pytest

from gbox.mercs.titles import re5_stage_hazards as H
from gbox.mercs.titles.re5_nav import Traversal


@pytest.fixture
def mesh():
    return SimpleNamespace(sig=H.MISSILE_GEOMETRY)


def test_observed_full_health_death_crossed_native_incinerator_c(mesh):
    before = (-2713.07,470.,-22676.37)
    dead = (-2713.36,470.,-22750.08)
    volume = H.INCINERATORS[2]
    assert not volume.contains(before,vertical_margin=False)
    assert volume.contains(dead,vertical_margin=False)
    assert H.blocked_segment(mesh,before,dead,margin=0.) is volume
    # A 100-cm clearance begins before the fatal 0.23-second sample.
    assert H.blocked_segment(mesh,(-2712.86,470.,-22381.01),(-2712.86,470.,-22781.01)) is volume


@pytest.mark.parametrize('y', [0., 300., 700., 900.])
def test_other_floors_are_not_erased(mesh,y):
    assert H.blocked_segment(mesh,(-2713.,y,-22300.),(-2713.,y,-23500.)) is None


def test_crossing_is_refused_even_when_both_endpoints_are_clear(mesh):
    assert H.blocked_segment(mesh,(-3300.,470.,-23000.),(-2100.,470.,-23000.)).name == 'incineratorC'


def test_native_hazard_cannot_be_learned_away_as_walked_floor(mesh):
    mesh.walked = {(-2713,470,-23000):True}
    mesh.hazard_spots = 0
    assert H.blocked_segment(mesh,(-2713.,470.,-22500.),(-2713.,470.,-23000.))


def test_safe_departure_does_not_trap_bot_in_clearance_margin(mesh):
    start = (-2713.,470.,-22676.)
    assert H.blocked_segment(mesh,start,(-2713.,470.,-22650.),departing=True) is None
    assert H.blocked_segment(mesh,start,(-2713.,470.,-22690.),departing=True)
    assert H.blocked_segment(mesh,start,(-2713.,470.,-23500.),departing=True)


def test_stationary_or_tangent_command_is_not_escape(mesh):
    start = (-2713.,470.,-22676.)
    assert H.blocked_segment(mesh,start,start,departing=True)
    assert H.blocked_segment(mesh,start,(-2700.,470.,-22676.),departing=True)


def test_action_link_landing_and_intermediate_legs_are_checked(mesh):
    start = (-2713.,900.,-22000.)
    landing = Traversal((-2713.,470.,-22900.),(-2713.,900.,-22500.),(-2713.,900.,-22600.))
    assert H.blocked_path(mesh,start,[landing,(-2100.,470.,-22900.)]).name == 'incineratorC'


def test_identity_is_geometry_not_requested_stage():
    for mesh in (None,SimpleNamespace(stage_name='Missile Area'),
                 SimpleNamespace(sig='another-stage',stage_name='Missile Area'),
                 SimpleNamespace(sig=H.MISSILE_GEOMETRY+'-modified')):
        assert H.for_mesh(mesh) == ()


@pytest.mark.parametrize('bad', [(math.nan,470.,0.), (0.,math.inf,0.), None, (0.,0.)])
def test_invalid_coordinate_cannot_certify_clear_segment(mesh,bad):
    assert H.blocked_segment(mesh,bad,(-2713.,470.,-22900.))


@pytest.mark.parametrize('margin', [-1., math.inf, math.nan, True, 1001.])
def test_margin_is_finite_and_bounded(mesh,margin):
    with pytest.raises(ValueError):
        H.blocked_segment(mesh,(-2713.,470.,-22500.),(-2713.,470.,-22900.),margin=margin)


def floor_grid(*, y=470., narrow=False):
    from gbox.mercs.titles.re5_nav import NavMesh
    xs = list(range(-4000,-1400,200))
    zs = list(range(-23200,-22799,200)) if narrow else list(range(-24000,-21199,200))
    points = [(float(x),y,float(z)) for z in zs for x in xs]
    triangles = []
    for z in range(len(zs)-1):
        for x in range(len(xs)-1):
            a = z*len(xs)+x
            triangles.extend(((a,a+1,a+len(xs)+1),(a,a+len(xs)+1,a+len(xs))))
    links,edges = [[] for _ in triangles],{}
    for u,tri in enumerate(triangles):
        for edge in range(3):
            pair = frozenset((tri[edge],tri[(edge+1)%3]))
            if pair in edges:
                v,other = edges[pair]
                links[u].append((v,edge,1.))
                links[v].append((u,other,1.))
            else:
                edges[pair] = u,edge
    mesh = NavMesh(points,triangles,links)
    # Synthetic geometry deliberately adopts the known frame to test routing
    # against the actual incinerator coordinates; this is not a live mesh dump.
    mesh.sig = H.MISSILE_GEOMETRY
    return mesh


def test_route_chooses_supported_alternate_corridor_instead_of_idling():
    mesh = floor_grid()
    start,goal = (-3700.,470.,-23050.),(-1700.,470.,-23050.)
    assert H.blocked_path(mesh,start,mesh.route(start,goal))
    path = H.route(mesh,start,goal,clearance=35.)
    assert path and path[-1] == goal
    assert H.blocked_path(mesh,start,path) is None
    assert all(mesh.floor_segment(a,b) for a,b in zip([start]+path,path))
    assert any(p[2] > -22643.44 or p[2] < -23408.72 for p in path)
    # Reusing the static edge exclusion cache does not retain the old endpoint.
    back = H.route(mesh,goal,start,clearance=35.)
    assert back and back[-1] == start and not H.blocked_path(mesh,goal,back)


def test_route_does_not_invent_passage_when_entire_corridor_is_lethal():
    mesh = floor_grid(narrow=True)
    start,goal = (-3700.,470.,-23050.),(-1700.,470.,-23050.)
    assert mesh.route(start,goal)
    assert H.route(mesh,start,goal) is None


def test_route_keeps_other_storey_and_unrelated_geometry_unmodified():
    mesh = floor_grid(y=900.)
    start,goal = (-3700.,900.,-23050.),(-1700.,900.,-23050.)
    assert H.route(mesh,start,goal) == mesh.route(start,goal)
    mesh.sig = 'unrelated-native-geometry'
    assert H.route(mesh,start,goal) == mesh.route(start,goal)


def test_route_refuses_lethal_destination_and_invalid_coordinates():
    mesh = floor_grid()
    assert H.route(mesh,(-3700.,470.,-23050.),(-2700.,470.,-23050.)) is None
    assert H.route(mesh,(float('nan'),470.,-23050.),(-1700.,470.,-23050.)) is None


def test_optional_operator_archive_proves_catalogue():
    """Read the user's own archive; no copyrighted asset bytes are vendored."""
    import hashlib
    import os
    from pathlib import Path
    import struct
    import zlib
    from gbox import mt_arc
    from gbox.re5_stage_enemies import read_xfs

    archive = Path(os.environ.get('GBOX_RE5_S405_ARC',
        Path(__file__).resolve().parents[2]/'.scratch-merc-recovery/stage/inputs/s405.arc'))
    if not archive.is_file():
        pytest.skip('operator s405.arc is not present')
    raw = archive.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == '2466a7a73a792c7e43e8825a3f0d0a4b01ba3a8c56e8219aff32ab516ddb319b'
    found = []
    for entry in mt_arc.parse(raw).entries:
        if not entry.name.endswith('s405_sce'):
            continue
        scene = zlib.decompress(entry.data)
        assert hashlib.sha256(scene).hexdigest() == 'c5574a7a1227c4c47e241f5d19d97a6b69a53a0e8cacc031997b553cda2f4116'
        assert struct.unpack_from('<HH',scene,4) == (16,11)
        # The existing strict parser admits layout kind4 only. Scene kind11 has
        # the same measured descriptors/value encoding; adapt its type tag in
        # this private copy only, and require the parser to consume every byte.
        adapted = bytearray(scene)
        struct.pack_into('<H',adapted,6,4)
        rows = read_xfs(bytes(adapted))['mArray']['mpArray']
        assert len(rows) == len(H.INCINERATORS)
        for row,hazard in zip(rows,H.INCINERATORS):
            shape,param = row['Shape'],row['Param']
            assert (param['mBootType'],param['mSceNo'],param['mDetectAttr']) == (3,99999,16)
            assert shape['Name'] == hazard.name
            corners = [shape[f'Box.mSetPos{i}'] for i in range(4)]
            assert hazard.low == (min(v[0] for v in corners),shape['Box.mPosY'],min(v[2] for v in corners))
            assert hazard.high == (max(v[0] for v in corners),shape['Box.mPosY']+shape['Box.mHeight'],max(v[2] for v in corners))
        found.append(entry.name.split('\\')[-2])
    assert sorted(found) == ['merce','mercedc','merceex','vsm','vss']
