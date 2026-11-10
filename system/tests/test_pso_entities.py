"""gbox.pso_entities: the live entity list, on a synthetic RAM image shaped like the proven layout."""
import pytest

from gbox import pso_entities as E
from gbox import pso_ram as R


class Mem:
    def __init__(self):
        self.data = bytearray(R.RAM_END - R.RAM_START)

    def poke(self, address, blob):
        off = address - R.RAM_START
        self.data[off:off + len(blob)] = blob

    def u32(self, address, value):
        import struct
        self.poke(address, struct.pack(">I", value))

    def u16(self, address, value):
        import struct
        self.poke(address, struct.pack(">H", value))

    def f32(self, address, value):
        import struct
        self.poke(address, struct.pack(">f", value))

    def read_memory(self, address, length):
        off = address - R.RAM_START
        if off < 0 or off + length > len(self.data):
            return None
        return bytes(self.data[off:off + length])


TABLE = R.ENTITY_TABLE
NAMES = 0x805D9000
OBJECTS = 0x805DA000


def game(items):
    """items: [(class name, room, x, z)] laid out as the live build does."""
    m = Mem()
    name_at, obj_at = NAMES, OBJECTS
    for i, (cls, room, x, z) in enumerate(items):
        m.poke(name_at, cls.encode() + b"\0")
        obj = obj_at + i * 0x100
        m.u32(obj + 0x00, name_at)               # +0x00 is a char* to the class name
        m.u16(obj + 0x28, room)
        m.f32(obj + 0x38, x)
        m.f32(obj + 0x3C, 0.0)
        m.f32(obj + 0x40, z)
        m.u32(TABLE + i * 4, obj)
        name_at += 0x40
    return m


TOWN = [("TObjPlayer", 41, 52.7, -2008.1), ("TObjNpcSecretaryBase", 41, 47.0, -2000.0),
        ("TObjCityDoor_Guild", 10, 185.0, 173.0), ("TObjCityDoor_Warp", 10, 254.0, 25.0)]


def test_entities_walk_the_table_in_order():
    r = R.Reader(game(TOWN))
    items = E.entities(r)
    assert [e["cls"] for e in items] == [t[0] for t in TOWN]
    assert items[0]["room"] == 41 and items[0]["x"] == pytest.approx(52.7)
    assert items[2]["x"] == pytest.approx(185.0) and items[2]["z"] == pytest.approx(173.0)


def test_entities_stop_at_the_first_word_that_is_not_an_actor():
    m = game(TOWN)
    m.u32(TABLE + 4 * 4, 0x805DA900)             # a pointer to an object whose +0x00 is not a name pointer
    r = R.Reader(m)
    assert len(E.entities(r)) == 4               # the bogus entry ends the walk, it is not skipped


def test_an_empty_table_is_not_an_error():
    m = Mem()
    m.u32(TABLE, 0)                              # first word is not an actor
    assert E.entities(R.Reader(m)) == []
    m.u32(TABLE, 0x1234)                         # not even a RAM pointer
    assert E.entities(R.Reader(m)) == []


def test_by_class_nearest_and_player():
    items = E.entities(R.Reader(game(TOWN)))
    assert [e["cls"] for e in E.by_class(items, "TObjCityDoor_")] == ["TObjCityDoor_Guild", "TObjCityDoor_Warp"]
    assert E.nearest(items, 250.0, 30.0)["cls"] == "TObjCityDoor_Warp"
    assert E.nearest(items, 250.0, 30.0, "TObjNpc")["cls"] == "TObjNpcSecretaryBase"
    assert E.player(items)["room"] == 41
    assert E.player(E.by_class(items, "TObjCityDoor_")) is None
