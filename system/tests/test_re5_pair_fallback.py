"""RE5's pre-class pair fallback (checkpoint 0.1).

An RE5 emulator that already ran the old flash holds the old spawn/explode bytes at `main+0x118E820` / `+0x118E9D0`.
Those bytes are executed code: `install()` refuses to overwrite them, and must. So the controller reads the pair
*before* it installs anything: the old pair keeps the flash on the old call shape (its installed image expects it)
and only the next emulator can take the class pair; a zero cave gets the class pair; any other bytes refuse.

No live game: the fake emulator implements the real `install()` contract (identical bytes or zero padding only).
"""
import struct
import threading

import pytest

from gbox.mercs.native.re5_ebffdb22 import classes as C
from gbox.mercs.titles import re5_switch_native as N

R = N.R
SPAWN, EXPLODE = 0x118E820, 0x118E9D0
FLASH_VT = 0x1C5EF58
PLAYER_VT = 0x1C290C8


def pair_controller(holds="class", position=(1000.0, 800.0, -2000.0)):
    """A fake RE5 emulator whose pair addresses hold `holds`: 'old', 'class' (zero caves), 'mixed' or 'other'."""
    ctl = N.Controller.__new__(N.Controller)
    ctl.base = 0x100000000
    ctl.player, ctl.sp = 0x200000000, 0x210000000
    ctl.generation = 0x100000002
    ctl.heap = 0x220000000
    ctl.lock = threading.RLock()
    ctl.failed = ctl.recoverable = False
    ctl.mem, ctl.writes, ctl.calls, ctl.installs, ctl.spawns = {}, [], [], [], []
    ctl.pid, ctl.identity = 4242, (4242, 7)
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

    def install(at, data):
        """The base class's contract: identical bytes are reusable, zero padding is writable, anything else refuses."""
        before = read(at, len(data))
        if before == data:
            return
        if any(before):
            raise N.Unavailable("native code padding is occupied")
        ctl.installs.append((at, bytes(data)))
        put(at, data)

    ctl.rd, ctl.write, ctl.put, ctl.install = read, write, put, install
    ctl.q = lambda a: struct.unpack("<Q", read(a, 8))[0]
    ctl.w = lambda a: struct.unpack("<I", read(a, 4))[0]
    ctl.check = ctl.check_build = lambda: None
    ctl.validate_heap = lambda: None
    ctl.detach_completed = lambda: None
    ctl.projectile = lambda unit, born: None
    ctl.ready = lambda: (ctl.player, ctl.generation)
    ctl.wait = lambda predicate, timeout=1.0: predicate()
    ctl.stopped = lambda fn: fn()

    entries = N.table_bytes(ctl.base, ctl.base + PLAYER_VT)
    put(ctl.player, struct.pack("<Q", ctl.base + PLAYER_VT))
    put(ctl.base + PLAYER_VT, entries)
    put(ctl.base + R.S_PLAYER, struct.pack("<Q", ctl.sp))
    put(ctl.player + R.P_POS, struct.pack("<3f", *position))
    put(ctl.heap + 0x6A8, struct.pack("<I", 0))
    if holds == "old":
        put(ctl.base + SPAWN, C.IMAGES["spawn"])
        put(ctl.base + EXPLODE, C.IMAGES["explode"])
    elif holds == "mixed":                       # a half-finished install: never guessed between the two pairs
        put(ctl.base + SPAWN, C.IMAGES["spawn"])
    elif holds == "other":
        put(ctl.base + SPAWN, b"\x11" * len(C.IMAGES["spawn"]))
        put(ctl.base + EXPLODE, b"\x22" * len(C.IMAGES["explode"]))

    def call(off, *args, timeout=1.0):
        ctl.calls.append((off, args))
        if off == SPAWN:
            n = len(ctl.spawns)
            unit, born = 0x230000000 + n * 0x10000, 5000 + n
            put(unit, struct.pack("<Q", ctl.base + FLASH_VT))
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


def test_the_old_pair_keeps_the_flash_on_the_old_call_shape_and_never_overwrites_it():
    ctl = pair_controller("old")
    result = ctl.flash()
    assert result["state"] == "confirmed" and result["effect"] == "native_flash_explosion"
    assert ctl.pair_profile == "pre_class"
    spawn = next(args for off, args in ctl.calls if off == SPAWN)
    assert spawn == (ctl.player, ctl.generation)                  # DTI and vtable compiled in: two arguments
    explode = next(args for off, args in ctl.calls if off == EXPLODE)
    assert explode == (ctl.spawns[0], 5000, ctl.player, ctl.generation)   # the old four-argument shape
    assert all(at not in (ctl.base + SPAWN, ctl.base + EXPLODE) for at, _data in ctl.installs)


def test_the_old_pair_refuses_hand_and_incendiary_until_the_next_emulator():
    ctl = pair_controller("old")
    rows = {row["kind"]: row for row in ctl.grenade_kinds()}
    assert rows["flash"]["available"] is True
    for kind in ("hand", "incendiary"):
        assert rows[kind]["available"] is False and rows[kind]["reason"] == N.PRE_CLASS_REASON
    with pytest.raises(N.Unavailable, match="runs the pre-class pair"):
        ctl.grenade_ring("hand", allow_unverified=True)
    with pytest.raises(N.Unavailable, match="runs the pre-class pair"):
        ctl.grenade_scatter("hand")
    assert ctl.calls == []                                        # refused before any native call


def test_a_zero_cave_installs_the_class_pair_and_runs_the_class_shape():
    ctl = pair_controller("class")
    result = ctl.flash()
    assert result["state"] == "confirmed" and ctl.pair_profile == "class"
    assert ctl.rd(ctl.base + SPAWN, len(C.SPAWN_CLASS_BYTES)) == C.SPAWN_CLASS_BYTES
    assert ctl.rd(ctl.base + EXPLODE, len(C.EXPLODE_CLASS_BYTES)) == C.EXPLODE_CLASS_BYTES
    installed = {at for at, _data in ctl.installs}
    assert {ctl.base + SPAWN, ctl.base + EXPLODE} <= installed
    spawn = next(args for off, args in ctl.calls if off == SPAWN)
    assert spawn == (ctl.player, ctl.generation, ctl.base + C.CLASSES["flash"].dti)
    explode = next(args for off, args in ctl.calls if off == EXPLODE)
    assert explode[4:7] == (ctl.base + FLASH_VT, 0x108, ctl.base + C.FLASH_UPDATE_OFF)


def test_a_pair_the_class_pair_already_wrote_is_reused_without_installing():
    ctl = pair_controller("installed")
    ctl.put(ctl.base + SPAWN, C.SPAWN_CLASS_BYTES)
    ctl.put(ctl.base + EXPLODE, C.EXPLODE_CLASS_BYTES)
    assert ctl.flash()["state"] == "confirmed"
    assert ctl.pair_profile == "class"
    assert all(at not in (ctl.base + SPAWN, ctl.base + EXPLODE) for at, _data in ctl.installs)


def test_any_other_bytes_refuse_everything_and_install_nothing():
    ctl = pair_controller("other")
    rows = ctl.grenade_kinds()
    assert all(row["available"] is False and "neither the pre-class pair" in row["reason"] for row in rows)
    with pytest.raises(N.Unavailable, match="neither the pre-class pair"):
        ctl.flash()
    with pytest.raises(N.Unavailable, match="neither the pre-class pair"):
        ctl.grenade_scatter("random")
    assert ctl.calls == [] and ctl.installs == []


def test_a_half_installed_pair_is_not_guessed_between_the_two():
    ctl = pair_controller("mixed")
    with pytest.raises(N.Unavailable, match="neither the pre-class pair"):
        ctl.flash()
    assert ctl.calls == [] and ctl.installs == []


def test_prior_class_image_with_clobbered_arguments_is_refused_without_overwrite():
    ctl=pair_controller('class')
    old=list(struct.unpack('<62I',C.IMAGES['explode']))
    old[4],old[5],old[47],old[55]=C.NOP,C.NOP,C.MOV_W3_W5,C.BLR_X6
    ctl.put(ctl.base+SPAWN,C.SPAWN_CLASS_BYTES)
    ctl.put(ctl.base+EXPLODE,struct.pack('<62I',*old))
    with pytest.raises(N.Unavailable,match='neither the pre-class pair'):
        ctl.flash()
    assert not ctl.calls and not ctl.installs
