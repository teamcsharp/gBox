"""gbox.pso_ram: the PSO GameCube RAM map, exercised on a synthetic memory image (no emulator)."""
import struct

import pytest

from gbox import pso_ram as R


class Mem:
    """A sparse 24 MiB RAM image with read_memory, like the Dolphin adapter's primitive."""

    def __init__(self):
        self.data = bytearray(R.RAM_END - R.RAM_START)

    def poke(self, address, blob):
        self.data[address - R.RAM_START:address - R.RAM_START + len(blob)] = blob

    def u32(self, address, value):
        self.poke(address, struct.pack(">I", value))

    def u16(self, address, value):
        self.poke(address, struct.pack(">H", value))

    def f32(self, address, value):
        self.poke(address, struct.pack(">f", value))

    def cstr(self, address, text):
        self.poke(address, text.encode() + b"\0")

    def read_memory(self, address, length):
        off = address - R.RAM_START
        if off < 0 or off + length > len(self.data):
            return None
        return bytes(self.data[off:off + length])


CLASS_NAME_PTR = 0x805DE000


def live():
    m = Mem()
    m.poke(R.PHASE, b"\x09")
    m.u32(R.FLOOR, 1)
    m.u32(R.EPISODE_FLOOR, 0)
    m.u32(R.TRAVELLING, 0)
    p1, p2 = 0x80DA62A0, 0x80DA8830
    m.u32(R.PLAYER_SLOTS + 0, p1)
    m.u32(R.PLAYER_SLOTS + 4, p2)
    # +0x00 is a char* to the class name (proven live: 0x80DA62A0 holds 0x80446F20 -> "TObjPlayer").
    # Each actor gets its own name string so a test can invalidate one without invalidating the other.
    m.cstr(CLASS_NAME_PTR, "TObjPlayer")
    m.cstr(CLASS_NAME_PTR + 0x20, "TObjPlayer")
    for ptr, name_ptr, (x, y, z, hp, hp_max, room) in (
            (p1, CLASS_NAME_PTR, (7.0, 0.0, -30.0, 120, 140, 10)),
            (p2, CLASS_NAME_PTR + 0x20, (12.0, 0.5, -32.0, 99, 140, 11))):
        m.u32(ptr + R.OFF_CLASS_POINTER, name_ptr)
        m.f32(ptr + R.OFF_X, x)
        m.f32(ptr + R.OFF_Y, y)
        m.f32(ptr + R.OFF_Z, z)
        m.u16(ptr + R.OFF_HP, hp)
        m.u16(ptr + R.OFF_HP_MAX, hp_max)
        m.u16(ptr + R.OFF_ROOM, room)
        m.u16(ptr + R.OFF_CONTROL_MODE, 2)
        m.u16(ptr + R.OFF_ACTION_STATE, 0x5F)
        m.u32(ptr + R.OFF_HIT_RECORDS, 0)
    m.u32(R.FLOOR_ITEM_COUNTS, 0x805D7000)
    m.u32(R.FLOOR_ITEM_TABLE, 0x805D7100)
    m.u32(0x805D7000 + 1 * 4, 2)                     # floor 1 has two items
    m.u32(0x805D7100 + 1 * 4, 0x805D7200)
    rec = bytearray(R.FLOOR_ITEM_RECORD * 2)
    rec[16:19] = bytes.fromhex("010200")
    struct.pack_into(">I", rec, 28, 0x00F00001)
    rec[R.FLOOR_ITEM_RECORD + 16:R.FLOOR_ITEM_RECORD + 19] = bytes.fromhex("010301")
    struct.pack_into(">I", rec, R.FLOOR_ITEM_RECORD + 28, 0x00F00002)
    m.poke(0x805D7200, bytes(rec))
    for i, a in enumerate(R.COLLISION_ROOTS):
        m.u32(a, 0x805D5000 + i * 0x10)
    return m


def test_addresses_are_in_ram_and_offsets_are_sane():
    for name in dir(R):
        if name.isupper() and isinstance(getattr(R, name), int):
            v = getattr(R, name)
            if v > 0x1000 and name != "RAM_END":
                assert R.RAM_START <= v < R.RAM_END, f"{name} = {v:#x}"
    assert R.GAME_ID == "GPOE8P"
    assert len(R.DOL_SHA256) == 64
    assert R.PLAYER_SLOTS_COUNT == 4 and len(R.COLLISION_ROOTS) == 4
    assert R.TRAVEL_DESTINATION == R.TRAVEL_STATE + 0xC


def test_phase_floor_episode_and_transition():
    r = R.Reader(live())
    assert R.phase(r) == 9
    assert R.floor(r) == 1 and R.floor_name(r) == "Forest1"
    assert R.episode(r) == 1
    assert R.travelling(r) is False
    r.memory.u32(R.TRAVELLING, 1)
    r.memory.u32(R.TRAVEL_DESTINATION, 2)
    assert R.travelling(r) is True and R.travel_destination(r) == 2
    r.memory.u32(R.FLOOR, 14)
    assert R.floor_name(r) == "DarkFalz"


def test_floor_name_is_none_off_the_proven_table():
    r = R.Reader(live())
    r.memory.u32(R.FLOOR, 17)
    assert R.floor_name(r) is None


def test_player_slots_and_state():
    r = R.Reader(live())
    assert R.player_slots(r)[:2] == [0x80DA62A0, 0x80DA8830] and R.player_slots(r)[2:] == [0, 0]
    p1 = R.player(r, 0)
    assert p1["cls"] == "TObjPlayer" and p1["hp"] == 120 and p1["hp_max"] == 140
    assert (p1["x"], p1["y"], p1["z"]) == (7.0, 0.0, -30.0)
    assert p1["room"] == 10 and p1["control_mode"] == 2 and p1["action_state"] == 0x5F
    ps = R.players(r)
    assert set(ps) == {1, 2} and ps[2]["hp"] == 99 and ps[2]["room"] == 11


def test_a_stale_slot_is_not_reported_as_a_player():
    m = live()
    m.cstr(CLASS_NAME_PTR, "TObjDoorKey")     # the class name behind the pointer is a different object
    r = R.Reader(m)
    assert R.player(r, 0) is None
    assert set(R.players(r)) == {2}


def test_player_class_follows_the_pointer_and_rejects_a_bad_one():
    m = live()
    r = R.Reader(m)
    assert R.player_class(r, 0x80DA62A0) == "TObjPlayer"
    m.u32(0x80DA62A0 + R.OFF_CLASS_POINTER, 0x1234)      # not in RAM
    assert R.player_class(r, 0x80DA62A0) is None
    m.u32(0x80DA62A0 + R.OFF_CLASS_POINTER, 0x805DE100)   # in RAM, but empty text
    assert R.player_class(r, 0x80DA62A0) is None


def test_reader_refuses_out_of_window_and_short_reads():
    r = R.Reader(live())
    with pytest.raises(R.RamError):
        r.read(0x1000, 4)
    with pytest.raises(R.RamError):
        r.read(R.RAM_END - 2, 4)
    with pytest.raises(R.RamError):
        r.read(R.PHASE, 0)
    with pytest.raises(TypeError):
        R.Reader(object())
    with pytest.raises(R.RamError):
        R.player(r, 4)


def test_floor_items_reads_the_pointer_arrays():
    r = R.Reader(live())
    items = R.floor_items(r)
    assert [i["id"] for i in items] == [0x00F00001, 0x00F00002]
    assert [i["code"] for i in items] == ["010200", "010301"]
    r.memory.u32(R.FLOOR, 3)                              # a floor with no items
    assert R.floor_items(r) == []


def test_floor_items_rejects_an_absurd_count():
    m = live()
    m.u32(0x805D7000 + 4, 100000)
    with pytest.raises(R.RamError):
        R.floor_items(R.Reader(m))


def test_collision_roots_and_snapshot():
    r = R.Reader(live())
    assert R.collision_roots(r) == (0x805D5000, 0x805D5010, 0x805D5020, 0x805D5030)
    s = R.snapshot(r)
    assert s["floor_name"] == "Forest1" and s["episode"] == 1 and set(s["players"]) == {1, 2}
