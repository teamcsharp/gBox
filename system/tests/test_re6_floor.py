"""Nearest mesh recovery must not approve stepping off a real floor edge."""
import math

import pytest

from gbox.mercs.titles.re6_floor import floor_at
from gbox.mercs.titles.re6_switch import NavMesh


def triangle():
    return NavMesh([(0., 0., 0.), (400., 0., 0.), (0., 0., 400.)], [(0, 1, 2)], [[]])


def test_nearest_triangle_fallback_cannot_make_a_ledge_safe():
    mesh = triangle()
    start, off_edge = (100., 0., 100.), (350., 0., 350.)
    assert mesh.locate(start) == mesh.locate(off_edge) == 0  # original false positive
    assert mesh.clear(start, off_edge) is False
    assert mesh.clear(off_edge, start) is False
    assert mesh.clear(off_edge, off_edge) is False
    assert mesh.clear(start, (150., 0., 150.)) is True


def test_off_stage_far_end_and_unknown_height_are_not_safe_floor():
    mesh = triangle()
    assert mesh.clear((100., 0., 100.), (100000., 0., 100000.)) is False
    assert mesh.clear((100., 0., 100.), (100., 900., 100.)) is None
    assert floor_at(mesh, (100., 31., 100.), 30.) is None


@pytest.mark.parametrize('bad', [(math.nan, 0., 0.), (0., math.inf, 0.), ('1', 0., 0.), None, [1, 2]])
def test_bad_coordinates_never_certify_floor(bad):
    mesh = triangle()
    assert floor_at(mesh, bad, 30.) is None
    assert mesh.clear((100., 0., 100.), bad) is False


def test_sloped_floor_uses_height_at_feet_not_triangle_centroid():
    mesh = NavMesh([(0., 0., 0.), (1000., 1000., 0.), (0., 0., 1000.)], [(0, 1, 2)], [[]])
    assert floor_at(mesh, (10., 10., 10.), 1.) == (0, 10.)
    assert mesh.clear((10., 10., 10.), (100., 100., 10.)) is True
    assert floor_at(mesh, (10., 300., 10.), 30.) is None


def test_overlapping_storeys_choose_floor_at_player_height():
    v = [(x, y, z) for y in (0., 500.) for x, z in ((0., 0.), (400., 0.), (0., 400.))]
    mesh = NavMesh(v, [(0, 1, 2), (3, 4, 5)], [[], []])
    assert floor_at(mesh, (100., 500.1, 100.), 30.) == (1, 500.)
    assert floor_at(mesh, (100., 250., 100.), 30.) is None


def test_degenerate_geometry_does_not_prove_ground_contact():
    mesh = NavMesh([(0., 0., 0.), (100., 0., 0.), (200., 0., 0.)], [(0, 1, 2)], [[]])
    assert floor_at(mesh, (50., 0., 0.), 30.) is None
    assert mesh.clear((50., 0., 0.), (60., 0., 0.)) is False
