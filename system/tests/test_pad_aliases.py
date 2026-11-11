"""The pad-name aliases the walk scripts need: `ddown`/`dup`/`dleft`/`dright` must reach the injector.

`pso_boot_walk`'s `offline_game` step presses `("ddown", "a")`. `PAD_KEYS` only carried `down`/`up`/`left`/`right`, so
`win_send_keys` fell through to `_SCAN.get("ddown")` -> `(0, 0)` and dropped the direction silently - the game never saw it,
which is why the step failed with the mode still on the title screen (CP4 round 65/67).
"""
import pytest

from gbox import adapters as A


@pytest.mark.parametrize("alias,target", [
    ("ddown", "down"), ("dup", "up"), ("dleft", "left"), ("dright", "right"),
])
def test_the_digital_pad_aliases_reach_the_injector(alias, target):
    for player, keys in A.PAD_KEYS.items():
        assert keys.get(alias) == keys[target], (player, alias)
        assert A._SCAN.get(keys[alias]) not in (None, (0, 0)), (player, alias)


def test_the_walk_scripts_keys_all_have_scan_codes():
    """Every key a boot step presses must map to a scan code, or the step silently does nothing."""
    from gbox import pso_boot_walk as W
    missing = []
    for _name, keys, _check in W.BOOT_STEPS:
        for key in keys:
            mapped = A.PAD_KEYS[1].get(key, key)
            if A._SCAN.get(mapped, A._SCAN.get(str(mapped).lower(), (0, 0))) == (0, 0):
                missing.append(key)
    assert missing == [], missing
