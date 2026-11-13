import struct
import threading

import pytest

from gbox.mercs.titles import re6_switch_shell_probe as P
from gbox.mercs.native.re6_061d2a06 import shell_probe as S


class Memory:
    base, player, unit = 0x100000000, 0x200000000, 0x210000000
    action, table, sp, heap = 0x220000000, 0x230000000, 0x240000000, 0x250000000
    generation, born = 55, 66

    def __init__(self):
        self.memory, self.writes, self.calls = {}, [], []
        self.lock = threading.RLock()
        self.put(self.unit, "Q", self.base + S.SHELLS["shell1304"].vtable)
        self.put(self.unit + 0x1300, "Q", self.player)
        self.put(self.unit + 0x1308, "I", self.born)
        self.put(self.unit + 0xC, "I", 0x201)
        self.put(self.unit + 0x13A8, "Q", self.base + S.MANAGER_VT)
        self.put(self.unit + 0x13B0, "Q", self.unit)
        self.put(self.unit + 0x13C0, "I", 27)
        self.put(self.unit + 0x13D0, "Q", self.table)
        self.put(self.unit + 0x13F0, "Q", self.action)
        self.put(self.table + 17 * 8, "Q", self.action)
        self.put(self.table + 19 * 8, "Q", self.action + 0x1000)
        self.put(self.action + 0x1000, "Q", self.base + S.SHELL_EXPLODE_VT)
        self.put(self.action + 0x1010, "Q", self.unit)
        self.put(self.action, "Q", self.base + S.SHELL_EXPLODE_VT)
        self.put(self.action + 0x10, "Q", self.unit)
        self.put(self.action + 0x20, "Q", 17)
        self.put(self.action + 0x28, "B", 2)
        self.put(self.action + 0x30, "Q", self.unit)
        self.put(self.unit + 0x2308, "I", 1)
        self.put(self.unit + 0x2060, "I", 4)
        self.put(self.unit + 0x2070, "I", 4)
        self.put(self.base + P.R.S_PLAYER, "Q", self.sp)
        self.put(self.sp + P.R.P_FIRST, "Q", self.player)
        self.put(self.player + P.R.P_POS, "3f", 0., 0., 0.)
        self.detach_count = 0

    def put(self, at, fmt, *vals):
        for i, value in enumerate(struct.pack("<" + fmt, *vals)):
            self.memory[at + i] = value

    def rd(self, at, n):
        return bytes(self.memory.get(at + i, 0) for i in range(n))

    def q(self, at): return struct.unpack("<Q", self.rd(at, 8))[0]
    def w(self, at): return struct.unpack("<I", self.rd(at, 4))[0]
    def check(self): pass
    def ready(self): return self.player, self.generation
    def attach(self): pass
    def detach_completed(self): self.detach_count += 1

    def write(self, at, data):
        self.writes.append((at, data))
        for i, value in enumerate(data): self.memory[at + i] = value

    def call(self, off, *args, **kwargs):
        self.calls.append((off, args))
        if off == S.SPAWN[0]:
            self.put(self.heap + P.PACKET_OFFSET + 16, "QI", self.unit, 2)
            return self.unit
        return 1


def inspect(m):
    return P.inspect_shell(m, m.unit, m.born, "shell1304")


@pytest.mark.parametrize("phase,pair,emitted", [
    (0, (4, 4), False), (1, (4, 4), False), (2, (1, 1), False),
    (2, (3, 3), False), (2, (4, 3), False), (2, (3, 4), False),
    (2, (4, 4), True), (3, (4, 4), False),
])
def test_effect_receipt_requires_native_phase_and_actual_enemy_attack(phase, pair, emitted):
    m = Memory()
    m.put(m.action + 0x28, "B", phase)
    m.put(m.unit + 0x2060, "I", pair[0])
    m.put(m.unit + 0x2070, "I", pair[1])
    m.put(m.unit + 0x3954, "I", 4)  # Arm bit alone proves nothing.
    result = inspect(m)
    assert result["emitted"] is emitted
    assert m.writes == [] and m.calls == []


@pytest.mark.parametrize("change", ["unit_vt", "owner", "generation", "manager", "manager_owner",
                                   "action_owner", "action_unit", "slot", "count", "oversize_queue"])
def test_invalid_identity_or_bounds_cannot_be_a_receipt(change):
    m = Memory()
    changes = {
        "unit_vt": (m.unit, "Q", m.base + S.SHELLS["shell1302"].vtable),
        "owner": (m.unit + 0x1300, "Q", m.player + 8),
        "generation": (m.unit + 0x1308, "I", m.born + 1),
        "manager": (m.unit + 0x13A8, "Q", 0),
        "manager_owner": (m.unit + 0x13B0, "Q", m.player),
        "action_owner": (m.action + 0x10, "Q", m.player),
        "action_unit": (m.action + 0x30, "Q", m.player),
        "slot": (m.table + 17 * 8, "Q", 0),
        "count": (m.unit + 0x13C0, "I", 65),
        "oversize_queue": (m.unit + 0x2308, "I", 9),
    }
    m.put(*changes[change])
    with pytest.raises(P.Unavailable): inspect(m)
    assert m.writes == [] and m.calls == []


def test_throw_wep_action_is_not_shell_explosion():
    m = Memory()
    m.put(m.action, "Q", m.base + 0x288C6C8)
    assert not inspect(m)["emitted"]


def test_recycled_unit_during_sampling_is_rejected():
    m = Memory()
    rd = m.rd
    def racing_read(at, n):
        data = rd(at, n)
        if at == m.action + 0x28:
            m.put(m.unit + 0x1308, "I", m.born + 1)
        return data
    m.rd = racing_read
    with pytest.raises(P.AllocationLost, match="during receipt sampling"): inspect(m)


@pytest.fixture
def probe(monkeypatch):
    m = Memory()
    monkeypatch.setattr(P, "_install_images", lambda _: None)
    monkeypatch.setattr(P.R, "inventory_guns", lambda *_: {0x112: 0})
    monkeypatch.setattr(P.R, "owned_throwables", lambda *_: [])
    clock = iter(i * .02 for i in range(1000))
    monkeypatch.setattr(P.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(P.time, "sleep", lambda _: None)
    return m


@pytest.mark.parametrize('units', [None, [None], [{'kind': 'remote', 'action': 'throw'}],
                                 [{'kind': 'remote', 'action': 'setting'}],
                                 [{'kind': 'remote', 'action': 'bomb'}]])
def test_shell_probe_refuses_unknown_or_present_live_bombs_under_shared_lock(probe, monkeypatch, units):
    def census(ctl, base, player):
        assert ctl is probe and ctl.lock._is_owned()
        assert (base, player) == (probe.base, probe.player)
        return units
    monkeypatch.setattr(P.R, 'owned_throwables', census)
    with pytest.raises(P.Unavailable, match='bomb'):
        P.probe_one(probe, (700., 0., 0.))
    assert probe.calls == probe.writes == [] and probe.detach_count == 0
    assert not getattr(probe, '_shell_probe_epochs', set())


def test_shell_probe_rereads_census_after_preparation_before_spawning(probe, monkeypatch):
    samples = iter(([], [{'kind': 'remote', 'action': 'setting'}]))
    def census(ctl, *_):
        assert ctl.lock._is_owned()
        return next(samples)
    monkeypatch.setattr(P.R, 'owned_throwables', census)
    out = P.probe_one(probe, (700., 0., 0.))
    assert out['state'] == 'failed' and out['spawned'] == 0
    assert probe.calls == probe.writes == [] and probe.detach_count == 1
    assert not getattr(probe, '_shell_probe_epochs', set())


def test_shell_probe_census_cannot_cross_player_lifetimes(probe, monkeypatch):
    def census(ctl, *_):
        ctl.ready = lambda: (ctl.player, ctl.generation + 1)
        return []
    monkeypatch.setattr(P.R, 'owned_throwables', census)
    with pytest.raises(P.AllocationLost, match='census'):
        P.probe_one(probe, (700., 0., 0.))
    assert not probe.calls and not probe.writes


def test_shell_probe_allocator_change_during_census_refuses_before_attach(probe, monkeypatch):
    idle = [True]
    def census(ctl, *_):
        idle[0] = False
        return []
    monkeypatch.setattr(P.R, 'owned_throwables', census)
    with pytest.raises(P.Unavailable, match='allocator'):
        P.probe_one(probe, (700., 0., 0.), allowed=lambda: idle[0])
    assert not probe.calls and not probe.writes and probe.detach_count == 0


def test_shell_probe_allocator_change_after_image_preparation_prevents_spawn(probe, monkeypatch):
    idle = [True]
    monkeypatch.setattr(P, '_install_images', lambda ctl: idle.__setitem__(0, False))
    out = P.probe_one(probe, (700., 0., 0.), allowed=lambda: idle[0])
    assert out['state'] == 'failed' and not out['spawned']
    assert not probe.calls and not probe.writes
    assert not getattr(probe, '_shell_probe_epochs', set())


def test_shell_probe_rechecks_player_clearance_after_final_bomb_census(probe, monkeypatch):
    reads = []
    def census(ctl, *_):
        reads.append(True)
        if len(reads) == 2:
            ctl.put(ctl.player + P.R.P_POS, '3f', 200., 0., 0.)
        return []
    monkeypatch.setattr(P.R, 'owned_throwables', census)
    out = P.probe_one(probe, (700., 0., 0.))
    assert out['state'] == 'failed' and not out['spawned'] and 'too close' in out['reason']
    assert not probe.calls and not probe.writes


def test_emission_stays_unverified_and_probe_is_not_replayed(probe):
    result = P.probe_one(probe, (700., 0., 0.), timeout_s=.05)
    assert result["spawned"] == result["detonated"] == 1
    assert result["verified"] is False
    assert result["state"] == "uncertain"
    assert probe.calls == [(S.SPAWN[0], (probe.player, probe.generation,
                                        probe.base + S.SHELLS["shell1304"].dti,
                                        probe.heap + P.PACKET_OFFSET))]
    assert probe.detach_count == 1
    with pytest.raises(P.Unavailable, match="not replayed"):
        P.probe_one(probe, (700., 0., 0.))
    assert len(probe.calls) == 1


def test_allocation_and_arm_without_effect_do_not_count(probe):
    probe.put(probe.action + 0x28, "B", 1)
    result = P.probe_one(probe, (700., 0., 0.), timeout_s=.05)
    assert result["spawned"] == result["armed"] == 1
    assert result["detonated"] == 0 and result["verified"] is False
    assert [call[0] for call in probe.calls] == [S.SPAWN[0], S.ARM[0]]
    # The only controller write is its private packet, never health, equipment or the actor.
    assert len(probe.writes) == 1
    assert probe.writes[0][0] == probe.heap + P.PACKET_OFFSET


def test_completion_timeout_retains_uncertainty_and_blocks_replay(probe):
    def uncertain(*args, **kwargs):
        raise P.Uncertain("native completion uncertain")
    probe.call = uncertain
    result = P.probe_one(probe, (700., 0., 0.), timeout_s=.05)
    assert result["state"] == "uncertain" and result["detonated"] == 0
    assert probe.failed and probe.recoverable
    with pytest.raises(P.Unavailable, match="not replayed"):
        P.probe_one(probe, (700., 0., 0.))


def test_probe_waits_for_native_flight_and_action_initialization(probe, monkeypatch):
    probe.put(probe.unit + 0xC, "I", 0x101)
    probe.put(probe.unit + 0x13C0, "I", 0)
    probe.put(probe.unit + 0x13F0, "Q", 0)
    sleeps = []
    def initialized(_):
        sleeps.append(True)
        if len(sleeps) == 2:
            assert len(probe.calls) == 1  # No arm request before native initialization.
            probe.put(probe.unit + 0xC, "I", 0x201)
            probe.put(probe.unit + 0x13C0, "I", 27)
    monkeypatch.setattr(P.time, "sleep", initialized)
    result = P.probe_one(probe, (700., 0., 0.), timeout_s=.05)
    assert result["armed"] == 1
    assert [call[0] for call in probe.calls] == [S.SPAWN[0], S.ARM[0]]
    assert len(sleeps) >= 2


def test_uninitialized_shell_does_not_get_an_arm_request(probe):
    probe.put(probe.unit + 0xC, "I", 0x101)
    probe.put(probe.unit + 0x13F0, "Q", 0)
    result = P.probe_one(probe, (700., 0., 0.), timeout_s=.05)
    assert result["state"] == "uncertain" and "initialization" in result["reason"]
    assert result["armed"] == 0 and result["detonated"] == 0
    assert len(probe.calls) == 1


def test_round_transition_during_initialization_stops_before_arm(probe, monkeypatch):
    probe.put(probe.unit + 0xC, "I", 0x101)
    probe.put(probe.unit + 0x13F0, "Q", 0)
    def transition(_): probe.ready = lambda: (probe.player, probe.generation + 1)
    monkeypatch.setattr(P.time, "sleep", transition)
    result = P.probe_one(probe, (700., 0., 0.), timeout_s=.05)
    assert "round or player changed" in result["reason"]
    assert result["armed"] == 0 and len(probe.calls) == 1


@pytest.mark.parametrize("point", [(0., 0., 0.), (600., 0., 0.), (float("nan"), 0., 0.)])
def test_unsafe_points_refuse_before_native_calls(probe, point):
    with pytest.raises(P.Unavailable): P.probe_one(probe, point)
    assert probe.calls == [] and probe.writes == []


def test_second_player_clearance_is_also_required(probe):
    other = probe.player + 0x10000
    probe.put(probe.sp + P.R.P_FIRST + 8, "Q", other)
    probe.put(other + P.R.P_POS, "3f", 690., 0., 0.)
    with pytest.raises(P.Unavailable, match="too close"):
        P.probe_one(probe, (700., 0., 0.))
    assert probe.calls == []


@pytest.mark.parametrize("before,after,born_delta,expected", [
    ("cEm1000ActWait", "cEm1000ActDmgIce", 0, True),
    ("cEmAnimalActRun", "cEmAnimalActDeadIce", 0, True),
    ("cEm1000ActDmgIce", "cEm1000ActDmgIce", 0, False),
    ("cEm1000ActWait", "cEm1000ActDmgIce", 1, False),
    ("cEm1000ActWait", "cEm1000ActDmgFlash", 0, False),
])
def test_ice_evidence_requires_new_reaction_and_same_enemy(monkeypatch, before, after, born_delta, expected):
    m = Memory()
    m.put(m.unit + P.R.E_HP, "h", 100)
    row = {"unit": m.unit, "generation": m.born, "vtable": m.q(m.unit),
           "action": before, "hp": 300}
    m.put(m.unit + 0x1308, "I", m.born + born_delta)
    monkeypatch.setattr(P.R, "unit_action", lambda *_: after)
    observations = P.ice_changes(m, [row])
    assert bool(observations) is expected
    assert m.writes == [] and m.calls == []


def test_target_baseline_is_bounded_and_ignores_dead_or_distant_enemies(monkeypatch):
    m = Memory()
    manager, array = 0x260000000, 0x270000000
    m.put(m.base + P.R.S_ENEMY, "Q", manager)
    m.put(manager + P.R.E_COUNT, "I", 11)
    m.put(manager + P.R.E_ARRAY, "Q", array)
    units = [m.unit + i * 0x10000 for i in range(11)]
    m.put(array, "11Q", *units)
    for i, unit in enumerate(units):
        m.put(unit, "Q", 0x280000000)
        m.put(unit + 0x1308, "I", i + 1)
        m.put(unit + P.R.E_POS, "3f", float(i), 0., 0.)
        m.put(unit + P.R.E_HP, "h", 100)
    m.put(units[0] + P.R.E_HP, "h", 0)
    m.put(units[-1] + P.R.E_POS, "3f", 5000., 0., 0.)
    monkeypatch.setattr(P.R, "unit_action", lambda *_: "cEm1000ActWait")
    baseline = P.nearby_targets(m, (0., 0., 0.))
    assert [row["unit"] for row in baseline] == units[1:9]
    assert m.writes == [] and m.calls == []
