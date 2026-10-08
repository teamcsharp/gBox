from collections import Counter
import random

from gbox.gta_stories_models import _mesh_strips, stripify


def canonical(triangle):
    a, b, c = triangle
    return min((a, b, c), (b, c, a), (c, a, b))


def decoded(strips):
    result = []
    for strip in strips:
        for k in range(len(strip) - 2):
            tri = tuple(strip[k:k + 3])
            if len(set(tri)) != 3:
                continue
            if k % 2:
                tri = (tri[1], tri[0], tri[2])
            result.append(canonical(tri))
    return Counter(result)


def test_strip_growth_and_odd_length_joins_preserve_oriented_faces():
    cases = [
        [(0, 1, 2), (2, 1, 3), (2, 3, 4), (8, 9, 10)],
        [(0, 1, 2), (1, 2, 3), (4, 5, 6), (7, 8, 9)],
    ]
    grid = []
    for y in range(8):
        for x in range(8):
            a = y * 9 + x
            grid.extend([(a, a + 1, a + 9), (a + 9, a + 1, a + 10)])
    random.Random(42).shuffle(grid)
    cases.append(grid)
    for triangles in cases:
        expected = Counter(map(canonical, triangles))
        assert decoded(stripify(triangles)) == expected
        assert decoded(_mesh_strips(triangles, max_len=42)) == expected
