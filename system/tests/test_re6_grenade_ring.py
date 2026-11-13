"""RE6 Switch grenade ring: the ten-grenade flash ring on the verified spawn/detonate pair.

No live game: a fake emulator answers the controller's reads/calls and records every unit position write. The
native assets themselves are checked by their pinned sizes/hashes in test_merc_interventions.
"""
import math
import struct
import threading

import pytest

from gbox.mercs.titles import re6_switch_native as N

R = N.R
SPAWN, DETONATE = 0x18F2880, 0x18F29C0


@pytest.fixture(autouse=True)
def _flash_resources(monkeypatch):
    """The controller requires the character to carry flash id 0x115; the inventory layout is not what this tests."""
    monkeypatch.setattr(N.R, "inventory_items", lambda m, p: {0x115})
    monkeypatch.setattr(N.R, "unit_action", lambda m, unit: "cWpAction_wp_act_throw")
    monkeypatch.setattr(N.R, "game_man", lambda m, base: 0x90000000)
    yield


def ring_controller(hp_after=1000, spawn_fail_at=None, position=(1000.0, 800.0, -2000.0), flag=True):
    """A fake RE6 controller whose spawn/detonate succeed, capturing every unit position write."""
    ctl = N.Controller.__new__(N.Controller)
    ctl.base = 0x100000000
    ctl.player, ctl.sp = 0x200000000, 0x210000000
    ctl.generation = 0x100000002
    ctl.manager = ctl.player + 0x13A8
    ctl.heap = 0x220000000
    ctl.lock = threading.RLock()
    ctl.failed = ctl.recoverable = False
    ctl.mem, ctl.writes, ctl.spawns = {}, [], []
    hp_box = {"v": 1000}

    def put(at, data):
        ctl.mem.update({at + i: b for i, b in enumerate(data)})

    def read(at, n):
        if at == ctl.player + R.P_HP:
            return struct.pack("<h", hp_box["v"])
        return bytes(ctl.mem.get(at + i, 0) for i in range(n))

    def write(at, data):
        ctl.writes.append((at, bytes(data)))
        put(at, data)

    ctl.rd, ctl.write, ctl.q, ctl.put = read, write, lambda a: struct.unpack("<Q", read(a, 8))[0], put
    ctl.w = lambda a: struct.unpack("<I", read(a, 4))[0]
    ctl.check = ctl.check_build = lambda: None
    ctl.attach = lambda: None
    ctl.detach_completed = lambda: None
    ctl.ready = lambda: (ctl.player, ctl.generation)
    ctl.wait = lambda predicate, timeout=1.0: predicate()
    put(ctl.base + R.S_PLAYER, struct.pack("<Q", ctl.sp))
    put(ctl.sp + R.P_FIRST, struct.pack("<Q", ctl.player))
    put(ctl.player, struct.pack("<Q", ctl.base + 0x2858318))      # the action manager's original vtable
    put(ctl.player + R.P_POS, struct.pack("<3f", *position))
    put(ctl.base + R.S_GAMEMAN, struct.pack("<Q", 0x90000000))
    put(0x90000000 + R.GM_PHASE, struct.pack("<i", R.PHASE_PLAYING))

    def call(off, *args, **kw):
        if off == SPAWN:
            n = len(ctl.spawns)
            if spawn_fail_at is not None and n == spawn_fail_at:
                return 0
            unit = 0x230000000 + n * 0x10000
            born = 5000 + n
            put(unit + 0x1308, struct.pack("<I", born))
            put(unit + 0x1300, struct.pack("<Q", ctl.player))
            ctl.spawns.append(unit)
            hp_box["v"] = hp_after                            # health reads back after the ring's blasts
            return unit
        put(args[0] + 0x28A0, b"\x01" if flag else b"\x00")   # RE6 1.0.2 does not write it (live 2026-11-11)
        return 1                                              # detonate confirmed
    ctl.call = call
    return ctl


def unit_writes(ctl):
    """{unit: (x, y, z)} for the position write each spawned unit received."""
    out = {}
    for at, data in ctl.writes:
        for unit in ctl.spawns:
            if at == unit + N.RING_UNIT_POS:
                out[unit] = struct.unpack("<3f", data)
    return out


def test_flash_ring_confirms_ten_evenly_spaced_expanding_grenades():
    ctl = ring_controller()
    result = ctl.grenade_ring("flash")
    assert result["state"] == "confirmed" and result["verified"] is True
    assert result["effect"] == "native_flash_ring" and result["op"] == "grenade_ring"
    assert result["kind"] == "flash" and result["requested"] == 10 and result["detonated"] == 10
    assert result["hp_before"] == 1000 and result["hp_after"] == 1000 and result["self_damage"] == 0
    assert len(result["grenades"]) == 10
    # every grenade reports the native void spawn's own generation, distinct per unit
    assert [g["projectile_generation"] for g in result["grenades"]] == [5000 + i for i in range(10)]

    px, py, pz = 1000.0, 800.0, -2000.0
    placed = unit_writes(ctl)
    assert len(placed) == 10
    radii, angles = [], []
    for i, unit in enumerate(ctl.spawns):
        x, y, z = placed[unit]
        assert y == pytest.approx(py)                         # the floor height is kept
        radii.append(math.hypot(x - px, z - pz))
        angles.append(math.atan2(z - pz, x - px) % (2 * math.pi))
    assert radii[0] == pytest.approx(N.RING_INNER_DEFAULT_CM)
    assert radii[-1] == pytest.approx(N.RING_RADIUS_DEFAULT_CM)
    assert radii == sorted(radii)
    for i, a in enumerate(angles):
        assert a == pytest.approx((2 * math.pi * i / 10) % (2 * math.pi), abs=1e-4)


def test_ring_radius_is_clamped_outward_for_self_safety():
    ctl = ring_controller()
    result = ctl.grenade_ring("flash", radius_cm=10.0, expand=False)
    assert result["radius_cm"] == N.RING_SELF_CLEAR_CM
    px, _py, pz = 1000.0, 800.0, -2000.0
    for x, _y, z in unit_writes(ctl).values():
        assert math.hypot(x - px, z - pz) == pytest.approx(N.RING_SELF_CLEAR_CM)


@pytest.mark.parametrize("kind,match", [("hand", "not yet verified"), ("incendiary", "not yet verified"),
                                        ("bogus", "unknown grenade kind")])
def test_unverified_kinds_are_refused_and_never_substituted(kind, match):
    ctl = ring_controller()
    with pytest.raises(N.Unavailable, match=match):
        ctl.grenade_ring(kind)
    assert ctl.spawns == []                                   # nothing spawned


def test_partial_ring_is_uncertain_not_replayed_and_recoverable():
    ctl = ring_controller(spawn_fail_at=3)
    result = ctl.grenade_ring("flash", count=10)
    assert result["state"] == "uncertain" and result["verified"] is False
    assert result["detonated"] == 3 and result["requested"] == 10
    assert "refused" in result["reason"]
    assert ctl.failed and ctl.recoverable                     # a new click is allowed; this one is never retried


def test_count_and_ripple_are_bounded():
    ctl = ring_controller()
    assert ctl.grenade_ring("flash", count=999, ripple_ms=99999)["requested"] == N.RING_COUNT_MAX
    assert ctl.grenade_ring("flash", count=0)["requested"] == 1


def test_kind_options_mark_only_flash_available():
    rows = {r["kind"]: r for r in N.Controller.grenade_kinds(ring_controller())}
    assert rows["flash"]["available"] is True and not rows["flash"]["reason"]
    assert rows["hand"]["available"] is False and rows["hand"]["reason"]
    assert rows["incendiary"]["available"] is False and rows["incendiary"]["reason"]
    # the launcher's shell rounds are implemented research kinds: listed, refused (no live receipt yet) and with their
    # own reason - the launcher ring reaches them through allow_unverified only
    assert set(rows) == {"flash", "hand", "incendiary", "shell1302", "shell1303", "shell1304"}
    for kind in ("shell1302", "shell1303", "shell1304"):
        assert rows[kind]["available"] is False and "launcher" in rows[kind]["reason"]


def test_ring_needs_a_living_player_and_flash_resources(monkeypatch):
    ctl = ring_controller()
    monkeypatch.setattr(N.R, "inventory_items", lambda m, p: set())
    with pytest.raises(N.Unavailable, match="resources"):
        ctl.grenade_ring("flash")
    assert ctl.spawns == []

def test_a_first_grenade_refusal_is_a_failed_ring_with_no_spawn():
    ctl = ring_controller(spawn_fail_at=0)
    result = ctl.grenade_ring("flash")
    assert result["state"] == "failed" and result["detonated"] == 0 and result["requested"] == 10
    assert "refused" in result["reason"]
    assert ctl.failed and ctl.recoverable


def test_a_missing_explosion_flag_does_not_fail_a_flash_that_detonated():
    """Live RE6 1.0.2 (2026-11-11): the detonate call returned 1 and the flash visibly bloomed on screen, but
    +0x28A0 stayed 0 and the whole ring aborted after one grenade. The call's 1 is the verified confirmation (the
    single flash uses the same test); the flag is evidence in the receipt, not the gate."""
    ctl = ring_controller(flag=False)
    result = ctl.grenade_ring("flash")
    assert result["state"] == "confirmed" and result["verified"] is True
    assert result["detonated"] == 10
    assert all(g["explosion_flag"] is False for g in result["grenades"])


def test_the_parameterised_hand_ring_gets_its_own_spawn_budget(monkeypatch):
    """The first live hand ring timed out at 1295 ms on the flash's 1 s budget (2026-11-11 13:51); the class spawn
    and detonate now carry CLASS_SPAWN_TIMEOUT_S and the initialized wait CLASS_WAIT_S."""
    monkeypatch.setattr(R, "inventory_items", lambda m, p: {0x113, 0x114, 0x115})
    ctl = ring_controller()
    ctl.stopped = lambda fn: fn()                     # the fake has no /proc: the install runs straight through
    ctl.install = lambda at, data: ctl.put(at, data)
    seen = {}
    real = ctl.call

    def recording(off, *args, **kw):
        if off == N.CLASSES.SPAWN_CLASS[0]:
            seen["spawn"] = kw.get("timeout")
            assert args == (ctl.player, ctl.base + N.CLASSES.CLASSES["hand"].dti)
            unit = 0x240000000
            ctl.put(unit + 0x1308, struct.pack("<I", 5001))
            ctl.put(unit + 0x1300, struct.pack("<Q", ctl.player))
            ctl.put(unit, struct.pack("<Q", ctl.base + N.CLASSES.CLASSES["hand"].vtable))
            ctl.spawns.append(unit)
            return unit
        if off == N.CLASSES.DETONATE_CLASS[0]:
            seen["detonate"] = kw.get("timeout")
            return 1
        return real(off, *args)

    ctl.call = recording
    ctl.wait = lambda predicate, timeout=1.0: True          # the action transition is the live probe's job
    result = ctl.grenade_ring("hand", count=1, radius_cm=600, inner_cm=600, allow_unverified=True)
    assert result["state"] == "confirmed" and result["kind"] == "hand" and result["detonated"] == 1
    assert seen["spawn"] == N.CLASS_SPAWN_TIMEOUT_S and seen["detonate"] == N.CLASS_SPAWN_TIMEOUT_S
    assert N.CLASS_SPAWN_TIMEOUT_S > 1.0 and N.CLASS_WAIT_S > 1.0


def test_a_hand_spawn_that_never_reaches_its_throw_action_says_what_it_built(monkeypatch):
    """The hand ring's live failure (2026-11-11 14:05) was the action wait, not the spawn budget: the receipt must
    carry the unit class and the action the parameterised factory actually built."""
    monkeypatch.setattr(R, "inventory_items", lambda m, p: {0x113})
    ctl = ring_controller()
    ctl.stopped = lambda fn: fn()
    ctl.install = lambda at, data: ctl.put(at, data)

    def call(off, *args, **kw):
        if off == N.CLASSES.SPAWN_CLASS[0]:
            unit = 0x240000000
            ctl.put(unit + 0x1308, struct.pack("<I", 5001))
            ctl.put(unit + 0x1300, struct.pack("<Q", ctl.player))
            ctl.put(unit, struct.pack("<Q", ctl.base + N.CLASSES.CLASSES["hand"].vtable))
            ctl.spawns.append(unit)
            return unit
        return 1

    ctl.call = call

    def never(predicate, timeout=1.0):
        raise N.Uncertain("native completion uncertain; request will not be replayed")

    ctl.wait = never
    result = ctl.grenade_ring("hand", count=1, radius_cm=600, inner_cm=600, allow_unverified=True)
    assert result["state"] in ("failed", "uncertain")
    assert "did not reach its placed action" in result["reason"] and "class=0x" in result["reason"]
