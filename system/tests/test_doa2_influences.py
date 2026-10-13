"""Donors with more than two bone influences per vertex are reduced before native SUP planning (#1385)."""
import numpy as np
import pytest

from gbox import doa2_swap as S
from gbox import doa2_sup_plan as P


def test_limit_influences_keeps_the_two_heaviest_and_renormalises():
    prims = [{
        'name': 'm0',
        'J': np.array([[3, 5, 7], [1, 1, 2], [4, 4, 4], [9, 0, 0]]),
        'W': np.array([[0.5, 0.3, 0.2], [0.25, 0.25, 0.5], [0.2, 0.3, 0.5], [1.0, 0.0, 0.0]]),
    }]
    out, report = S.limit_influences(prims, 2)
    j, w = out[0]['J'], out[0]['W']
    assert j.shape == (4, 2) and w.shape == (4, 2)
    assert j[0].tolist() == [3, 5] and w[0].tolist() == pytest.approx([0.625, 0.375])      # 0.2 on joint 7 dropped
    assert sorted(zip(j[1].tolist(), w[1].tolist())) == [(1, 0.5), (2, 0.5)]              # duplicates merged, nothing dropped
    assert j[2].tolist() == [4, 4] and w[2].tolist() == pytest.approx([1.0, 0.0])           # one real joint
    assert j[3].tolist() == [9, 9] and w[3].tolist() == pytest.approx([1.0, 0.0])
    assert out[0]['owner'].tolist() == [3, 1, 4, 9]
    assert report == {'max_influences': 2, 'vertices_reduced': 1, 'largest_weight_dropped': 0.2}
    # the planner accepts every reduced row
    for row_j, row_w in zip(j, w):
        P._influence(row_j, row_w)


def test_limit_influences_rejects_mismatched_arrays():
    with pytest.raises(ValueError, match="share a shape"):
        S.limit_influences([{'J': np.zeros((2, 3), int), 'W': np.zeros((2, 2))}])
