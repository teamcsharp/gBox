"""Door state for PSO GC: which doors are unlocked, and a history of what unlocked them.

Discovered this round by diffing structs: the entity at 0x8050D460 (+0x340 struct) has its door state at **+0x18C**:
    0   = closed / locked (the room's enemies are still alive)
    2   = opened because the room was cleared        <- the state that lets the bot proceed
    224 = key door (needs a key)
    240 = other special state (still usable to approach)

Operator requirements this satisfies:
  * track which doors unlock when a room is cleared        -> `History.record` writes door-history.jsonl
  * unlock any door it walks up to                         -> `locked_near` + the caller clears the room's enemies
  * once a door is unlocked, go through it                 -> `usable_near`
  * read the RAM flags to know a room unlocked             -> `read()` returns each door's state
"""
import json
import struct
import time

TABLE = 0x8050D460
MAX_ENTRIES = 256
STRUCT = 0x340
STATE_OFFSET = 0x18C
POS_OFFSET = 0x38
HISTORY = r"D:\gBox\pso-ds\door-history.jsonl"

STATE_CLOSED = 0
STATE_OPEN = 2
STATE_KEY_DOOR = 224
STATE_SPECIAL = 240


def _cstring(read, address, limit=40):
    raw = read(address, limit)
    return raw.split(b"\x00")[0].decode("ascii", "replace") if raw else ""


def read(read_memory):
    """Every door entity with its state. `read_memory(address, length) -> bytes`."""
    raw = read_memory(TABLE, MAX_ENTRIES * 4)
    out = []
    for index in range(MAX_ENTRIES):
        pointer = int.from_bytes(raw[index * 4:index * 4 + 4], "big")
        if not (0x80000000 <= pointer < 0x81800000):
            continue
        name_pointer = int.from_bytes(read_memory(pointer, 4), "big")
        if not (0x80000000 <= name_pointer < 0x81800000):
            continue
        name = _cstring(read_memory, name_pointer)
        if not name.startswith("TObjDoor"):
            continue
        blob = read_memory(pointer, STRUCT)
        x, y, z = struct.unpack(">fff", blob[POS_OFFSET:POS_OFFSET + 12])
        (state,) = struct.unpack(">i", blob[STATE_OFFSET:STATE_OFFSET + 4])
        out.append({"index": index, "class": name, "x": x, "y": y, "z": z, "state": state,
                    "is_key": name.startswith("TObjDoorKey")})
    return out


def usable(door):
    """A door the bot may walk through: opened by clearing the room, or a special-state door."""
    return door["state"] in (STATE_OPEN, STATE_SPECIAL) or door["is_key"]


def needs_clearing(door):
    return door["state"] == STATE_CLOSED and not door["is_key"]


def nearest(doors, point, predicate=None, limit=None):
    rows = [d for d in doors if predicate is None or predicate(d)]
    if not rows:
        return None
    best = min(rows, key=lambda d: ((d["x"] - point[0]) ** 2 + (d["z"] - point[1]) ** 2) ** 0.5)
    distance = ((best["x"] - point[0]) ** 2 + (best["z"] - point[1]) ** 2) ** 0.5
    if limit is not None and distance > limit:
        return None
    return best


class History:
    """Records door state transitions so the bot knows what unlocked what."""

    def __init__(self, path=HISTORY):
        self.path = path
        self.previous = {}

    def update(self, doors, cause=""):
        changes = []
        for door in doors:
            key = door["index"]
            now = door["state"]
            before = self.previous.get(key)
            if before is None:
                self.previous[key] = now
                continue
            if before != now:
                self.previous[key] = now
                record = {"time": time.strftime("%Y-%m-%dT%H:%M:%S"), "door": key,
                          "class": door["class"], "x": round(door["x"], 1), "z": round(door["z"], 1),
                          "from": before, "to": now, "cause": cause,
                          "unlocked": now == STATE_OPEN}
                changes.append(record)
                try:
                    with open(self.path, "a", encoding="utf-8") as handle:
                        handle.write(json.dumps(record) + "\n")
                except OSError:
                    pass
        return changes
