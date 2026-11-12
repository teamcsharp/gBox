"""RE5's parameterised spawn/explode pair: the class as an argument.

No live game: the images are derived from the pinned, verified blobs and their replaced instructions checked word
for word; the controller runs against a fake emulator that records every native call and the class it was handed.
"""
import math
import struct
import threading

import pytest

from gbox.mercs.native.re5_ebffdb22 import classes as C
from gbox.mercs.titles import re5_switch_native as N

R = N.R
SPAWN, EXPLODE = 0x118E820, 0x118E9D0
FLASH_VT = 0x1C5EF58


# ---- the derived images ----------------------------------------------------------------------------------------------------

def test_the_parameterised_spawn_takes_the_class_in_x2():
    old = struct.unpack(f"<{len(C.IMAGES['spawn']) // 4}I", C.IMAGES["spawn"])
    new = struct.unpack(f"<{len(C.SPAWN_CLASS_BYTES) // 4}I", C.SPAWN_CLASS_BYTES)
    assert [(i, hex(old[i]), hex(new[i])) for i in range(len(new)) if old[i] != new[i]] == [
        (12, "0xf0005f01", "0xaa0203e1"),          # adrp x1 (FLASH_DTI) -> orr x1, xzr, x2
        (13, "0x9114e021", "0xd503201f")]          # add x1, x1, #0x538 -> nop
    assert C.SPAWN_CLASS[:3] == (SPAWN, "spawn_class", 432)


def test_the_parameterised_explode_takes_the_vtable_item_and_update():
    old = struct.unpack(f"<{len(C.IMAGES['explode']) // 4}I", C.IMAGES["explode"])
    new = struct.unpack(f"<{len(C.EXPLODE_CLASS_BYTES) // 4}I", C.EXPLODE_CLASS_BYTES)
    assert [(i, hex(old[i]), hex(new[i])) for i in range(len(new)) if old[i] != new[i]] == [
        (4, "0x90005684", "0xd503201f"),           # adrp x4 (FLASH_VT) -> nop
        (5, "0x913d6084", "0xd503201f"),           # add x4, x4, #0xf58 -> nop
        (47, "0x52802103", "0x2a0503e3"),          # movz w3, #0x108 -> orr w3, wzr, w5
        (55, "0x97da48e9", "0xd63f00c0")]          # bl FLASH_UPDATE -> blr x6
    assert C.EXPLODE_CLASS[:3] == (EXPLODE, "explode_class", 248)


def test_a_changed_source_image_is_refused_instead_of_patched(monkeypatch):
    broken = bytearray(C.IMAGES["explode"])
    broken[47 * 4:48 * 4] = b"\x00\x00\x00\x00"
    monkeypatch.setitem(C.IMAGES, "explode", bytes(broken))
    with pytest.raises(ValueError, match="no longer configures the flash item"):
        C.explode_with_class()


def test_the_class_family_has_one_update_for_the_flash_and_one_for_the_bomb():
    assert C.FLASH_UPDATE_OFF == 0x820E50 and C.BOMB_UPDATE_OFF == 0x806B80
    assert C.CLASSES["flash"].item == 0x108
    assert [C.CLASSES[k].item for k in ("hand", "incendiary")] == [0x106, 0x107]
    assert C.image_bytes("spawn_class") == C.SPAWN_CLASS_BYTES
    assert C.image_bytes("spawn") == C.IMAGES["spawn"]


# ---- the controller path ---------------------------------------------------------------------------------------------------

def ring_controller(unit_vtable=FLASH_VT, spawn_fail_at=None, position=(1000.0, 800.0, -2000.0)):
    ctl = N.Controller.__new__(N.Controller)
    ctl.base = 0x100000000
    ctl.player, ctl.sp = 0x200000000, 0x210000000
    ctl.generation = 0x100000002
    ctl.heap = 0x220000000
    ctl.lock = threading.RLock()
    ctl.failed = ctl.recoverable = False
    ctl.mem, ctl.writes, ctl.spawns, ctl.calls = {}, [], [], []
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

    ctl.rd, ctl.write, ctl.put = read, write, put
    ctl.q = lambda a: struct.unpack("<Q", read(a, 8))[0]
    ctl.w = lambda a: struct.unpack("<I", read(a, 4))[0]
    ctl.check = ctl.check_build = lambda: None
    ctl.attach = lambda: None
    ctl.detach_completed = lambda: None
    ctl.projectile = lambda unit, born: None
    ctl.ready = lambda: (ctl.player, ctl.generation)
    ctl.wait = lambda predicate, timeout=1.0: predicate()
    put(ctl.base + R.S_PLAYER, struct.pack("<Q", ctl.sp))
    put(ctl.player, struct.pack("<Q", ctl.base + 0x1C290C8))
    put(ctl.player + R.P_POS, struct.pack("<3f", *position))

    def call(off, *args):
        ctl.calls.append((off, args))
        if off == SPAWN:
            n = len(ctl.spawns)
            if spawn_fail_at is not None and n == spawn_fail_at:
                return 0
            unit = 0x230000000 + n * 0x10000
            born = 5000 + n
            put(unit, struct.pack("<Q", ctl.base + unit_vtable))
            put(unit + 0x1A00, struct.pack("<Q", born))
            put(unit + 0x1B28, struct.pack("<I", 29))
            put(unit + 0x1B88, b"\x01")
            put(unit + 0x28A0, b"\x01")
            ctl.spawns.append(unit)
            hp_box["v"] = 1000
            return unit
        return 1
    ctl.call = call
    return ctl


HAND_VT = 0x1C5EF98          # a hand class vtable the table does not carry: the wrapper must take the carried one


def test_a_hand_ring_hands_the_hand_class_to_the_same_verified_wrappers():
    ctl = ring_controller(unit_vtable=HAND_VT)
    result = ctl.grenade_ring("hand", allow_unverified=True, count=2, expand=False)
    assert result["state"] == "confirmed" and result["kind"] == "hand"
    assert result["effect"] == "native_hand_ring" and result["detonated"] == 2
    spawns = [c for c in ctl.calls if c[0] == SPAWN]
    assert len(spawns) == 2 and all(a == (ctl.player, ctl.generation, 0x1D714C8) for _o, a in spawns)
    detonations = [c for c in ctl.calls if c[0] == EXPLODE]
    assert len(detonations) == 2
    for _off, args in detonations:
        unit, born, player, generation, vtable, item, update = args
        assert player == ctl.player and generation == ctl.generation
        assert vtable == ctl.base + HAND_VT and item == 0x106
        assert update == ctl.base + C.BOMB_UPDATE_OFF


def test_the_flash_ring_keeps_its_verified_values_and_update():
    ctl = ring_controller()
    result = ctl.grenade_ring("flash", count=1)
    assert result["state"] == "confirmed" and result["effect"] == "native_flash_ring"
    spawn_args = next(a for o, a in ctl.calls if o == SPAWN)
    assert spawn_args == (ctl.player, ctl.generation, 0x1D71538)
    explode_args = next(a for o, a in ctl.calls if o == EXPLODE)
    assert explode_args[4] == ctl.base + FLASH_VT and explode_args[5] == 0x108
    assert explode_args[6] == ctl.base + C.FLASH_UPDATE_OFF


def test_a_flash_allocation_of_another_class_is_refused():
    ctl = ring_controller(unit_vtable=0x1C5EF58 + 0x40)
    result = ctl.grenade_ring("flash", count=1)
    assert result["state"] == "failed" and "verified class" in result["reason"]


@pytest.mark.parametrize("kind", ["hand", "incendiary"])
def test_an_unverified_kind_needs_the_probe_flag(kind):
    ctl = ring_controller()
    with pytest.raises(N.Unavailable, match="no live receipt yet"):
        ctl.grenade_ring(kind)
    assert ctl.calls == []


def test_an_unknown_kind_is_refused_before_any_native_call():
    ctl = ring_controller()
    with pytest.raises(N.Unavailable, match="unknown grenade kind"):
        ctl.grenade_ring("nuke", allow_unverified=True)
    assert ctl.calls == []


def test_only_the_verified_kind_is_advertised():
    rows = {r["kind"]: r for r in N.ring_kind_options()}
    assert rows["flash"]["available"] is True
    assert all(rows[k]["available"] is False and rows[k]["reason"] for k in ("hand", "incendiary"))
    assert set(N.RING_IMPLEMENTED_KINDS) == {"flash", "hand", "incendiary"}


# ---- an explosive ring keeps its distance -----------------------------------------------------------------------------------

def _placed(ctl):
    """{unit: (x, y, z)} from the position write each spawned unit received."""
    out = {}
    for at, data in ctl.writes:
        for unit in ctl.spawns:
            if at == unit + N.RING_UNIT_POS:
                out[unit] = struct.unpack("<3f", data)
    return out


def _near(ctl, origin):
    return min(math.hypot(x - origin[0], z - origin[2]) for x, _y, z in _placed(ctl).values())


def test_a_hand_ring_never_places_a_grenade_inside_its_own_blast():
    origin = (1000.0, 800.0, -2000.0)
    ctl = ring_controller(unit_vtable=HAND_VT, position=origin)
    result = ctl.grenade_ring("hand", allow_unverified=True, count=4)
    assert result["state"] == "confirmed"
    assert len(_placed(ctl)) == 4
    assert _near(ctl, origin) >= N.RING_EXPLOSIVE_CLEAR_CM
    assert result["inner_cm"] >= N.RING_EXPLOSIVE_CLEAR_CM


def test_an_incendiary_ring_asked_for_a_short_radius_is_raised_and_says_so():
    ctl = ring_controller(unit_vtable=HAND_VT)
    result = ctl.grenade_ring("incendiary", allow_unverified=True, count=2, radius_cm=300.0, inner_cm=100.0)
    assert result["state"] == "confirmed"
    assert result["radius_cm"] == N.RING_EXPLOSIVE_CLEAR_CM
    assert result["inner_cm"] == N.RING_EXPLOSIVE_CLEAR_CM
    assert _near(ctl, (1000.0, 800.0, -2000.0)) >= N.RING_EXPLOSIVE_CLEAR_CM


def test_the_flash_ring_keeps_its_verified_near_floor():
    ctl = ring_controller()
    result = ctl.grenade_ring("flash", count=3, radius_cm=250.0, inner_cm=100.0)
    assert result["state"] == "confirmed"
    assert result["radius_cm"] == 305.0 and result["inner_cm"] == 305.0, "the ring never starts inside 10 ft"
    assert _near(ctl, (1000.0, 800.0, -2000.0)) >= 100.0
