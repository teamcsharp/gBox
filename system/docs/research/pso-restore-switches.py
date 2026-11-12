"""Restore the switch functions that the focus patch removed.

The focus patch replaced everything between `def ensure_focus()` and `def main(...)`, and the switch helpers lived in that span, so the loop died with
`NameError: press_switches is not defined` on every cycle. They are re-inserted ahead of `main`, with the same behaviour as before:

  * **scan the whole entity table** for switch-like classes (`Door`, `Swtch`, `Switch`, `Key`) up to 120 units;
  * **walk to the nearest**, then **step toward it before each A press** - the step is what turns the character so the reticle appears;
  * press up to eight times, logging the distance and the door state every iteration.
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\.tmp\play_rooms.py")
text = path.read_text(encoding="utf-8")

if "def press_switches(" in text:
    print("press_switches already present")
else:
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
    """Walk to the nearest switch and flip it: step toward it (which turns the character), then press A."""
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
    for attempt in range(8):
        me = player()
        if me is None:
            return True
        here = math.dist((me[0], me[2]), (target["x"], target["z"]))
        if here > 2.5:
            step = RUN.unit(target["x"] - me[0], target["z"] - me[2])
            table = RUN.calibrate(ME_point())
            key, _align = RUN.best_key(table, step)
            if key is not None:
                pso_input.hold(key, 0.12)
        pso_input.hold("a", 0.3)
        time.sleep(0.45)
        again = next((row for row in switches() if math.dist((row["x"], row["z"]),
                                                             (target["x"], target["z"])) < 8), None)
        state = again["state"] if again else None
        log(f"    step+press x{attempt + 1}: at {here:.1f} units, state {state}")
        if state == 2:
            log("    open")
            return True
    log("    still locked after eight step-and-press attempts - will come back to it")
    return True


def main(seconds=3600.0):'''
    if text.count("def main(seconds=3600.0):") != 1:
        raise SystemExit("main anchor not unique")
    text = text.replace("def main(seconds=3600.0):", block, 1)
    path.write_text(text, encoding="utf-8")
    print("switch functions restored")
