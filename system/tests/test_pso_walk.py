"""CP17: the collision graph is routable - floors, walls and a shortest path over a real `c.rel`."""
import pathlib
from collections import deque

import pytest

from gbox import pso_walk as W

DISC = pathlib.Path(r"D:\gBox\cache\mods\436e0bb84d5337d1\pso_city_npc_moved"
                    r"\Phantasy Star Online Episode I & II Plus (USA).iso")


@pytest.fixture(scope="module")
def ancient_collision() -> bytes:
    from gbox import gcdisc
    if not DISC.is_file():
        pytest.skip("the disc is not on this machine")
    return gcdisc.GCDisc(str(DISC)).read("Scene/map_aancient01_00c.rel")


def _components(walkable: set) -> list[set]:
    seen, out = set(), []
    for start in walkable:
        if start in seen:
            continue
        block, queue = set(), deque([start])
        seen.add(start)
        while queue:
            cell = queue.popleft()
            block.add(cell)
            for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nxt = (cell[0] + dx, cell[1] + dz)
                if nxt in walkable and nxt not in seen:
                    seen.add(nxt)
                    queue.append(nxt)
        out.append(block)
    return out


def test_the_room_has_a_walkable_graph(ancient_collision):
    summary = W.describe(ancient_collision)
    assert summary["floors"] > 100                     # a real room, not a degenerate triangle set
    assert summary["walls"] > 0
    assert 0 < summary["walkable"] <= summary["floors"]


def test_the_largest_connected_region_is_routable(ancient_collision):
    floors, walls = W.cells(ancient_collision)
    walkable = floors - walls
    blocks = sorted(_components(walkable), key=len, reverse=True)
    assert blocks and len(blocks[0]) >= 20, "the room should have a sizeable connected floor"
    cells = sorted(blocks[0])
    start, end = cells[0], cells[-1]
    route = W.path(ancient_collision, W.cell_centre(start), W.cell_centre(end))
    assert route, "two cells of the same component must be connected"
    assert route[0] == W.cell_centre(start)
    assert route[-1] == W.cell_centre(end)
    for (ax, az), (bx, bz) in zip(route, route[1:]):
        assert abs(ax - bx) + abs(az - bz) == pytest.approx(W.CELL)


def test_a_point_far_outside_the_room_has_no_route(ancient_collision):
    floors, walls = W.cells(ancient_collision)
    walkable = sorted(floors - walls)
    route = W.path(ancient_collision, (100000.0, 100000.0), W.cell_centre(walkable[0]))
    assert route is None


def test_the_cell_helpers_are_inverse():
    assert W.to_cell(*W.cell_centre((3, -2))) == (3, -2)
