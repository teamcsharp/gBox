"""Patch map_bot onto the v2 operator lock: every hold declares its input window, so operator motion is never mistaken for the bot's.

Without this the bot's 0.7 s strides masked the operator's input and the lock never engaged - the exact bug the operator reported.
"""
import pathlib

PATH = pathlib.Path(r"C:\_tools\gBox\.tmp\map_bot.py")
text = PATH.read_text(encoding="utf-8")

text = text.replace("import pso_operator", "import pso_operator2 as pso_operator")

OLD_SEND = '''def send(events):
    if not pso_operator.guard():
        return {}
    import game_input
    pso_operator.note_bot_input()
    game_input.PID = None                                        # resolve the live pid
    return events if game_input.send(events) else {}'''

NEW_SEND = '''def send(events, window=0.25):
    """Send one batch and declare how long it affects the game, so the operator lock can tell our motion from theirs."""
    if not pso_operator.guard():
        return {}
    import game_input
    pso_operator.note_bot_input(window)
    game_input.PID = None                                        # resolve the live pid
    return events if game_input.send(events) else {}'''

assert text.count(OLD_SEND) == 1, text.count(OLD_SEND)
text = text.replace(OLD_SEND, NEW_SEND)

OLD_HOLD = '''def hold(keys, seconds):
    if isinstance(keys, str):
        keys = [keys]
    keys = list(keys)
    send([{"key": k, "down": True} for k in keys])
    time.sleep(seconds)
    send([{"key": k, "down": False} for k in keys])
    time.sleep(0.03)'''

NEW_HOLD = '''def hold(keys, seconds):
    if isinstance(keys, str):
        keys = [keys]
    keys = list(keys)
    pso_operator.note_bot_input(seconds + 0.25)
    send([{"key": k, "down": True} for k in keys], window=seconds + 0.25)
    time.sleep(seconds)
    send([{"key": k, "down": False} for k in keys], window=0.25)
    time.sleep(0.03)'''

assert text.count(OLD_HOLD) == 1, text.count(OLD_HOLD)
text = text.replace(OLD_HOLD, NEW_HOLD)

OLD_TAP = '''def tap(key, times=1, gap=0.3):
    for _ in range(times):
        send([{"key": key, "down": True}, {"key": key, "down": False}])
        time.sleep(gap)'''
NEW_TAP = '''def tap(key, times=1, gap=0.3):
    for _ in range(times):
        if not pso_operator.guard():
            return
        pso_operator.note_bot_input(0.3)
        send([{"key": key, "down": True}, {"key": key, "down": False}], window=0.3)
        time.sleep(gap)'''
if text.count(OLD_TAP) == 1:
    text = text.replace(OLD_TAP, NEW_TAP)

PATH.write_text(text, encoding="utf-8")
print("map_bot uses the v2 lock and declares every input window")
