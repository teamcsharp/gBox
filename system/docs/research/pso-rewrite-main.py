"""Rewrite play_pad.main so the loop dispatches on choose_action - the tested decision is the one that runs.

Everything below `def main(` is replaced with a version that:

  * boots through the title, calibrates the stick, then loops;
  * calls `choose_action` for the decision and dispatches to exactly the same action bodies as before (switch stepping, enemy fighting, exit walking,
    room walking, waiting);
  * logs the floor at start and any floor change as `AREA CLEARED`, which is the completion signal;
  * honours the PAUSED file and yields to the operator's pad;
  * resets the pad on exit.

The action bodies are carried over unchanged from the previous version; only the selection moved into the tested function.
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\.tmp\play_pad.py")
text = path.read_text(encoding="utf-8")

start = text.find("def main(seconds=3600.0):")
if start < 0:
    raise SystemExit("main not found")

body = '''def main(seconds=3600.0):
    log("=== pad-driven play")
    pad = vpad.Pad()
    if not boot(pad):
        log("no character to play - stopping")
        return 2
    log("calibrating the stick against the character")
    table = pad.calibrate(read_pos)
    for name, move in table.items():
        log(f"  stick {name}: moved ({move[0]:+.1f}, {move[1]:+.1f})")
    if not table:
        log("calibration produced nothing - is the game in the field?")
        return 1

    started = time.time()
    start_floor = int.from_bytes(S.read_memory(0x805D5FC0, 4), "big")
    log(f"starting on floor {start_floor}")

    while time.time() - started < seconds:
        if os.path.exists(r"D:\\gBox\\pso-ds\\PAUSED") or OP.operator_active():
            time.sleep(0.6)
            continue
        me = player()
        if me is None:
            time.sleep(1.0)
            continue

        here_floor = int.from_bytes(S.read_memory(0x805D5FC0, 4), "big")
        if here_floor != start_floor:
            log(f"AREA CLEARED: floor {start_floor} -> {here_floor}")
            start_floor = here_floor

        foes, switches = entities()
        way_out = exits()
        room_list = rooms_for(here_floor)
        kind, target = choose_action(foes, switches, way_out, room_list, me)
        log(f"decision: {kind}" + (f" ({target.get('class', target.get('room'))})" if isinstance(target, dict) else ""))

        if kind == "switch":
            log(f"switch {target['class']} state {target['state']} at {target['distance']:.0f} units")
            for attempt in range(10):
                current = player()
                if current is None:
                    break
                gap = approach(pad, current, (target["x"], target["z"]), tolerance=2.5)
                pad.press("a", 0.28)
                time.sleep(0.25)
                _foes, again = entities()
                now = next((row for row in again if row["class"] == target["class"]
                            and math.dist((row["x"], row["z"]), (target["x"], target["z"])) < 8), None)
                state = now["state"] if now else None
                log(f"  step+press x{attempt + 1}: at {gap if gap is None else round(gap, 1)} units, state {state}")
                if state == 2 or now is None:
                    log("  switch handled")
                    break

        elif kind == "enemy":
            log(f"enemy {target['class']} hp {target['hp']} at {target['distance']:.0f} units")
            for attempt in range(12):
                current = player()
                if current is None:
                    break
                gap = approach(pad, current, (target["x"], target["z"]), tolerance=3.0)
                pad.press("a", 0.3)
                if gap is not None and gap > 25:
                    pad.press("b", 0.3)
                time.sleep(0.2)
                _foes, _switches = entities()
                still = next((row for row in _foes if row["class"] == target["class"]), None)
                if still is None:
                    log("  enemy down")
                    break
                target = still

        elif kind == "exit":
            log(f"exit {target['class']} at {target['distance']:.0f} units")
            for _ in range(30):
                current = player()
                if current is None:
                    break
                gap = approach(pad, current, (target["x"], target["z"]), tolerance=2.5, seconds=0.4)
                pad.press("a", 0.3)
                time.sleep(0.4)
                now_floor = int.from_bytes(S.read_memory(0x805D5FC0, 4), "big")
                if now_floor != start_floor:
                    log(f"AREA CLEARED: floor {start_floor} -> {now_floor}")
                    start_floor = now_floor
                    break
                if gap is not None and gap < 3:
                    break

        elif kind == "room":
            label = target.get("room")
            centre = (target["centre"][0], target["centre"][1])
            log(f"heading for room {label}")
            for _ in range(40):
                current = player()
                if current is None:
                    break
                gap = approach(pad, current, centre, tolerance=20.0, seconds=0.4)
                if gap is None or gap < 25:
                    log(f"  room {label} reached")
                    break
                if OP.operator_active():
                    break
            else:
                log("  could not reach it - trying another room")

        else:
            time.sleep(0.8)

    pad.reset()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(float(sys.argv[1]) if len(sys.argv) > 1 else 3600.0))
'''

path.write_text(text[:start] + body, encoding="utf-8")
print("main rewritten to dispatch on choose_action")
