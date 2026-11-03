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


# --- phase (b): dispatcher-v5 extra-update, both gate variants (prepared, inert) ---
import struct

from gbox import pso_gc_live as L


def _words(b):
    return struct.unpack(">%dI" % (len(b) // 4), b)


def test_default_dispatcher_is_byte_identical_no_regression():
    # The shipped GBPSOGC4 dispatcher must be untouched when no speed gate is requested.
    assert L.dispatcher() == L.CODE
    assert L.dispatcher(speed_gate=None) == L.CODE


def test_speed_factor_must_be_at_least_two():
    with pytest.raises(ValueError, match="speed_factor"):
        L.dispatcher(speed_gate=S.GATE_A8, speed_factor=1)


def test_both_gate_variants_build_fit_and_extend_the_stock_dispatcher():
    for gate in (S.GATE_A8, S.gate_from_326([1, 5])):
        v5 = S.dispatcher_v5(gate, factor=3)
        assert len(v5) < 0x300                      # still fits below HEADER
        assert len(v5) > len(L.CODE)                # the extra-update block was spliced in
        assert v5[:24] == L.CODE[:24]               # same prologue (shared dispatcher)


_BASE = _words(L.CODE)


def test_a8_gate_tests_hit_record_count_and_runs_factor_minus_one_updates():
    w = _words(S.dispatcher_v5(S.GATE_A8, factor=3))
    assert 0x818300A8 in w                          # lwz r12,0xA8(r3)  (active hit-records)
    assert 0x40850000 in [x & 0xFFFF0000 for x in w]  # ble cr1,skip (attacking iff > 0)
    # exactly one extra bcctrl (the loop body) over the stock dispatcher's own queue calls
    assert w.count(0x4E800421) == _BASE.count(0x4E800421) + 1
    assert 0x3BE00002 in w                          # li r31,2  == factor-1 extra updates
    assert w.count(0x4E800420) == _BASE.count(0x4E800420) == 1   # stock tail-chain bctr preserved


def test_326_gate_tests_action_state_against_each_locked_value():
    w = _words(S.dispatcher_v5(S.gate_from_326([1, 5]), factor=3))
    assert 0xA1830326 in w                          # lhz r12,0x326(r3)
    assert 0x2C8C0001 in w and 0x2C8C0005 in w      # cmpwi cr1,r12,1 ; cmpwi cr1,r12,5
    assert w.count(0x4E800421) == _BASE.count(0x4E800421) + 1


def test_gate_from_probe_uses_a_locked_326_gate_else_falls_back_to_a8():
    ad = SimpleNamespace()
    assert S.gate_from_probe(ad) is None            # nothing probed yet
    assert S.preferred_gate(ad) is S.GATE_A8        # deterministic fallback
    ad._pso_speed_probe = {0: {"n": 300, "atk": 200,
                               "gate": {"off": 0x326, "values": [1], "desc": "x", "locked": True}}}
    g = S.gate_from_probe(ad)
    assert g and g["kind"] == "s326" and g["values"] == [1]
    assert S.preferred_gate(ad) is g or S.preferred_gate(ad)["values"] == [1]


def test_326_gate_not_locked_is_ignored_by_gate_from_probe():
    ad = SimpleNamespace(_pso_speed_probe={0: {"gate": {"off": 0x326, "values": [1], "locked": False}}})
    assert S.gate_from_probe(ad) is None
