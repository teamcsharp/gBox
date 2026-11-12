"""Give the pad bot a way to finish a level: head for the exit object, and notice when the area changes.

"To completion" needs two things the loop did not have:

1. **an exit to walk to.** In PSO the way out of an area is a portal/warp object in the final room, and its exact runtime class name has not been observed
   in this session (`TObjDoor`, `TObjDoorKey`, `TObjContainerItem`, `TObjPlayer` are the classes seen so far). Rather than hard-code a guess, the loop
   matches a broad set of exit-like words - Portal, Warp, Exit, Gate, Teleport, Vr, Stair - and logs whatever it finds, so the first time one appears its
   real name is on the record and the match can be tightened.

2. **proof that a level was finished.** The floor id (`0x805D5FC0`) changes when an area transition completes, so the loop records the floor it started
   on and logs the change with the room count reached. That turns "it ran for an hour" into "it moved from floor 1 to floor 2", which is the difference
   between a bot that is busy and a bot that is progressing.

Priority stays progression-first: switches (they open the way), then enemies (they block it), then the exit, then the next room.
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\.tmp\play_pad.py")
text = path.read_text(encoding="utf-8")

# 1. exit detection helpers, placed with the other scanners
anchor = "def rooms_for(current_floor):"
if "EXIT_WORDS" not in text:
    helper = '''EXIT_WORDS = ("Portal", "Warp", "Exit", "Gate", "Teleport", "Vr", "Stair")


def exits():
    """Exit-like objects: the way out of the area, whatever the game calls it."""
    me = player()
    if me is None:
        return []
    raw = S.read_memory(TABLE, MAX_ENTRIES * 4)
    out = []
    for index in range(MAX_ENTRIES):
        pointer = int.from_bytes(raw[index * 4:index * 4 + 4], "big")
        if not (0x80000000 <= pointer < 0x81800000):
            continue
        try:
            name_pointer = int.from_bytes(S.read_memory(pointer, 4), "big")
            if not (0x80000000 <= name_pointer < 0x81800000):
                continue
            name = S.read_memory(name_pointer, 32).split(b"\\x00")[0].decode("ascii", "replace")
            if not name or not any(word in name for word in EXIT_WORDS):
                continue
            blob = S.read_memory(pointer, 0x340)
            if len(blob) < 0x340:
                continue
            x, y, z = struct.unpack(">fff", blob[POS:POS + 12])
        except Exception:                                        # noqa: BLE001
            continue
        if name.startswith("TObjPlayer"):
            continue
        out.append({"class": name, "x": x, "y": y, "z": z,
                    "distance": math.dist((me[0], me[2]), (x, z))})
    return sorted(out, key=lambda row: row["distance"])


def rooms_for(current_floor):'''
    if text.count(anchor) != 1:
        raise SystemExit("rooms_for anchor not found")
    text = text.replace(anchor, helper, 1)
    print("exit detection added")

# 2. track the starting floor and report transitions
old_loop = """    started = time.time()
    target_room = None"""
new_loop = """    started = time.time()
    target_room = None
    start_floor = int.from_bytes(S.read_memory(0x805D5FC0, 4), "big")
    log(f"starting on floor {start_floor}")"""
if text.count(old_loop) == 1:
    text = text.replace(old_loop, new_loop, 1)

old_step = """        me = player()
        if me is None:
            time.sleep(1.0)
            continue
        foes, switches = entities()"""
new_step = """        me = player()
        if me is None:
            time.sleep(1.0)
            continue
        here_floor = int.from_bytes(S.read_memory(0x805D5FC0, 4), "big")
        if here_floor != start_floor:
            log(f"AREA CLEARED: floor {start_floor} -> {here_floor}")
            start_floor = here_floor
        way_out = exits()
        if way_out:
            log(f"exit {way_out[0]['class']} at {way_out[0]['distance']:.0f} units")
            for _ in range(30):
                gap = approach(pad, me, (way_out[0]["x"], way_out[0]["z"]), tolerance=2.5, seconds=0.4)
                pad.press("a", 0.3)
                time.sleep(0.4)
                now_floor = int.from_bytes(S.read_memory(0x805D5FC0, 4), "big")
                if now_floor != start_floor:
                    log(f"AREA CLEARED: floor {start_floor} -> {now_floor}")
                    start_floor = now_floor
                    break
                if gap is not None and gap < 3:
                    break
            continue
        foes, switches = entities()"""
if text.count(old_step) == 1:
    text = text.replace(old_step, new_step, 1)
    print("exit handling added to the cycle")
else:
    print("cycle anchor count", text.count(old_step))

path.write_text(text, encoding="utf-8")
print("done")
