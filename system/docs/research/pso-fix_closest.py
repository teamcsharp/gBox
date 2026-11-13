"""Define `closest` where the loop's other counters are defined, and report it."""
import pathlib
import py_compile

ENDLESS = pathlib.Path(r"C:\_tools\gBox\.tmp\endless.py")
text = ENDLESS.read_text(encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles BEFORE")

old = "    last_position, stuck, killed, moved = None, 0, 0, 0.0"
new = "    last_position, stuck, killed, moved, closest = None, 0, 0, 0.0, 999.0"
if text.count(old) != 1:
    raise SystemExit("counter anchor count: %d" % text.count(old))
text = text.replace(old, new, 1)
print("closest defined alongside the other counters")

old_return = '    return f"played {seconds:.0f}s, {moved} travel steps"'
new_return = '    return f"played {seconds:.0f}s, {moved} travel steps, closest approach {closest:.1f}"'
if text.count(old_return) == 1:
    text = text.replace(old_return, new_return, 1)
    print("return now reports the closest approach")
else:
    print("return anchor count:", text.count(old_return))

ENDLESS.write_text(text, encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles AFTER")

# prove the names used are the names defined
body = text.split("def play(", 1)[1]
for name in ("closest", "moved", "killed", "stuck"):
    print(f"  {name}: defined={'%s =' % name in body or ', %s =' % name in body}, used={'{%s' % name in body or '%s +=' % name in body or 'min(%s' % name in body}")
