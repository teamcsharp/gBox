"""Repair the misplaced NPC guard block in endless.py.

The guard was inserted at the wrong indent: it landed inside `if bdist <= 220.0:` but at the level of its body, and it
swallowed the `if bdist <= 20.0:` that follows - producing "expected an indented block after 'if' statement".

The correct shape is a nested guard:

    if bdist <= 220.0:
        if <any NPC within 25>:
            back away; continue
        if bdist <= 20.0:
            for _ in range(3):
                ...
"""
import pathlib
import py_compile

ENDLESS = pathlib.Path(r"C:\_tools\gBox\.tmp\endless.py")
lines = ENDLESS.read_text(encoding="utf-8").splitlines()
print("lines:", len(lines))

# locate the malformed guard: the line that opens the NPC test inside the box block
start = None
for index, line in enumerate(lines):
    if line.strip().startswith("if any(is_npc(e)") and line.startswith("                if any(is_npc"):
        start = index
        break
if start is None:
    raise SystemExit("malformed guard not found")

# the broken region runs from that `if` to the `if bdist <= 20.0:` line inclusive
end = start
while end < len(lines) and "if bdist <= 20.0:" not in lines[end]:
    end += 1
if end >= len(lines):
    raise SystemExit("the bdist <= 20.0 line was not found after the guard")
print("replacing lines %d..%d" % (start + 1, end + 1))

BLOCK = [
    '                if any(is_npc(e) and e.get("x") is not None and e.get("z") is not None',
    '                       and math.hypot(float(e.get("x") or 0) - x, float(e.get("z") or 0) - z) < 25.0',
    '                       for e in (now.get("entities") or [])):',
    '                    # An NPC is close: step away rather than press A and open a dialog that freezes us.',
    '                    hold(pad, "down", 0.6)',
    '                    time.sleep(0.1)',
    '                    continue',
    '                if bdist <= 20.0:        # real PMT range is 13-30 units (was 8, from the fallback)',
]
lines[start:end + 1] = BLOCK
ENDLESS.write_text("\n".join(lines) + "\n", encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles AFTER")

# show the repaired region
text = ENDLESS.read_text(encoding="utf-8").splitlines()
for index in range(start - 4, min(start + 12, len(text))):
    print("%4d: %s" % (index + 1, text[index]))
