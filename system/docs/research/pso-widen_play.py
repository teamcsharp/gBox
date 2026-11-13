"""Give play() long enough to finish an approach, and keep the hill-climb's side across windows.

Two things conspire to stop the loop ever landing a kill even though the hill-climb provably works:

* **`play()` runs for 45 s.** Closing an enemy from 210 units takes about 48 hill-climb steps at ~1.1 s each, so the window expires mid-approach and every cycle restarts the walk from
  wherever it happens to be. The bot was observed chasing the same `TObjEneBeast` through rooms 15, 16, 12 and 11 over 336 units without one kill.
* **the side choice lived in `globals()`**, which survives but is clumsy; it becomes a module constant so it is explicit.

So the window grows to 120 s - enough to close and swing several times - and the log reports the closest approach it managed, which is the number that shows whether combat is converging.
"""
import pathlib
import py_compile

ENDLESS = pathlib.Path(r"C:\_tools\gBox\.tmp\endless.py")
text = ENDLESS.read_text(encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles BEFORE")

old_call = "outcome = play(pad, seconds=45)"
new_call = "outcome = play(pad, seconds=120)"
print("call anchor count:", text.count(old_call))
if text.count(old_call) == 1:
    text = text.replace(old_call, new_call, 1)
    print("play window: 45s -> 120s")

old_def = "def play(pad: Pad, seconds: float = 45.0) -> str:"
new_def = "def play(pad: Pad, seconds: float = 120.0) -> str:"
if text.count(old_def) == 1:
    text = text.replace(old_def, new_def, 1)
    print("default window: 45s -> 120s")

# report the closest approach, so convergence is visible in the log
old_report = 'log(f"played {seconds:.0f}s, {moved:.1f} travel steps")'
new_report = 'log(f"played {seconds:.0f}s, {moved:.1f} travel steps, closest approach {closest:.1f} units")'
if text.count(old_report) == 1:
    text = text.replace(old_report, new_report, 1)
    print("closest-approach reporting added")
else:
    print("report anchor count:", text.count(old_report))

# define closest next to the loop's other counters
anchor = "    moved = 0.0"
if text.count(anchor) == 1:
    text = text.replace(anchor, "    moved = 0.0\n    closest = 999.0", 1)
    print("closest counter defined")
else:
    print("moved anchor count:", text.count(anchor))

# track it whenever an enemy is in sight
anchor2 = """            name = str(target.get("class"))"""
if text.count(anchor2) == 1:
    text = text.replace(anchor2, """            closest = min(closest, distance)
            name = str(target.get("class"))""", 1)
    print("closest tracked")

ENDLESS.write_text(text, encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles AFTER")
