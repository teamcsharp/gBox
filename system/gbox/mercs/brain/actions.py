"""The brain's abstract actions and the control maps that turn them into each title's buttons.

An action is a dict; every key is optional (absent = no):
    raise       the gun up (aim)                       fire        the trigger down (with raise)
    aim         (yaw, pitch), each -1 / 0 / +1: the right stick moving the aim while it is up (+yaw = left, +pitch = up)
    turn        -1 / 0 / +1: the body turning with the gun down (+ = left, a larger heading)
    move        "forward" | "back" | "left" | "right"  run         the run button with move
    quick_turn  the 180-degree quick turn (stick back + run)
    reload      reload the gun in hand                 use_item    use the recovery item in hand
    wiggle      1 / 2: the left stick shaken left / right (break free)
    mash        the title's resuscitate / struggle button
    press       "action" | "dpad_up" | "dpad_down" | "dpad_left" | "dpad_right": one tap of that button
Titles map them with keys(action, controls). Holds come back sorted as a tuple ({"hold": (...)}); a press is a tap
({"tap": key}) and wins over holds that tick (the engine presses a tap alone).
"""
from __future__ import annotations

# The two pads so far. RE5 PS3: gBox pad names = PS3 buttons (gbox.adapters.RPCS3_KEYPAD), Type D (re5_ps3's controls).
# RE5 / RE6 Switch: Type D as the game's Controller Settings show it (re5_switch's controls).
RE5_PS3 = {"raise": ("l1",), "fire": ("r1",), "aim_left": ("rleft",), "aim_right": ("rright",), "aim_up": ("rup",),
           "aim_down": ("rdown",), "turn_left": ("rleft",), "turn_right": ("rright",), "forward": ("lup",),
           "back": ("ldown",), "left": ("lleft",), "right": ("lright",), "run": ("cross",),
           "quick_turn": ("ldown", "cross"), "reload": ("l1", "cross"), "use_item": ("square",),
           "wiggle_left": ("lleft",), "wiggle_right": ("lright",), "mash": ("cross",), "action": "square",
           "dpad_up": "dup", "dpad_down": "ddown", "dpad_left": "dleft", "dpad_right": "dright"}
SWITCH_TYPE_D = {"raise": ("zl",), "fire": ("zr",), "aim_left": ("rleft",), "aim_right": ("rright",), "aim_up": ("rup",),
                 "aim_down": ("rdown",), "turn_left": ("rleft",), "turn_right": ("rright",), "forward": ("lup",),
                 "back": ("ldown",), "left": ("lleft",), "right": ("lright",), "run": ("b",),
                 "quick_turn": ("ldown", "b"), "reload": ("zl", "b"), "use_item": ("y",),
                 "wiggle_left": ("lleft",), "wiggle_right": ("lright",), "mash": ("a",), "action": "a",
                 "dpad_up": "dup", "dpad_down": "ddown", "dpad_left": "dleft", "dpad_right": "dright"}
CONTROLS = {"re5_ps3": RE5_PS3, "switch_type_d": SWITCH_TYPE_D}


def keys(action: dict, controls: dict) -> dict:
    """{"hold": tuple(sorted keys)} or {"tap": key} for one abstract action on one pad."""
    action = action or {}
    if action.get("press"):
        return {"tap": controls[action["press"]]}
    held: set = set()
    if action.get("raise") or action.get("fire"):
        held.update(controls["raise"])
    if action.get("fire"):
        held.update(controls["fire"])
    yaw, pitch = (action.get("aim") or (0, 0))
    if yaw:
        held.update(controls["aim_left" if yaw > 0 else "aim_right"])
    if pitch:
        held.update(controls["aim_up" if pitch > 0 else "aim_down"])
    if action.get("turn"):
        held.update(controls["turn_left" if action["turn"] > 0 else "turn_right"])
    if action.get("move"):
        held.update(controls[action["move"]])
        if action.get("run"):
            held.update(controls["run"])
    if action.get("quick_turn"):
        held.update(controls["quick_turn"])
    if action.get("reload"):
        held.update(controls["reload"])
    if action.get("use_item"):
        held.update(controls["use_item"])
    if action.get("wiggle"):
        held.update(controls["wiggle_left" if action["wiggle"] == 1 else "wiggle_right"])
    if action.get("mash"):
        held.update(controls["mash"])
    return {"hold": tuple(sorted(held))}
