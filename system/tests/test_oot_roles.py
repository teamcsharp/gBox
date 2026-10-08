import numpy as np

from gbox.oot_swap import guess_roles


def test_skirt_below_feet_is_not_mistaken_for_a_leg():
    # Zelda's 17-limb OoT skeleton, first standing animation frame.
    positions = np.array([
        [0, 2523, 14], [0, 2523, 14], [248, 2024, -95], [252, 1145, 101],
        [-252, 2024, -83], [-248, 1144, 109], [0, 1973, 11], [0, 1073, 5],
        [0, 373, 1], [0, 2523, 14], [450, 3123, -37], [639, 2449, -56],
        [800, 1874, 0], [-450, 3123, -37], [-662, 2455, -85], [-800, 1874, 0],
        [0, 3623, 13],
    ])
    parents = [-1, 0, 1, 2, 1, 4, 1, 6, 7, 0, 9, 10, 11, 9, 13, 14, 9]
    roles, _ = guess_roles(positions, parents)
    assert roles['head'] == 16
    assert (roles['l_upper'], roles['l_fore'], roles['l_hand']) == (10, 11, 12)
    assert (roles['r_upper'], roles['r_fore'], roles['r_hand']) == (13, 14, 15)
    assert (roles['l_thigh'], roles['l_shin']) == (2, 3)
    assert (roles['r_thigh'], roles['r_shin']) == (4, 5)
    assert not set(range(6, 9)) & set(roles.values())
