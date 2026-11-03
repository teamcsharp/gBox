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
    def __init__(self, a8, s324, s2e4, s326=0):
        self.a8, self.s324, self.s2e4, self.s326 = a8, s324, s2e4, s326

    def u32(self, a):
        return self.a8 if a == _P + 0xA8 else 0

    def u16(self, a):
        return {_P + 0x324: self.s324, _P + 0x2E4: self.s2e4, _P + 0x326: self.s326}.get(a, 0)


def test_probe_learns_the_attack_gate_from_action_state_326():
    ad = SimpleNamespace()
    for _ in range(200):                                  # idle: no hit-records, action-state +0x326 = 5
        S.probe_tick(ad, 0, PM(0, 1, 0, s326=5), _P)
    for _ in range(200):                                  # attacking: hit-records present, +0x326 = 1
        out = S.probe_tick(ad, 0, PM(1, 1, 0, s326=1), _P)
    gate = S.speed_probe_status(ad)[0]["gate"]
    # +0x326 separates (attack=1 vs idle=5); +0x324 (always 1) and +0x2E4 (always 0) do not
    assert gate and gate["off"] == 0x326 and 1 in gate["values"] and gate["locked"] is True
    assert out["speed_probe_locked"] is True and out["speed_probe_atk"] == 200


def test_probe_falls_back_to_2e4_when_326_does_not_separate():
    ad = SimpleNamespace()
    for _ in range(200):
        S.probe_tick(ad, 0, PM(0, 1, 0, s326=7), _P)      # +0x326 = 7 idle
    for _ in range(200):
        S.probe_tick(ad, 0, PM(1, 1, 0x24, s326=7), _P)   # +0x326 = 7 while attacking too -> no separation
    gate = S.speed_probe_status(ad)[0]["gate"]
    assert gate and gate["off"] == 0x2E4 and 0x24 in gate["values"]   # falls back to +0x2E4


def test_probe_is_fail_soft_on_bad_reads():
    class Bad:
        def u32(self, a): raise RuntimeError("boom")
        def u16(self, a): return 0
    out = S.probe_tick(SimpleNamespace(), 0, Bad(), _P)
    assert "speed_probe_err" in out
