"""Route every bot's key presses through pso_input, so no script can bypass the operator lock.

Replaces the local hold/tap helpers in explore.py and flip_switches.py with pso_input's locked versions (which check the operator lock
before every key and declare the action window), and verifies the swap.
"""
import pathlib

REPLACEMENTS = {
    r"C:\_tools\gBox\.tmp\explore.py": (
        '''def hold(key, seconds):
    OP.note_bot_input(seconds + 0.25)
    G.send([{"key": key, "down": True}])
    time.sleep(seconds)
    G.send([{"key": key, "down": False}])
    time.sleep(0.05)


def tap(key, gap=0.35):
    OP.note_bot_input(0.3)
    G.send([{"key": key, "down": True}, {"key": key, "down": False}])
    time.sleep(gap)''',
        '''import pso_input

hold = pso_input.hold
tap = pso_input.tap''',
        ),
    r"C:\_tools\gBox\.tmp\flip_switches.py": (
        '''def hold(key, seconds):
    OP.note_bot_input(seconds + 0.25)
    G.send([{"key": key, "down": True}])
    time.sleep(seconds)
    G.send([{"key": key, "down": False}])
    time.sleep(0.05)


def tap(key, gap=0.35):
    OP.note_bot_input(0.3)
    G.send([{"key": key, "down": True}, {"key": key, "down": False}])
    time.sleep(gap)''',
        '''import pso_input

hold = pso_input.hold
tap = pso_input.tap''',
        ),
}

for path_text, (old, new) in REPLACEMENTS.items():
    path = pathlib.Path(path_text)
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        print(f"{path.name}: pattern count {count} (skipped)")
        continue
    path.write_text(text.replace(old, new), encoding="utf-8")
    print(f"{path.name}: input now goes through pso_input")

# verify
for path_text in REPLACEMENTS:
    name = pathlib.Path(path_text).name
    text = pathlib.Path(path_text).read_text(encoding="utf-8")
    print(f"{name}: uses pso_input = {'hold = pso_input.hold' in text}")
