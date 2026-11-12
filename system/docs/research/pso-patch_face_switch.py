"""Face the switch before pressing it: step toward it, then press A.

The operator described the mechanic exactly: "if I was able to use my controller with the game right now, but it's ignoring me, I would basically rotate
the character slightly until the reticle appears on the switch and then have them press the switch."

In PSO the character faces the direction it moves, so a short step toward the switch *is* the rotation - the reticle appears once the facing is right,
and then A interacts. Pressing A while facing elsewhere does nothing, which is why five presses from 12 units changed nothing.

So the switch routine becomes a loop of small steps plus a press:

    while not open and attempts < 8:
        if distance > 2.5: step toward the switch for 0.12 s   (turns the character, closes the gap)
        press A for 0.3 s
        read the door state

Each iteration logs the distance and the state, so the record shows whether the character closed, whether the facing worked, and whether the door opened.
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\.tmp\play_rooms.py")
text = path.read_text(encoding="utf-8")

old = """    for attempt in range(5):
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
    return True"""

new = """    # step toward it (which turns the character toward it, so the reticle appears) and press A each time
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
    return True"""

if text.count(old) != 1:
    raise SystemExit(f"press loop count {text.count(old)}")
text = text.replace(old, new, 1)
path.write_text(text, encoding="utf-8")
print("switch routine now steps toward the switch (turning) and presses each time")
