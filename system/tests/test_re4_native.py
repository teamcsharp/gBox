"""The RE4 native harness controller (E4/E5): the writes, the trigger, the mailbox and its refusal cases.

A fake guest builds the image's real layout - a player unit of class 0xB0C0A0 whose vtable slot +0x20 holds
main+0x2B6420, a zero cave, and a mailbox - and a fake dispatcher consumes one published request. No game.
"""
import struct
import types

import pytest

from gbox.mercs.titles import re4_switch as R
from gbox.mercs.titles import re4_switch_native as N
from gbox.mercs.titles import re6_switch_native as NB
from gbox.mercs.native.re4_82c2a04a import code as CODE

BASE = 0x100000000
PLAYER = 0x200000000
MAILBOX = 0x900000000
PLAYER_VT = BASE + 0xB0C0A0
CAVE = BASE + CODE.CAVE_AT
CLONE = BASE + CODE.CLONE_AT


def put(mem, at, data):
    mem.update({at + i: b for i, b in enumerate(data)})


def get(mem, at, n):
    return bytes(mem.get(at + i, 0) for i in range(n))


def fake_controller(monkeypatch, *, mailbox=MAILBOX, complete=True):
    ctl = N.Controller.__new__(N.Controller)
    ctl.base, ctl.pid, ctl.identity = BASE, 4242, (4242, 7)
    ctl.mailbox, ctl.player, ctl.original, ctl.player_id = mailbox, None, None, None
    ctl.request_generation, ctl.failed = 0, False
    ctl.player_class = None
    mem, writes, installed = {}, [], []
    ctl.mem, ctl.writes, ctl.installed = mem, writes, installed
    ctl.check = ctl.check_build = lambda: None
    ctl.stopped = lambda fn: fn()

    def read(at, n):
        return get(mem, at, n)

    def ad_write(at, data):
        writes.append((at, bytes(data)))
        put(mem, at, data)

    ctl.rd = read
    ctl.q = lambda at: struct.unpack("<Q", read(at, 8))[0]
    ctl.w = lambda at: struct.unpack("<I", read(at, 4))[0]
    ctl.ad = types.SimpleNamespace(address_mode="direct", paused=False,
                                   write_memory=ad_write, read_memory=read, _guest=lambda: (4242, 1))

    # the unit itself
    unit = bytearray(0x400)
    struct.pack_into("<Q", unit, 0, PLAYER_VT)
    struct.pack_into("<Q", unit, 0x110, 7)                       # id
    struct.pack_into("<3f", unit, 0xA4, 1.0, 2.0, 3.0)           # position
    struct.pack_into("<3f", unit, 0xB4, 0.0, 0.0, 0.0)           # rotation
    struct.pack_into("<H", unit, 0x3C2, 100)                     # hp
    struct.pack_into("<H", unit, 0x3C4, 100)                     # hp max
    unit[0x3CE] = 0                                              # type
    put(mem, PLAYER, unit)
    put(mem, BASE + R.S_PLAYER, struct.pack("<Q", PLAYER))
    vt = bytearray(32 * 8)
    for slot in range(32):
        struct.pack_into("<Q", vt, slot * 8, BASE + 0x1234)
    struct.pack_into("<Q", vt, CODE.SLOT_TRANSFORM, BASE + CODE.ORIGINAL_TRANSFORM)
    put(mem, BASE + 0xB0C0A0, vt)                                # the class vtable the player carries (Leon B)

    def fake_install(self, at, data):
        before = get(mem, at, len(data))
        if before == data:
            return
        if any(before):
            raise N.Unavailable("native code padding is occupied")
        installed.append((at, bytes(data)))
        put(mem, at, data)
    monkeypatch.setattr(NB.Controller, "install", fake_install, raising=False)

    def wait(predicate, timeout=1.0):
        state = ctl.w(MAILBOX + CODE.MAILBOX["state"]) if ctl.mailbox else 0
        if not complete:
            raise N.Uncertain("native completion uncertain; request will not be replayed")
        if state == CODE.STATE["requested"]:
            target = ctl.q(MAILBOX + CODE.MAILBOX["target"])
            args = struct.unpack("<7Q", get(mem, MAILBOX + CODE.MAILBOX["args"], 56))
            result = target + sum(args)
            put(mem, MAILBOX + CODE.MAILBOX["result"], struct.pack("<Q", result))
            put(mem, MAILBOX + CODE.MAILBOX["state"], struct.pack("<I", CODE.STATE["done"]))
        return predicate()
    ctl.wait = wait
    return ctl


# ---- E4: the write rule -----------------------------------------------------------------------------------------------

def test_a_write_into_code_or_rodata_is_refused(monkeypatch):
    ctl = fake_controller(monkeypatch)
    for at in (BASE + 0x100, BASE + 0x2B6420, BASE + 0x655880, BASE + 0x900000):
        with pytest.raises(N.Unavailable, match="code or read-only"):
            ctl.write(at, b"\x00\x00\x00\x00")
    ctl.write(MAILBOX + CODE.MAILBOX["state"], b"\x00\x00\x00\x00")     # .bss/heap is allowed
    assert ctl.writes and ctl.writes[-1][0] == MAILBOX


def test_install_outside_the_cave_is_refused(monkeypatch):
    ctl = fake_controller(monkeypatch)
    with pytest.raises(N.Unavailable, match="outside the vetted cave"):
        ctl.install(BASE + 0x100, b"\x00" * 8)
    with pytest.raises(N.Unavailable, match="outside the vetted cave"):
        ctl.install(CAVE + CODE.CAVE_SIZE, b"\x00" * 8)
    ctl.install(CAVE, b"\x01" * 8)                                       # inside the cave: the base class decides
    assert ctl.installed and ctl.installed[0][0] == CAVE


# ---- E5: the trigger and the mailbox ---------------------------------------------------------------------------------

def test_attach_installs_dispatch_and_clone_and_writes_only_the_vtable_pointer(monkeypatch):
    ctl = fake_controller(monkeypatch)
    ctl.attach()
    assert [at for at, _data in ctl.installed] == [CAVE, CLONE]
    assert ctl.installed[0][1] == CODE.IMAGES["dispatch"]
    clone = ctl.installed[1][1]
    assert len(clone) == CODE.CLONE_SIZE
    assert struct.unpack_from("<Q", clone, CODE.SLOT_TRANSFORM)[0] == CAVE
    assert struct.unpack_from("<Q", clone, CODE.CLONE_MAILBOX_OFF)[0] == MAILBOX
    assert len(ctl.writes) == 1 and ctl.writes[0] == (PLAYER, struct.pack("<Q", CLONE))
    assert ctl.q(PLAYER) == CLONE and ctl.attached()

    ctl.detach()
    assert ctl.q(PLAYER) == PLAYER_VT and not ctl.attached()
    assert ctl.writes[-1] == (PLAYER, struct.pack("<Q", PLAYER_VT))


def test_attaching_again_is_a_no_op(monkeypatch):
    ctl = fake_controller(monkeypatch)
    ctl.attach()
    ctl.attach()
    assert len(ctl.installed) == 2 and len(ctl.writes) == 1


def test_attach_refuses_without_a_mailbox(monkeypatch):
    ctl = fake_controller(monkeypatch, mailbox=None)
    with pytest.raises(N.Unavailable, match="E3"):
        ctl.attach()
    assert ctl.installed == [] and ctl.writes == []


def test_attach_refuses_a_player_whose_transform_slot_is_not_pinned(monkeypatch):
    ctl = fake_controller(monkeypatch)
    put(ctl.mem, BASE + 0xB0C0A0 + CODE.SLOT_TRANSFORM, struct.pack("<Q", BASE + 0x999))
    with pytest.raises(N.Unavailable, match="transform slot"):
        ctl.attach()
    assert ctl.writes == []


def test_attach_refuses_a_cave_that_is_not_empty(monkeypatch):
    ctl = fake_controller(monkeypatch)
    put(ctl.mem, CAVE, b"\x01")
    with pytest.raises(N.Unavailable, match="padding is occupied"):
        ctl.attach()
    assert ctl.writes == []


def test_a_call_publishes_once_and_reads_the_result(monkeypatch):
    ctl = fake_controller(monkeypatch)
    ctl.attach()
    result = ctl.call(0x1000, 1, 2, 3)
    assert result == BASE + 0x1000 + 6
    states = [w for w in ctl.writes if w[0] == MAILBOX + CODE.MAILBOX["state"]]
    assert len(states) == 1 and struct.unpack("<I", states[0][1])[0] == CODE.STATE["requested"]
    assert ctl.w(MAILBOX + CODE.MAILBOX["state"]) == CODE.STATE["done"]
    assert struct.unpack("<7Q", get(ctl.mem, MAILBOX + CODE.MAILBOX["args"], 56)) == (1, 2, 3, 0, 0, 0, 0)


def test_a_timeout_is_uncertain_and_the_request_is_never_replayed(monkeypatch):
    ctl = fake_controller(monkeypatch, complete=False)
    ctl.attach()
    with pytest.raises(N.Uncertain):
        ctl.call(0x1000, 1)
    published = [w for w in ctl.writes if w[0] == MAILBOX + CODE.MAILBOX["state"]]
    assert len(published) == 1
    with pytest.raises(N.Unavailable, match="incomplete"):
        ctl.call(0x1000, 1)
    assert len([w for w in ctl.writes if w[0] == MAILBOX + CODE.MAILBOX["state"]]) == 1


def test_a_changed_generation_is_not_trusted(monkeypatch):
    ctl = fake_controller(monkeypatch)
    ctl.attach()

    def wait_tampered(predicate, timeout=1.0):
        put(ctl.mem, MAILBOX + CODE.MAILBOX["generation"], struct.pack("<Q", 999))
        put(ctl.mem, MAILBOX + CODE.MAILBOX["state"], struct.pack("<I", CODE.STATE["done"]))
        return predicate()
    ctl.wait = wait_tampered
    with pytest.raises(N.Uncertain, match="generation"):
        ctl.call(0x1000)


def test_call_requires_attachment(monkeypatch):
    ctl = fake_controller(monkeypatch)
    with pytest.raises(N.Unavailable, match="not attached"):
        ctl.call(0x1000)


def test_ready_refuses_a_player_of_a_non_unit_class(monkeypatch):
    ctl = fake_controller(monkeypatch)
    put(ctl.mem, PLAYER, struct.pack("<Q", BASE + 0x1000))
    with pytest.raises(N.Unavailable, match="no player unit"):
        ctl.ready()
