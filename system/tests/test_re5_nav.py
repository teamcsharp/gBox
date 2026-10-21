"""RE5 traversal correctness: slopes, directed drops, and stage-specific learned crossings."""

from gbox.mercs.titles.re5_nav import NavMesh


def test_ramp_lookup_uses_floor_height_at_the_player_not_the_triangle_centroid():
    points = [(-100.0, 0.0, 0.0), (100.0, 0.0, 0.0), (-100.0, 600.0, 1000.0), (100.0, 600.0, 1000.0)]
    mesh = NavMesh(points, [(0, 1, 3), (0, 3, 2)], [[(1, 2, 1.0)], [(0, 0, 1.0)]])
    start, goal = (0.0, 6.0, 10.0), (0.0, 594.0, 990.0)
    assert mesh.find(start) == 0 and mesh.find(goal) == 1
    assert mesh.route(start, goal)[-1] == goal


def test_a_directed_drop_is_reachable_only_in_its_recorded_direction():
    points = [(-100.0, 0.0, 0.0), (100.0, 0.0, 0.0), (0.0, 0.0, 200.0),
              (-100.0, 300.0, 400.0), (100.0, 300.0, 400.0), (0.0, 300.0, 600.0)]
    mesh = NavMesh(points, [(0, 1, 2), (3, 4, 5)], [[], [(0, 0, 1.0)]])
    low, high = (0.0, 0.0, 50.0), (0.0, 300.0, 450.0)
    assert mesh.component(0) == mesh.component(1)
    assert mesh.route(high, low)[-1] == low
    assert mesh.route(low, high) is None


def test_learning_signature_follows_geometry_across_relocations_not_just_node_counts():
    points, tris, links = [(0.0, 0.0, 0.0), (100.0, 0.0, 0.0), (0.0, 0.0, 100.0)], [(0, 1, 2)], [[]]
    first = NavMesh(points, tris, links, ptr=1)
    same_stage = NavMesh(points, tris, links, ptr=2)
    other_stage = NavMesh([(x, y + 300.0, z) for x, y, z in points], tris, links, ptr=1)
    assert first.sig == same_stage.sig and first.sig != other_stage.sig
