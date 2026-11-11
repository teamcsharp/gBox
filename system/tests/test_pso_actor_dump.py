"""The live-actor dump: find a pad's or door's handler field without guessing (A7's remaining discriminator)."""
import struct

from gbox import pso_actor_dump as D


class FakeReader:
    """A tiny RAM: a bytes buffer at 0x80000000 (inside the real RAM window), with u32/cstring over it."""

    BASE = 0x80000000

    def __init__(self, memory):
        self.memory = bytes(memory)

    def _at(self, address, size):
        from gbox.pso_ram import RamError
        if not self.BASE <= address and address + size <= self.BASE + len(self.memory):
            raise RamError(f"{address:#x} is not mapped")
        if address + size > self.BASE + len(self.memory):
            raise RamError(f"{address:#x} is past the end of mapped memory")
        return self.memory[address - self.BASE:address - self.BASE + size]

    def u32(self, address):
        return struct.unpack(">I", self._at(address, 4))[0]

    def cstring(self, address, limit=32):
        raw = self.memory[address - self.BASE:address - self.BASE + limit]
        return raw.split(b"\x00")[0].decode("ascii", "replace")


def _actor(extra=(), **fields):
    memory = bytearray(0x400)
    for offset, value in fields.items():
        memory[int(offset, 16):int(offset, 16) + 4] = struct.pack(">I", value)
    for address, raw in extra:
        start = address - FakeReader.BASE
        memory[start:start + len(raw)] = raw
    return bytes(memory)


def test_a_dump_labels_class_names_code_pointers_and_small_values():
    memory = _actor(extra=[(0x80000100, b"TObjCityAreaWarp\x00"),
                           (0x80000200, struct.pack(">I", 0))],
                    **{"00": 0x80000100,          # a pointer to the class-name text
                       "28": 10,                  # room
                       "38": 0x3F800000,          # x as a float bit pattern (not a pointer)
                       "40": 0x80000200})         # a pointer into RAM (not code)
    dump = D.actor_fields(FakeReader(memory), FakeReader.BASE, size=0x48)
    by_off = {f["offset"]: f for f in dump["fields"]}
    assert by_off[0x00]["kind"] == "class-name" and by_off[0x00]["text"] == "TObjCityAreaWarp"
    assert by_off[0x28]["kind"] == "small" and by_off[0x28]["name"] == "room"
    assert by_off[0x38]["kind"] == "raw" and by_off[0x38]["name"] == "x"
    assert by_off[0x40]["kind"] == "ram"


def test_handlers_filters_to_code_pointers():
    # a code pointer must be 4-aligned inside the executable window; 0x20001000 is RAM, not code
    memory = bytearray(0x400)
    memory[0x00:0x04] = struct.pack(">I", 0x80000100)
    memory[0x04:0x08] = struct.pack(">I", 0x80123400)
    memory[0x08:0x0C] = struct.pack(">I", 0x80123402)      # unaligned: not a function pointer
    memory[0x0C:0x10] = struct.pack(">I", 0x80001000)
    memory[0x100:0x110] = b"TObjCityAreaWarp"
    found = D.handlers(FakeReader(memory), FakeReader.BASE, size=0x10)
    assert [f["offset"] for f in found] == [0x04]


def test_a_dump_stops_at_unmapped_memory_instead_of_raising():
    memory = _actor(extra=[(0x80000100, b"TObjPlayer\x00")], **{"00": 0x80000100, "28": 3})
    reader = FakeReader(memory[:0x2C])              # only up to offset 0x2C
    dump = D.actor_fields(reader, FakeReader.BASE, size=0x40)
    assert [f["offset"] for f in dump["fields"]] == [0x00, 0x04, 0x08, 0x0C, 0x10, 0x14, 0x18, 0x1C, 0x20, 0x24, 0x28]


def test_actor_dump_picks_the_class_from_the_entity_list():
    memory = _actor(extra=[(0x80000100, b"TObjCityAreaWarp\x00")], **{"00": 0x80000100})
    items = [{"index": 3, "pointer": FakeReader.BASE, "cls": "TObjCityAreaWarp", "room": 10,
              "x": 1.0, "y": 2.0, "z": 3.0}]
    dump = D.actor_dump(FakeReader(memory), items, cls="TObjCityAreaWarp", size=0x10)
    assert dump["cls"] == "TObjCityAreaWarp" and dump["room"] == 10 and dump["pos"] == (1.0, 2.0, 3.0)
    assert D.actor_dump(FakeReader(memory), items, cls="TObjCityDoor_") is None
