import numpy as np
import pytest

from gbox.ff7_swap import pair_quads


def _tris(second_col=None):
    return [((0, 1, 2), ((255, 0, 0), (0, 255, 0), (0, 0, 255))),
            ((2, 1, 3), ((0, 0, 255), second_col or (0, 255, 0), (255, 255, 255)))]


def test_flat_quad_preserves_both_triangles_and_colours():
    quads, rest = pair_quads(_tris(), [(0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0)])
    assert rest == []
    ids, colours = quads[0]
    expanded = [(tuple(ids[i] for i in order), tuple(colours[i] for i in order))
                for order in ((0, 1, 2), (2, 1, 3))]
    assert expanded == _tris()


@pytest.mark.parametrize('fourth', [(1, 1, 1), (1, 1, -1), (-1, -1, 0), (0, 0, 0)])
def test_folded_reversed_and_degenerate_pairs_remain_independent(fourth):
    tris = _tris()
    assert pair_quads(tris, [(0, 0, 0), (1, 0, 0), (0, 1, 0), fourth]) == ([], tris)


def test_integer_rounding_does_not_allow_a_small_fold():
    tris = _tris()
    assert pair_quads(tris, [(0, 0, 0), (1000, 0, 0), (0, 1000, 0), (1000, 1000, 1)]) == ([], tris)


def test_coloured_seam_cannot_be_replaced_by_one_quad():
    tris = _tris((255, 0, 0))
    assert pair_quads(tris, [(0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0)]) == ([], tris)


def test_full_s16_coordinate_range_does_not_overflow_facing_test():
    vertices = [(-32768, -32768, 0), (32767, -32768, 0),
                (-32768, 32767, 0), (32767, 32767, 0)]
    assert len(pair_quads(_tris(), vertices)[0]) == 1
    vertices[3] = (32767, 32767, 1)
    assert pair_quads(_tris(), vertices) == ([], _tris())


def test_rejected_fold_can_hide_a_visible_triangle_under_native_quad_culling():
    vertices = np.array([(0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 2)])
    view = np.array((1, 1, .5))
    signs = [np.cross(vertices[b]-vertices[a], vertices[c]-vertices[a]) @ view
             for (a, b, c), _ in _tris()]
    assert signs[0] * signs[1] < 0
    assert len(pair_quads(_tris(), vertices)[1]) == 2
