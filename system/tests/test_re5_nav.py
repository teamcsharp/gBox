"""RE5 traversal correctness: slopes, directed drops, and stage-specific learned crossings."""

import struct

from gbox.mercs.titles.re5_nav import Learning, NavMesh


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


def floor_pair(y=0.0, reverse=False, ptr=1):
    points = [(0.0, y, 0.0), (200.0, y, 0.0), (200.0, y, 200.0), (0.0, y, 200.0)]
    links = [[], [(0, 0, 1.0)]] if reverse else [[(1, 2, 1.0)], []]
    return NavMesh(points, [(0, 1, 2), (0, 2, 3)], links, ptr)


def test_observed_crossing_requires_real_membership_and_an_existing_directed_link():
    mesh, learned = floor_pair(), Learning()
    start, goal = (150.0, 0.0, 50.0), (50.0, 0.0, 150.0)
    assert learned.observe(mesh, start, 1.0) is None
    assert learned.observe(mesh, (140.0, 0.0, 60.0), 1.1) is None
    assert learned.observe(mesh, goal, 1.5) == "0:1"
    assert learned.observe(mesh, start, 2.0) is None                 # reverse travel cannot invent a reverse link
    stage = learned.stages[mesh.learning_sig]
    assert stage["crossings"] == {"0:1": 1}
    assert stage["visits"] == {"0": 2, "1": 1}                   # entries, not frame counts
    assert mesh.route(goal, start) is None                         # the recorded direction is still authoritative


def test_off_mesh_boundary_and_airborne_positions_are_not_crossing_evidence():
    mesh, learned = floor_pair(), Learning()
    start, goal, nearby = (150.0, 0.0, 50.0), (50.0, 0.0, 150.0), (-10.0, 0.0, 150.0)
    assert mesh.find(nearby) is None and mesh.member(nearby) is None
    assert mesh.member((100.0, 0.0, 100.0)) is None                 # shared diagonal has ambiguous membership
    assert mesh.member((50.0, 80.0, 150.0)) is None                 # animation above the floor
    learned.observe(mesh, start, 1.0)
    learned.observe(mesh, nearby, 1.2)
    learned.observe(mesh, goal, 1.4)
    assert not learned.stages[mesh.learning_sig]["crossings"]


def floor_grid(cells, blocked=()):
    """100cm floor cells with links only at their actual shared edges; blocked edges are solid walls."""
    points, lookup, tris = [], {}, []
    for x, z in cells:
        vertices = []
        for p in ((x * 100., 0., z * 100.), ((x + 1) * 100., 0., z * 100.),
                  ((x + 1) * 100., 0., (z + 1) * 100.), (x * 100., 0., (z + 1) * 100.)):
            if p not in lookup:
                lookup[p] = len(points); points.append(p)
            vertices.append(lookup[p])
        a, b, c, d = vertices
        tris += [(a, b, c), (a, c, d)]
    edges, links = {}, [[] for _ in tris]
    for i, tri in enumerate(tris):
        for edge in range(3):
            key = frozenset((tri[edge], tri[(edge + 1) % 3]))
            if key in edges:
                u, ue = edges[key]
                if frozenset(points[v] for v in key) not in blocked:
                    links[u].append((i, ue, 1.)); links[i].append((u, edge, 1.))
            else:
                edges[key] = (i, edge)
    return NavMesh(points, tris, links)


def test_off_mesh_goal_cannot_be_projected_into_a_nearby_room():
    mesh = floor_grid([(0, 0)])
    start = (20., 0., 50.)
    for goal in ((110., 0., 50.), (-10., 0., 50.), (400., 0., 50.)):
        assert mesh.find(goal) is None
        assert mesh.route(start, goal) is None
        assert not mesh.floor_segment(start, goal)


def test_l_corridor_segment_cannot_cut_its_missing_inside_corner():
    mesh = floor_grid([(0, 0), (1, 0), (2, 0), (2, 1), (2, 2)])
    start, corner, goal = (175., 0., 50.), (200., 0., 100.), (250., 0., 250.)
    assert not mesh.floor_segment(start, goal)
    assert mesh.floor_segment(start, corner) and mesh.floor_segment(corner, goal)
    route = mesh.route(start, goal)
    assert route[-1] == goal and len(route) > 1
    assert all(mesh.floor_segment(a, b) for a, b in zip([start] + route, route))


def test_adjacent_floors_are_not_a_doorway_without_a_link_and_route_uses_real_opening():
    wall = [frozenset(((100., 0., z), (100., 0., z + 100.))) for z in (0., 200.)]
    mesh = floor_grid([(x, z) for x in (0, 1) for z in (0, 1, 2)], blocked=wall)
    start, goal = (50., 0., 50.), (150., 0., 50.)
    assert not mesh.floor_segment(start, goal)             # floor exists both sides, but this edge is a wall
    assert mesh.floor_segment((50., 0., 150.), (150., 0., 150.))
    route = mesh.route(start, goal, pull=False)
    assert route and any(w[2] >= 100. for w in route)
    assert all(mesh.floor_segment(a, b) for a, b in zip([start] + route, route))


def test_floor_shortcuts_obey_direction_and_do_not_skip_a_climb():
    mesh = floor_pair()
    start, goal = (150., 0., 50.), (50., 0., 150.)
    assert mesh.floor_segment(start, goal) and not mesh.floor_segment(goal, start)
    climb = NavMesh([(0., 0., 0.), (100., 0., 0.), (0., 300., 100.)], [(0, 1, 2)], [[]])
    assert not climb.floor_segment((10., 0., 0.), (10., 150., 50.))


def test_floor_segments_reject_invalid_positions_and_different_storeys():
    mesh = floor_grid([(0, 0)])
    assert not mesh.floor_segment((float("nan"), 0., 0.), (50., 0., 50.))
    assert not mesh.floor_segment((20., 80., 50.), (50., 80., 50.))
    assert mesh.floor_segment((20., 0., 50.), (50., 13., 50.))  # hourglass centre lies above the floor


def test_a_nonvertical_steep_climb_face_is_not_observed_as_a_floor():
    mesh = NavMesh([(-100.0, 0.0, 0.0), (100.0, 0.0, 0.0), (0.0, 300.0, 100.0)], [(0, 1, 2)], [[]])
    assert mesh.find((0.0, 150.0, 50.0)) == 0
    assert mesh.steep[0] and mesh.member((0.0, 150.0, 50.0)) is None


def test_loading_sample_gaps_and_implausible_motion_do_not_prove_crossings():
    mesh = floor_pair()
    start, goal = (150.0, 0.0, 50.0), (50.0, 0.0, 150.0)
    for gap in (0.0, 0.01, 2.0):
        learned = Learning()
        learned.observe(mesh, start, 1.0)
        assert learned.observe(mesh, goal, 1.0 + gap) is None
    learned = Learning()
    learned.observe(mesh, start, 1.0)
    learned.observe(None, start, 1.1)
    assert learned.observe(mesh, goal, 1.5) is None


def test_geometry_or_direction_changes_reset_continuity_but_ram_relocation_keeps_learning():
    first, relocated, changed = floor_pair(), floor_pair(ptr=99), floor_pair(y=300.0)
    assert first.learning_sig == relocated.learning_sig
    assert first.learning_sig != changed.learning_sig
    assert first.learning_sig != floor_pair(reverse=True).learning_sig
    learned = Learning()
    learned.observe(first, (150.0, 0.0, 50.0), 1.0)
    assert learned.observe(relocated, (50.0, 0.0, 150.0), 1.5) == "0:1"
    assert learned.observe(changed, (50.0, 300.0, 150.0), 2.0) is None
    assert learned.stages[changed.learning_sig]["visits"] == {"1": 1}
    assert not learned.stages[changed.learning_sig]["crossings"]


def test_route_arrival_requires_actual_goal_membership_and_position_not_a_prompt_or_nearby_floor():
    mesh, learned = floor_pair(), Learning()
    start, goal = (150.0, 0.0, 50.0), (50.0, 0.0, 150.0)
    learned.begin_route(mesh, start, goal)
    learned.observe(mesh, start, 1.0)
    learned.observe(mesh, (-10.0, 0.0, 150.0), 1.5)                 # near the goal, outside its triangle
    row = learned.stages[mesh.learning_sig]["routes"]["0:1"]
    assert row["started"] == 1 and row["arrived"] == 0
    learned.observe(mesh, goal, 2.0)
    learned.observe(mesh, goal, 2.1)
    assert row["arrived"] == 1 and learned.active_route is None
    learned.begin_route(mesh, start, goal)
    learned.finish_route("timed_out")
    learned.finish_route("timed_out")                           # a terminal outcome only once
    assert row["started"] == 2 and row["timed_out"] == 1
    assert learned.route_penalty(mesh, start, goal) == 50.0
    assert learned.route_penalty(mesh, goal, start) == 0.0


def test_learning_persists_bounded_counts_and_no_in_flight_observation(tmp_path):
    class SmallLearning(Learning):
        MAX_GEOMETRIES, MAX_VISITS, MAX_CROSSINGS, MAX_ROUTES, MAX_COUNT = 2, 2, 2, 2, 3

    path = tmp_path / "navigation.json"
    learned = SmallLearning(path)
    for height in range(5):
        # Three distinct floors and three directed links exercise every per-stage map's bound.
        points = [(x + dx, float(height), z) for x in (0.0, 200.0, 400.0)
                  for dx, z in ((-40.0, -40.0), (40.0, -40.0), (0.0, 40.0))]
        mesh = NavMesh(points, [(0, 1, 2), (3, 4, 5), (6, 7, 8)],
                       [[(1, 0, 1.0)], [(2, 0, 1.0)], [(0, 0, 1.0)]])
        for i in range(15):
            start = (float(i % 3 * 200), float(height), 0.0)
            goal = (float((i + 1) % 3 * 200), float(height), 0.0)
            learned.observe(mesh, start, i + 1.0)
            learned.begin_route(mesh, start, goal)
            learned.finish_route("blocked")
        # Repeated entries into a retained node and route saturate rather than grow arbitrary integers.
        for i in range(10):
            learned.observe(mesh, (0.0, float(height), 0.0), 20.0 + i)
            learned.begin_route(mesh, (0.0, float(height), 0.0), (200.0, float(height), 0.0))
            learned.finish_route("timed_out")
    learned.begin_route(mesh, (0.0, 4.0, 0.0), (200.0, 4.0, 0.0))
    learned.save()
    loaded = SmallLearning(path)
    assert loaded.stages == learned.stages
    assert loaded.previous is None and loaded.active_route is None
    assert len(loaded.stages) == 2
    for stage in loaded.stages.values():
        assert all(len(stage[k]) <= 2 for k in ("visits", "crossings", "routes"))
        assert all(0 < v <= 3 for k in ("visits", "crossings") for v in stage[k].values())
        assert all(0 <= v <= 3 for row in stage["routes"].values() for v in row.values())
    assert max(v for row in loaded.stages[mesh.learning_sig]["routes"].values() for v in row.values()) == 3


def test_invalid_or_oversized_learning_file_is_ignored(tmp_path):
    path = tmp_path / "navigation.json"
    path.write_text('{"version":1,"stages":{"bad":{"visits":{"NaN":99,"1":-3},"routes":[]}}}')
    assert Learning(path).stages["bad"] == {"visits": {}, "crossings": {}, "routes": {}}
    path.write_text("x" * 41)
    class TinyFileLearning(Learning):
        MAX_FILE_BYTES = 40
    assert not TinyFileLearning(path).stages


def test_ram_mesh_cache_does_not_keep_old_geometry_after_unload_or_buffer_replacement():
    from gbox.mercs.titles import re5_nav as N

    class Memory:
        def __init__(self):
            self.data = {}

        def put(self, address, raw):
            self.data.update({address + i: b for i, b in enumerate(raw)})

        def word(self, address, value):
            self.put(address, struct.pack(">I", value))

        def rd(self, address, size):
            return bytes(self.data.get(address + i, 0) for i in range(size))

    memory, cache = Memory(), {}
    ai, pf, nav, points, nodes, vertices = (0x30000000 + i * 0x1000 for i in range(6))
    memory.word(N.S_AI, ai)
    memory.word(ai + N.AI_PATHFINDING, pf)
    memory.word(pf + N.PF_NAVMESH, nav)
    memory.word(nav + N.NM_POINTS, points)
    memory.word(nav + N.NM_NPOINTS, 3)
    memory.word(nav + N.NM_NODES, nodes)
    memory.word(nav + N.NM_NNODES, 1)
    memory.word(nodes + N.NODE_VERTS, vertices)
    memory.word(nodes + N.NODE_NVERTS, 3)
    memory.put(vertices, struct.pack(">3I", 0, 1, 2))

    def floor(address, height):
        memory.put(address, b"".join(struct.pack(">4f", x, height, z, 0.0)
                                    for x, z in ((0.0, 0.0), (100.0, 0.0), (0.0, 100.0))))

    floor(points, 0.0)
    first = N.read(memory, cache)
    assert N.read(memory, cache) is first
    memory.word(pf + N.PF_NAVMESH, 0)
    assert N.read(memory, cache) is None and not cache
    memory.word(pf + N.PF_NAVMESH, nav)
    floor(points, 300.0)
    second = N.read(memory, cache)
    assert second.ptr == first.ptr and second.learning_sig != first.learning_sig
    floor(points + 0x6000, 600.0)
    memory.word(nav + N.NM_POINTS, points + 0x6000)
    third = N.read(memory, cache)
    assert third.learning_sig != second.learning_sig and len(cache) == 1
