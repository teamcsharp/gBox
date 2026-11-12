"""Verify the bot's entity scanners against a synthetic memory image.

Every scanner in the play loop reads raw structs out of the emulator: a name pointer at the actor, the position at `+0x38`, HP at `+0x32C`, the door state at
`+0x18C`, and the player's own pointer at `0x8050EA10`. If any offset or byte order is wrong the loop will not crash - it will simply see no enemies, no
switches and no exits, and wander forever. That is exactly the failure that would look like "the bot is confused" with a running game.

So the scanners are exercised against a hand-built memory image: three actors (an enemy with HP, a door-switch in state 224, a portal), plus the player
himself, at known coordinates. The test asserts the parsed distances, classes, HP and states, so a wrong offset shows up here instead of in a live run.

`session.read_memory` is replaced by a fake that serves the image, so nothing here needs an emulator.
"""
import math
import struct
import sys

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import play_pad                                                    # noqa: E402

BASE = 0x80500000


class FakeMemory:
    """A sparse little-endian-agnostic memory image: address -> bytes."""

    def __init__(self):
        self.blocks = {}

    def put(self, address, data):
        self.blocks[address] = bytes(data)

    def read(self, address, length):
        """Return the readable part of a block and zero-fill the rest, as a real memory image would."""
        for start, data in self.blocks.items():
            end = start + len(data)
            if start <= address < end:
                offset = address - start
                chunk = data[offset:offset + length]
                return chunk + b"\x00" * (length - len(chunk))
        return b"\x00" * length


def actor_table(memory, rows):
    """rows: list of (name, x, y, z, hp, state) -> writes the entity table and returns the addresses."""
    table = 0x8050D460
    pointer_bytes = bytearray(256 * 4)
    for index, (name, x, y, z, hp, state) in enumerate(rows):
        actor = BASE + 0x1000 + index * 0x400
        name_pointer = BASE + 0x8000 + index * 0x40
        memory.put(name_pointer, name.encode("ascii").ljust(64, b"\x00"))   # a name lives in a larger allocation
        struct_body = bytearray(0x340)
        struct.pack_into(">fff", struct_body, 0x38, x, y, z)
        struct.pack_into(">H", struct_body, 0x32C, hp)
        struct.pack_into(">i", struct_body, 0x18C, state)
        struct.pack_into(">I", struct_body, 0x00, name_pointer)   # the actor's first field is its class-name pointer
        memory.put(actor, struct_body)
        pointer_bytes[index * 4:index * 4 + 4] = struct.pack(">I", actor)
    memory.put(table, pointer_bytes)


def install(memory, player_position):
    """Point the module's own reads at the fake image, with the player at a known place."""
    player_actor = BASE + 0x0000
    body = bytearray(0x340)
    struct.pack_into(">fff", body, 0x38, *player_position)
    struct.pack_into(">H", body, 0x32C, 40)
    memory.put(player_actor, body)
    memory.put(0x8050EA10, struct.pack(">I", player_actor))

    def read_memory(address, length=4):                              # noqa: ANN001
        return memory.read(address, length)

    play_pad.S.read_memory = read_memory


if __name__ == "__main__":
    memory = FakeMemory()
    player_at = (0.0, 10.0, 0.0)
    actor_table(memory, [
        ("TObjPlayer", 0.0, 10.0, 0.0, 40, 0),
        ("TObjEneSandRappy", 30.0, 10.0, 40.0, 120, 0),
        ("TObjDoor", 0.0, 12.0, 12.0, 0, 224),
        ("TObjVrPortal", 0.0, 10.0, 80.0, 0, 0),
    ])
    install(memory, player_at)

    foes, switches = play_pad.entities()
    exits = play_pad.exits()

    failures = []

    def check(label, condition, detail=""):
        print(("PASS " if condition else "FAIL ") + label + (" - " + detail if detail else ""))
        if not condition:
            failures.append(label)

    check("one enemy parsed", len(foes) == 1, f"got {len(foes)}")
    if foes:
        enemy = foes[0]
        check("enemy class", enemy["class"] == "TObjEneSandRappy", enemy["class"])
        check("enemy hp", enemy["hp"] == 120, str(enemy["hp"]))
        check("enemy distance from (0,0) is 50",
              abs(enemy["distance"] - 50.0) < 0.01, f"{enemy['distance']:.2f}")

    check("one switch parsed", len(switches) == 1, f"got {len(switches)}")
    if switches:
        door = switches[0]
        check("switch class", door["class"] == "TObjDoor", door["class"])
        check("switch state 224", door["state"] == 224, str(door["state"]))
        check("switch distance 12", abs(door["distance"] - 12.0) < 0.01, f"{door['distance']:.2f}")

    check("one exit parsed", len(exits) == 1, f"got {len(exits)}")
    if exits:
        check("exit class", exits[0]["class"] == "TObjVrPortal", exits[0]["class"])
        check("exit distance 80", abs(exits[0]["distance"] - 80.0) < 0.01, f"{exits[0]['distance']:.2f}")

    print()
    if failures:
        print(f"{len(failures)} check(s) failed: {failures}")
        raise SystemExit(1)
    print("all scanner checks passed")
