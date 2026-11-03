"""The 3x-attack-speed scaffold is inert until configured and never acts on the game."""
from types import SimpleNamespace

import pytest

from gbox import pso_speed as S
from gbox.registry import Unsupported


def test_scaffold_is_unconfigured_and_refuses_to_enable_without_touching_memory():
    assert S.configured() is False
    ad = SimpleNamespace(read_memory=lambda *a: pytest.fail('must not read before configured'),
                         write_memory=lambda *a: pytest.fail('must not write before configured'))
    with pytest.raises(Unsupported, match='not yet enabled|not configured|post-restart'):
        S.set_enabled(ad, 'gamecube', True)
    st = S.status(ad, 'gamecube')
    assert st['configured'] is False and st['factor'] == 3 and st['attack_speed_3x'] is False


def test_wrong_platform_is_refused():
    ad = SimpleNamespace(read_memory=lambda *a: pytest.fail('read'), write_memory=lambda *a: pytest.fail('write'))
    with pytest.raises(Unsupported, match='GameCube'):
        S.set_enabled(ad, 'dreamcast', True)


def test_cave_region_is_separate_from_crit_and_dispatcher():
    from gbox import pso_crit as C, pso_gc_live as G
    assert S.CAVE >= C.END                     # above the crit cave 0x80005000-0x80005100
    assert S.END <= 0x80006000                 # below the adventure cave
    assert S.CAVE >= G.END                      # above the live dispatcher region (<0x80005000)
