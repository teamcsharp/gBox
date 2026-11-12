"""Press any door or switch in reach, whatever its state - the operator's rule, applied directly.

The operator's guidance, verbatim: "The bot needs to press the button any time this opportunity comes up, anytime they see an indicator for the switch, they
need to press it."

The live dump shows why the existing filter missed them. Standing next to a door:

```
23.4  TObjDoor  state=880  hp=18951
```

`880` was rejected by a filter that only accepted 0, 2, 224 and 240 - but a door does not have to be in one of those states to be worth pressing. `880` is
most likely mid-animation, and the glowing indicator the operator screenshotted is exactly the sort of thing that accompanies an interactive door.

So the rule becomes the operator's own:

  * **any door or switch entity within 10 units is pressed**, regardless of state;
  * the state is still **logged**, so the record shows what changed when a press lands;
  * the state filter stays only for choosing a *distant* destination to walk to, where pressing is not immediate anyway.

This runs before everything else in the cycle, so the bot takes the opportunity the moment it is in reach instead of walking past it toward something else.
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\.tmp\play_rooms.py")
text = path.read_text(encoding="utf-8")

# 1. accept any door state when choosing a destination (hp still marks a real door)
old_filter = """        if "Door" in name and state not in (0, 2, 224, 240):
            continue                                   # not a door state"""
new_filter = """        if "Door" in name and state not in (0, 2, 224, 240, 880, 176, 48, 1):
            continue                                   # a state no door has ever shown in this session"""
if text.count(old_filter) == 1:
    text = text.replace(old_filter, new_filter, 1)
    print("door states widened to those actually observed")

# 2. a new step: press anything in reach, whatever its state
anchor = "def press_switches():"
if "def press_in_reach(" not in text:
    block = '''def press_in_reach():
    """Press any door or switch within 10 units, whatever its state. Returns True when it pressed."""
    me = player()
    if me is None:
        return False
    raw = S.read_memory(TABLE, MAX_ENTRIES * 4)
    nearest = None
    for index in range(MAX_ENTRIES):
        pointer = int.from_bytes(raw[index * 4:index * 4 + 4], "big")
        if not (0x80000000 <= pointer < 0x81800000):
            continue
        try:
            name_pointer = int.from_bytes(S.read_memory(pointer, 4), "big")
            name = S.read_memory(name_pointer, 32).split(b"\\x00")[0].decode("ascii", "replace")
            if not any(word in name for word in ("Door", "Swtch", "Switch", "Capsule", "Key")):
                continue
            blob = S.read_memory(pointer, 0x340)
            x, y, z = struct.unpack(">fff", blob[POS:POS + 12])
            state = struct.unpack(">i", blob[0x18C:0x18C + 4])[0]
            hp = struct.unpack(">H", blob[HP:HP + 2])[0]
        except Exception:                                        # noqa: BLE001
            continue
        distance = math.dist((me[0], me[2]), (x, z))
        if distance <= 10.0 and (nearest is None or distance < nearest[0]):
            nearest = (distance, name, state, hp, x, z)
    if nearest is None:
        return False
    distance, name, state, hp, x, z = nearest
    log(f"  in reach: {name} state {state} hp {hp} at {distance:.1f} units - pressing")
    for attempt in range(4):
        pso_input.hold("a", 0.3)
        time.sleep(0.5)
        again = None
        raw2 = S.read_memory(TABLE, MAX_ENTRIES * 4)
        for index in range(MAX_ENTRIES):
            pointer = int.from_bytes(raw2[index * 4:index * 4 + 4], "big")
            if not (0x80000000 <= pointer < 0x81800000):
                continue
            try:
                name_pointer = int.from_bytes(S.read_memory(pointer, 4), "big")
                other = S.read_memory(name_pointer, 32).split(b"\\x00")[0].decode("ascii", "replace")
                if other != name:
                    continue
                block2 = S.read_memory(pointer, 0x340)
                ox, _oy, oz = struct.unpack(">fff", block2[POS:POS + 12])
                if math.dist((ox, oz), (x, z)) < 8:
                    again = struct.unpack(">i", block2[0x18C:0x18C + 4])[0]
                    break
            except Exception:                                    # noqa: BLE001
                continue
        log(f"    press x{attempt + 1}: state {again}")
        if again != state:
            log("    state changed - it did something")
            return True
    return True


def press_switches():'''
    if text.count(anchor) != 1:
        raise SystemExit("press_switches anchor not found")
    text = text.replace(anchor, block, 1)
    print("press_in_reach added")

# 3. run it first in the cycle
old_cycle = """            if press_switches():
                continue"""
new_cycle = """            if press_in_reach():
                continue
            if press_switches():
                continue"""
if text.count(old_cycle) == 1:
    text = text.replace(old_cycle, new_cycle, 1)
    print("press_in_reach runs first in every cycle")
else:
    print("cycle anchor count", text.count(old_cycle))

path.write_text(text, encoding="utf-8")
print("done")
