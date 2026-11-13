from gbox.mercs.titles import re5_switch as R
from gbox.mercs.titles.re5_nav import NavMesh
from gbox.mercs.titles.re5_switch_nav import C_WALL, geometry_identity


def mesh(offset=0.):
    result = NavMesh([(offset, 0., 0.), (offset+1000., 0., 0.),
                      (offset+1000., 0., 1000.), (offset, 0., 1000.)],
                     [(0, 1, 2), (0, 2, 3)], [[], []])
    result.name = 'test-native-resource'
    result.stage_name = 'Village'
    return result


def bot(tmp_path):
    result = R.Bot(stats={}, clock=lambda: 1.)
    result._learn_dir = tmp_path
    return result


def test_main_loop_persists_measured_geometry_and_reloads_it(tmp_path):
    level = mesh()
    first = bot(tmp_path)
    first._tick({'nav': level}, 1.)
    first._nav.grid.mark_wall(500., 500.)
    # A loading gap saves the completed observed map before resetting scope.
    first._tick({}, 2.)
    second = bot(tmp_path)
    second._tick({'nav': level}, 3.)
    assert second._nav.grid.identity == geometry_identity(level)
    assert second._nav.grid.cost((5, 5)) == C_WALL
    assert len(list((tmp_path/'nav_grids'/'verified').glob('*.json'))) == 1


def test_menu_stage_resync_does_not_destroy_verified_grid(tmp_path, monkeypatch):
    monkeypatch.setattr(R.tuning, 'apply', lambda *a: None)
    monkeypatch.setattr(R.tuning, 'dead_ends', lambda *a: [])
    b = bot(tmp_path)
    b._tick({'nav': mesh()}, 1.)
    navigator = b._nav
    b._stage_learning('Village')
    assert b._nav is navigator
    b._stage_learning('Prison')  # a menu identity cannot re-key measured geometry
    assert b._nav is navigator


def test_different_geometry_and_unverified_gap_do_not_share_wall_memory(tmp_path):
    b = bot(tmp_path)
    b._tick({'nav': mesh()}, 1.)
    b._nav.grid.mark_wall(500., 500.)
    b._tick({'nav': mesh(10.)}, 2.)
    assert not b._nav.grid.cells
    b._tick({}, 3.)
    assert b._nav.grid.identity is None and not b._nav.grid.cells
    b._nav.grid.mark_wall(900., 900.)
    b._nav.grid.save(force=True)
    assert not list((tmp_path/'nav_grids').glob('*.json'))


def test_round_bootstrap_cannot_load_old_unverified_stage_file(tmp_path, monkeypatch):
    monkeypatch.setattr(R.tuning, 'apply', lambda *a: None)
    monkeypatch.setattr(R.tuning, 'dead_ends', lambda *a: [])
    b = bot(tmp_path)
    b._stage_learning('Village')
    assert b._nav.grid._base is None
    b._nav.grid.mark_wall(0., 0.)
    b._nav.grid.save(force=True)
    assert not list(tmp_path.rglob('*.json'))


def test_main_route_planner_uses_scene_hazard_detour(tmp_path):
    from test_re5_stage_hazards import floor_grid
    from gbox.mercs.titles.re5_stage_hazards import blocked_path
    b = bot(tmp_path)
    b._mesh = floor_grid()
    start, goal = (-3700.,470.,-23050.), (-1700.,470.,-23050.)
    assert b._mesh_waypoint({'pos': start, 'rot': 0.}, goal, 10.) is not None
    assert blocked_path(b._mesh, start, b._mroute['pts'], departing=True) is None
