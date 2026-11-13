"""Fix the town check: `now` does not exist at that point in the frame.

The town rule was inserted before the local `now` is assigned, so `isinstance(globals().get("now"), dict)` always fell
through to `state(pad)` - but the bare `now` in the expression raised `NameError` the moment the line ran. `pyflakes`
caught it as `undefined name 'now'`, which is exactly why it is run before every restart.

The rule does not need `now` at all: it needs the entity list, so it asks for the state directly.
"""
import pathlib
import py_compile

ENDLESS = pathlib.Path(r"C:\_tools\gBox\.tmp\endless.py")
lines = ENDLESS.read_text(encoding="utf-8").splitlines()

fixed = 0
for index, line in enumerate(lines):
    if 'isinstance(globals().get("now"), dict)' in line:
        indent = len(line) - len(line.lstrip())
        lines[index] = " " * indent + '_town_state = state(pad)'
        fixed += 1
        print("fixed line", index + 1)

if not fixed:
    raise SystemExit("town-state line not found")

ENDLESS.write_text("\n".join(lines) + "\n", encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles AFTER")
