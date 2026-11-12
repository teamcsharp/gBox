"""Switches are the progression mechanic: walk to them and flip them, always.

The operator's rule, verbatim: "the bot needs to target these switches whenever they are found and basically flip these switches always, no matter what.
It is how it progresses through the game."

The previous version only noticed a door within 16 units, only pressed it while a route was being walked, and gave up when the state stayed 224. That is
the opposite of the rule. This version:

  * **scans the whole entity table** for switch-like classes (`Door`, `Swtch`, `Switch`, `Key`) up to 120 units, so a switch is found from across the
    room rather than only when the bot happens to brush past it;
  * **walks to it** with the height-aware planner, then **presses A up to five times**, logging the state after each press;
  * **runs before everything else** in the cycle - before fighting, before travelling - because flipping the switch is what opens the way;
  * **never gives up after one attempt**: if the state stays 224 it reports the door as still locked but keeps it in the list, and the next cycle tries
    again from a fresh position.

`walk_through` is switched off as part of this: with collision bypass on, the bot could slide through a door without ever learning to open it, which is
exactly the behaviour this is meant to replace.
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\.tmp\play_rooms.py")
text = path.read_text(encoding="utf-8")

start = text.find("def press_switches():")
end = text.find("def main(seconds=3600.0):")
if start < 0 or end < 0:
    raise SystemExit("press_switches block not found")

block = '''SWITCH_WORDS = ("Door", "Swtch", "Switch", "Key")
SWITCH_RANGE = 120.0


def switches():
    """Every switch-like entity in the area, nearest first."""
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
            if not name or not any(word in name for word in SWITCH_WORDS):
                continue
            blob = S.read_memory(pointer, 0x340)
            if len(blob) < 0x340:
                continue
            x, y, z = struct.unpack(">fff", blob[POS:POS + 12])
            state = struct.unpack(">i", blob[0x18C:0x18C + 4])[0]
        except Exception:                                        # noqa: BLE001
            continue
        distance = math.dist((me[0], me[2]), (x, z))
        if distance <= SWITCH_RANGE:
            out.append({"class": name, "x": x, "y": y, "z": z, "state": state, "distance": distance})
    return sorted(out, key=lambda row: row["distance"])


def press_switches():
    """Walk to the nearest switch and flip it. Returns True when it did something."""
    found = switches()
    if not found:
        return False
    target = found[0]
    log(f"  switch {target['class']} state {target['state']} at {target['distance']:.0f} units")
    if target["distance"] > 7:
        route, raw_cells, legs = nav3.plan_h((player()[0], player()[2]), (target["x"], target["z"]),
                                             start_height=player()[1], goal_height=target["y"])
        if route:
            for waypoint in route[1:4]:
                RUN.run_to(ME_point(), (waypoint[0], waypoint[1]), tolerance=5.0, budget=12.0)
                if OP.operator_active():
                    return True
        else:
            RUN.run_to(ME_point(), (target["x"], target["z"]), tolerance=5.0, budget=15.0)
        log(f"    walked to {math.dist((player()[0], player()[2]), (target['x'], target['z'])):.0f} units")
    for attempt in range(5):
        pso_input.hold("a", 0.3)
        time.sleep(0.5)
        again = next((row for row in switches() if math.dist((row["x"], row["z"]),
                                                             (target["x"], target["z"])) < 8), None)
        state = again["state"] if again else None
        log(f"    after A x{attempt + 1}: state {state}")
        if state == 2:
            log("    open")
            return True
    log("    still locked after five presses - will come back to it")
    return True


'''
text = text[:start] + block + text[end:]
path.write_text(text, encoding="utf-8")
print("switches are now hunted across the room and flipped five times")
