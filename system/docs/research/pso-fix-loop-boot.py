"""Apply the loop-boot that never landed: when there is no character, press in, don't idle.

Round 35 claimed to add a boot inside the loop. It did not: the patch reported "anchor count: 0" and I moved on, so the loop still does

```python
me = player()
if me is None:
    time.sleep(1.0)
    continue
```

which is why `play_rooms` has been alive and silent since 04:37:28 - floor 0, no character, and not a single log line, because it is idling once a second
forever instead of pressing START to get into the game.

This replaces exactly that block with a call to `boot()`, which presses START/A, logs each round, and is bounded. The indentation must match the loop body
(12 spaces).
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\.tmp\play_rooms.py")
text = path.read_text(encoding="utf-8")

old = """            me = player()
            if me is None:
                time.sleep(1.0)
                continue"""
new = """            me = player()
            if me is None:
                boot()            # no character: press back in rather than idling silently
                continue"""

count = text.count(old)
print("anchor count:", count)
if count == 1:
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print("the loop now boots when there is no character")
else:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if "if me is None" in line:
            print(f"  line {index + 1}: {lines[index - 1].strip()[:60]} | {line.strip()} | {lines[index + 1].strip()[:40] if index + 1 < len(lines) else ''}")

import py_compile
py_compile.compile(str(path), doraise=True)
print("compile: OK")

import inspect
import sys
sys.path.insert(0, r"C:\_tools\gBox\.tmp")
import importlib
import play_rooms
importlib.reload(play_rooms)
source = inspect.getsource(play_rooms.main)
print("main now calls boot in the loop:", "boot()            # no character" in source)
