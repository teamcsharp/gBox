"""gBox's game-agnostic bot brain (gbox/bot_brain.py): routing, targeting, aim, stuck handling, difficulty."""
import random

from gbox import bot_brain as bb


def grid(n=4, step=500.0):
    """n x n nodes, 4-connected, 500 units apart (y = 0)."""
    nodes = [(x * step, 0.0, z * step) for z in range(n) for x in range(n)]
    adj = [[] for _ in nodes]
    for z in range(n):
        for x in range(n):
            i = z * n + x
            if x + 1 < n:
                adj[i].append(i + 1)
                adj[i + 1].append(i)
            if z + 1 < n:
                adj[i].append(i + n)
                adj[i + n].append(i)
    return bb.NavGraph(nodes, adj)


def world(now, me, contacts=(), items=(), nav=None):
    return bb.World(now, me, list(contacts), list(items), nav)


def test_astar_shortest_route_unreachable_and_penalties():
    g = grid()
    path = g.path(0, 15)
    assert path[0] == 0 and path[-1] == 15 and len(path) == 7          # 6 hops on a 4x4 grid
    assert all(b in g.adj[a] for a, b in zip(path, path[1:]))
    g.adj.append([])                                                    # an island node
    g.nodes.append((9000.0, 0.0, 9000.0))
    assert g.path(0, 16) == []
    assert g.path(5, 5) == [5]
    first = g.path(0, 3)                                                # straight along the row
    assert first == [0, 1, 2, 3]
    detour = g.path(0, 3, penalty={(1, 2): 50.0, (2, 1): 50.0})
    assert (1, 2) not in list(zip(detour, detour[1:])) and detour[-1] == 3


def test_nearest_prefers_the_same_floor():
    g = bb.NavGraph([(0, 0, 0), (100, 400, 0), (300, 0, 0)], [[], [], []])
    assert g.nearest((120, 0, 0)) == 0                                  # node 1 is closer in x but a floor up
    assert g.nearest((260, 0, 0)) == 2


def test_aim_cone_follows_goldeneye_distance_table():
    assert bb.aim_cone_deg(100) == 14.4
    assert bb.aim_cone_deg(300) == 8.6
    assert bb.aim_cone_deg(600) == 4.29
    assert bb.aim_cone_deg(1000) == 2.16
    assert bb.aim_cone_deg(5000) == 1.07


def test_difficulty_presets_and_fallback():
    assert bb.difficulty("agent").reaction_s > bb.difficulty("00").reaction_s > bb.difficulty("007").reaction_s
    assert bb.difficulty("Agent agent").name == "agent"
    assert bb.difficulty("nonsense").name == "00"
    assert bb.difficulty(bb.PRESETS["secret"]) is bb.PRESETS["secret"]


def test_turns_toward_a_visible_target_and_fires_after_reacting():
    b = bb.Brain("007", rng=random.Random(1))
    me = bb.Body((0, 0, 0), heading=0.0, weapon_score=0.9)              # facing +z
    foe = bb.Contact(1, (300, 0, 300), visible=True)                    # bearing 45 degrees: turn to a larger heading
    i = b.tick(world(0.0, me, [foe]))
    assert i.goal == "fight" and i.target == 1 and i.turn > 0 and not i.fire   # first sight: not yet reacted
    me.heading = 45.0
    i = b.tick(world(5.0, me, [foe]))
    assert i.fire
    me.heading = 45.0 + 60.0                                            # far off: no trigger
    b.aim_off = 0.0
    b.aim_off_at = 5.0
    assert not b.tick(world(5.1, me, [foe])).fire


def test_ignores_targets_out_of_sight_but_hunts_them():
    b = bb.Brain("00", rng=random.Random(2))
    g = grid()
    me = bb.Body((0, 0, 0), heading=90.0, node=0, weapon_score=0.9)
    foe = bb.Contact(1, (1500, 0, 1500), visible=False, node=15)
    i = b.tick(world(0.0, me, [foe], nav=g))
    assert i.goal == "hunt" and not i.fire and b.route and b.route[-1] == 15


def test_follows_the_route_and_advances_past_reached_nodes():
    b = bb.Brain("00", rng=random.Random(3))
    g = grid()
    me = bb.Body((0, 0, 0), heading=90.0, node=0, weapon_score=0.9)     # facing +x, along the first row
    foe = bb.Contact(1, (1500, 0, 0), visible=False, node=3)
    i = b.tick(world(0.0, me, [foe], nav=g))
    assert b.route[0] == 1 and i.forward == 1.0 and abs(i.turn) < 0.2
    me.pos = (480.0, 0.0, 0.0)                                          # within ARRIVE of node 1
    b.tick(world(0.1, me, [foe], nav=g))
    assert b.route[0] == 2


def test_stuck_steps_aside_presses_use_and_penalises_the_edge():
    b = bb.Brain("00", rng=random.Random(4))
    g = grid()
    me = bb.Body((0, 0, 0), heading=90.0, node=0, weapon_score=0.9)
    foe = bb.Contact(1, (1500, 0, 0), visible=False, node=3)
    t, i = 0.0, None
    for _ in range(12):                                                  # wants forward, never moves
        i = b.tick(world(t, me, [foe], nav=g))
        t += 0.1
    assert b.stats["stuck"] == 1 and i.use and i.strafe != 0 and i.forward < 0
    assert any(v > 1.0 for v in b.penalty.values())


def test_dead_bot_presses_respawn_now_and_then():
    b = bb.Brain("00")
    me = bb.Body((0, 0, 0), heading=0.0, alive=False)
    first = b.tick(world(0.0, me))
    again = b.tick(world(0.1, me))
    later = b.tick(world(1.0, me))
    assert first.respawn and not again.respawn and later.respawn and first.goal == "dead"


def test_unarmed_bot_arms_first_and_punches_when_cornered():
    b = bb.Brain("00", rng=random.Random(5))
    me = bb.Body((0, 0, 0), heading=0.0, weapon_score=0.0)
    gun = ((0, 0, 800), 0.9)
    far = bb.Contact(1, (0, 0, 2000), visible=True)
    i = b.tick(world(0.0, me, [far], items=[gun]))
    assert i.goal == "pickup" and not i.fire
    near = bb.Contact(1, (0, 0, 120), visible=True)
    b.first_seen[1] = -10.0
    i = b.tick(world(1.0, me, [near], items=[gun]))
    assert i.goal == "melee" and i.forward > 0 and i.fire


def test_remembers_where_a_target_was_seen():
    b = bb.Brain("00", rng=random.Random(6))
    me = bb.Body((0, 0, 0), heading=0.0, weapon_score=0.9)
    b.tick(world(0.0, me, [bb.Contact(1, (0, 0, 900), visible=True)]))
    i = b.tick(world(0.5, me, [bb.Contact(1, (900, 0, 900), visible=False)]))
    assert i.goal == "chase" and i.forward > 0                          # heads for (0, 0, 900), not the hidden spot
    i = b.tick(world(30.0, me, [bb.Contact(1, (900, 0, 900), visible=False)]))
    assert i.goal == "hunt"                                             # memory expired after memory_s


def test_pickup_already_reached_is_skipped_for_a_while():
    b = bb.Brain("00", rng=random.Random(7))
    me = bb.Body((0, 0, 0), heading=0.0, weapon_score=0.0)
    item = ((10, 0, 10), 0.9)
    assert b.tick(world(0.0, me, items=[item])).goal == "pickup"
    assert b.tick(world(0.1, me, items=[item])).goal != "pickup"        # standing on it: not ours to take
