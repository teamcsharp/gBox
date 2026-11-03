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


# --- phase (a): in-bot attack-state probe ---
_P = 0x80DA0000


class PM:
    def __init__(self, a8, s324, s2e4):
        self.a8, self.s324, self.s2e4 = a8, s324, s2e4

    def u32(self, a):
        return self.a8 if a == _P + 0xA8 else 0

    def u16(self, a):
        return {_P + 0x324: self.s324, _P + 0x2E4: self.s2e4}.get(a, 0)


def test_probe_learns_the_attack_gate_from_the_hitrecord_signal():
    ad = SimpleNamespace()
    for _ in range(200):                                  # idle: no hit-records, action id 0
        S.probe_tick(ad, 0, PM(0, 1, 0), _P)
    for _ in range(200):                                  # attacking: hit-records present, action id 0x24
        out = S.probe_tick(ad, 0, PM(1, 1, 0x24), _P)
    gate = S.speed_probe_status(ad)[0]["gate"]
    assert gate and gate["off"] == 0x2E4 and 0x24 in gate["values"] and gate["locked"] is True
    assert out["speed_probe_locked"] is True and out["speed_probe_atk"] == 200
    # +0x324 was the same (1) idle vs attacking, so it is NOT chosen as the discriminator
    assert "0x324" not in (gate["desc"])


def test_probe_is_fail_soft_on_bad_reads():
    class Bad:
        def u32(self, a): raise RuntimeError("boom")
        def u16(self, a): return 0
    out = S.probe_tick(SimpleNamespace(), 0, Bad(), _P)
    assert "speed_probe_err" in out
