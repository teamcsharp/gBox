"""RE6 Switch (operator 2026-11-10 14:45): "I need it to actually aim the grenades at the ground instead of throwing them in
lava". A grenade goes only where it lands on the stage's walkable floor among the enemies: the target's feet on a nav-mesh
triangle (not NavMesh.locate's nearest-triangle fallback), and the aim point - the group's centre - on floor too, a little
short and long of it, with the floor running there from him. A centre over the lava gives way to one of them standing on
floor; nowhere to land it is no throw. No live game: test_re6_switch's synthetic guest and a mesh built here."""
import math

import pytest

from gbox.mercs.titles import re6_switch as R
from tests.test_re6_bomb_drop import drive, nade_bot


@pytest.fixture(autouse=True)
def _nades_back():
    was = R.NADES
    yield
    R.NADES = was


def mesh(holes=(), x=(-400, 400), z=(-200, 1200), step=100):
    """A flat floor of step-square cells (two triangles each) at y 0; a cell inside a hole (x0, x1, z0, z1) is lava: not
    on the mesh. The links join triangles that share an edge, as the decoded rNavigationMesh's do."""
    verts, index, tris = [], {}, []

    def v(px, pz):
        if (px, pz) not in index:
            index[px, pz] = len(verts)
            verts.append((float(px), 0.0, float(pz)))
        return index[px, pz]
    for cx in range(x[0], x[1], step):
        for cz in range(z[0], z[1], step):
            mx, mz = cx + step / 2, cz + step / 2
            if any(x0 <= mx <= x1 and z0 <= mz <= z1 for x0, x1, z0, z1 in holes):
                continue
            a, b, c, d = v(cx, cz), v(cx + step, cz), v(cx + step, cz + step), v(cx, cz + step)
            tris += [(a, b, c), (a, c, d)]
    edges = {}
    for k, t in enumerate(tris):
        for i in range(3):
            edges.setdefault(tuple(sorted((t[i], t[(i + 1) % 3]))), []).append(k)
    links = [[] for _ in tris]
    for ks in edges.values():
        if len(ks) == 2:
            links[ks[0]].append(ks[1])
            links[ks[1]].append(ks[0])
    return R.NavMesh(verts, tris, links, name="lava test")


CHANNEL = (-100, 100, 600, 1000)                  # a lava channel 2 m wide, 6..10 m ahead of him
GAP = (-400, 400, 1200, 1600)                     # a lava moat across the whole floor, 12..16 m ahead
MOAT = dict(holes=(GAP,), x=(-200, 200), z=(-200, 2200), step=200)


def test_floor_is_a_triangle_under_the_feet_not_the_nearest_one():
    m = mesh(holes=(CHANNEL,))
    assert R.Bot._floor_at(m, (300.0, 0.0, 800.0)) is True
    assert R.Bot._floor_at(m, (0.0, 0.0, 800.0)) is False                    # over the lava
    assert m.locate((0.0, 0.0, 800.0)) is not None                          # (locate's fallback finds a neighbour)
    assert R.Bot._floor_at(m, (300.0, 300.0, 800.0)) is False                # 3 m above the floor: not standing on it
    assert R.Bot._floor_at(object(), (0.0, 0.0, 0.0)) is None                # a mesh without a grid cannot say


def test_a_centre_over_the_lava_moves_onto_the_feet_of_one_on_the_floor():
    bot, bridge, clock, snap = nade_bot(())
    snap["navmesh"] = m = mesh(holes=(CHANNEL,))
    p = snap["player"]
    on_floor = [{"pos": (-200.0, 0.0, 700.0)}, {"pos": (200.0, 0.0, 900.0)}]
    assert bot._nade_landing(p, on_floor[:1], snap) == (-200.0, 0.0, 700.0)
    across = [{"pos": (-150.0, 0.0, 800.0)}, {"pos": (150.0, 0.0, 800.0)}]   # either side of the channel
    spot = bot._nade_landing(p, across, snap)
    assert spot in ((-150.0, 0.0, 800.0), (150.0, 0.0, 800.0))
    assert R.Bot._floor_at(m, spot) and bot.stats["nade_landing_moves"] == 1
    together = [{"pos": (-300.0, 0.0, 450.0)}, {"pos": (-250.0, 0.0, 500.0)}]
    assert bot._nade_landing(p, together, snap) == (-275.0, 0.0, 475.0)      # their centre on floor: the centre


def test_beyond_the_moat_or_at_its_edge_there_is_nowhere_to_land_it():
    bot, bridge, clock, snap = nade_bot(())
    snap["navmesh"] = mesh(**MOAT)
    p = snap["player"]
    assert bot._nade_landing(p, [{"pos": (0.0, 0.0, 2000.0)}], snap) is None  # across the lava: the floor stops
    assert bot._nade_landing(p, [{"pos": (0.0, 0.0, 1150.0)}], snap) is None  # half a metre from it: a long throw sinks
    assert bot.stats["nade_landing_skips"] == 2 and bot.stats["nade_void_skips"] >= 2
    assert bot._nade_landing(p, [{"pos": (0.0, 0.0, 900.0)}], snap) == (0.0, 0.0, 900.0)
    del snap["navmesh"]
    bot._mesh = None
    assert bot._nade_landing(p, [{"pos": (0.0, 0.0, 2000.0)}], snap) == (0.0, 0.0, 2000.0)   # no mesh: cannot say


def test_a_pack_either_side_of_the_lava_gets_its_grenade_on_the_ground_never_the_channel():
    foes = ((-150.0, 0.0, 800.0, 700), (150.0, 0.0, 800.0, 700))           # their centre is the lava channel
    bot, bridge, clock, snap = nade_bot(foes)
    snap["navmesh"] = m = mesh(holes=(CHANNEL,))
    aims = []
    for _ in range(60):
        drive(bot, bridge, clock, snap, 0.05)
        if bot.nade is not None and bot.nade.get("phase") in ("face", "aim", "throw"):
            aims.append((bot.nade["to"][0], bot.nade.get("to_y", 0.0), bot.nade["to"][1]))
    assert bot.stats["frags"] + bot.stats["fires"] >= 1
    assert aims and all(R.Bot._floor_at(m, a) for a in aims), aims
    assert all(math.hypot(a[0], a[2] - 800.0) > 100.0 for a in aims)       # never the channel's middle


def test_a_grenade_in_hand_with_only_lava_between_goes_back_unthrown():
    bot, bridge, clock, snap = nade_bot(((0.0, 0.0, 2000.0, 700),))
    snap["navmesh"] = mesh(**MOAT)
    snap["player"]["equipped"] = 9                                          # a frag in his hand
    out = bot.tick(snap)
    assert bot.stats["frags"] == 0 and not {"zl", "zr"} & set(out.get("hold") or ())
