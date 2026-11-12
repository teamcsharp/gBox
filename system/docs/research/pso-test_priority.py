"""Test the loop's decision order: switches, then enemies, then the exit, then the nearest room.

Each case isolates one rule, including the two that are easy to get backwards:

  * an **open** switch (state 2) must not be chosen - pressing an already-open door wastes time;
  * an enemy is fought before an exit, because walking past the room's enemies to the door and being shot in the back is not progress.

`choose_action` is pure - no memory reads, no input - so the whole strategy is checked here without an emulator.
"""
import sys

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import play_pad                                                    # noqa: E402

failures = []


def check(label, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + label + (" - " + detail if detail else ""))
    if not condition:
        failures.append(label)


def enemy(distance=20.0, hp=100):
    return {"class": "TObjEneX", "x": distance, "y": 0.0, "z": 0.0, "hp": hp, "distance": distance}


def switch(state=224, distance=10.0):
    return {"class": "TObjDoorKey", "x": distance, "y": 0.0, "z": 0.0, "state": state, "distance": distance}


def exit_object(distance=100.0):
    return {"class": "TObjVrPortal", "x": distance, "y": 0.0, "z": 0.0, "distance": distance}


ROOMS = [{"room": 1, "centre": (500.0, 500.0)}, {"room": 2, "centre": (30.0, 0.0)}]
ME = (0.0, 0.0, 0.0)

kind, target = play_pad.choose_action([enemy()], [switch()], [exit_object()], ROOMS, ME)
check("switch wins over everything", kind == "switch", kind)
check("the switch chosen is the closed one", target["state"] == 224)

kind, target = play_pad.choose_action([], [switch(state=2)], [exit_object()], ROOMS, ME)
check("an open switch is not an action", kind != "switch", kind)
check("with no live switch the exit is next", kind == "exit", kind)

kind, _t = play_pad.choose_action([enemy()], [switch(state=2)], [exit_object()], ROOMS, ME)
check("enemy is fought before the exit", kind == "enemy", kind)

kind, target = play_pad.choose_action([], [], [exit_object()], ROOMS, ME)
check("exit when nothing else", kind == "exit", kind)
check("exit target is the exit", target["class"] == "TObjVrPortal", target["class"])

kind, target = play_pad.choose_action([], [], [], ROOMS, ME)
check("room when nothing else", kind == "room", kind)
check("the NEAREST room is chosen (30 away, not 500)", target["room"] == 2, str(target["room"]))

kind, target = play_pad.choose_action([], [], [], [], ME)
check("nothing to do waits", kind == "wait", kind)
check("wait has no target", target is None)

kind, _t = play_pad.choose_action([], [switch(state=0)], [], [], ME)
check("a closed switch (state 0) is still an action", kind == "switch", kind)

print()
if failures:
    print(f"{len(failures)} check(s) failed: {failures}")
    raise SystemExit(1)
print("all decision checks passed")
