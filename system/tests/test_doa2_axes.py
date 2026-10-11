import numpy as np
import pytest

from gbox import doa2_axes as S


def edge(a, b, rotation):
    return {'bone_a': a, 'bone_b': b, 'a_columns': np.eye(3).tolist(),
            'b_columns': np.asarray(rotation).tolist(), 'name': 'owned fixture'}


def test_constraint_direction_maps_positive_native_leg_axis_downward():
    left_thigh = [[0, -1, 0], [0, 0, -1], [1, 0, 0]]
    reverse_shin = np.diag([-1, 1, -1])
    result = S.solve([edge(6, 2, left_thigh), edge(7, 6, reverse_shin)], joint_ids=(2, 6, 7))
    thigh = np.asarray(result['rotations']['6'])
    shin = np.asarray(result['rotations']['7'])
    assert np.array_equal(thigh @ [0, 0, 1], [0, -1, 0])
    assert np.array_equal(shin @ [0, 0, -1], [0, -1, 0])
    assert result['translation_policy'] == 'not derived by this solver'


def test_solver_handles_reverse_graph_traversal_and_rejects_contradictory_cycle():
    rotation = np.diag([-1, 1, -1])
    result = S.solve([edge(0, 2, rotation)], anchor=0, joint_ids=(0, 2))
    assert np.array_equal(result['rotations']['2'], rotation)
    with pytest.raises(ValueError, match='inconsistent'):
        S.solve([edge(0, 2, rotation), edge(0, 2, np.eye(3))], joint_ids=(0, 2))


@pytest.mark.parametrize('matrix', [np.diag([-1, 1, 1]), np.eye(3) * 2, np.full((3, 3), np.nan)])
def test_non_rotation_bases_are_rejected(matrix):
    with pytest.raises(ValueError):
        S.solve([edge(0, 2, matrix)], joint_ids=(0, 2))


def test_disconnected_actual_evidence_is_not_filled_with_fictional_axes():
    with pytest.raises(ValueError, match='does not connect'):
        S.solve([edge(0, 2, np.eye(3))], joint_ids=(0, 1, 2))
