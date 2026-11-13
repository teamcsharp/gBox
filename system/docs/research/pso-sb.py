"""Splice the clean no-enemies branch in, replacing the tangled lines, and declare the new counters."""
import pathlib
import py_compile

ENDLESS = pathlib.Path(r"C:\_tools\gBox\.tmp\endless.py")
BRANCH = pathlib.Path(r"C:\_tools\gBox\.tmp\new_branch.py")

lines = ENDLESS.read_text(encoding="utf-8").splitlines()
branch = BRANCH.read_text(encoding="utf-8").splitlines()

# the branch begins at the `        else:` immediately before the "A LEVEL-EXIT TELEPORTER" comment
start = None
for index, line in enumerate(lines):
    if "A LEVEL-EXIT TELEPORTER" in line:
        start = index
        break
if start is None:
    raise SystemExit("could not find the branch")
# walk back to the `else:` that owns it
while start > 0 and lines[start].strip() != "else:":
    start -= 1
print("branch else at line", start + 1)

# it ends at the last `moved += 1` before `        time.sleep(0.15)`
end = None
for index in range(start, min(start + 200, len(lines))):
    if lines[index].strip() == "time.sleep(0.15)":
        end = index - 1
        break
if end is None:
    raise SystemExit("could not find the branch end")
while end > start and lines[end].strip() != "moved += 1":
    end -= 1
print("branch ends at line", end + 1, ":", lines[end].strip())

spliced = lines[:start] + branch + lines[end + 1:]
text = "\n".join(spliced) + "\n"

# counters for the new warp logic
old_decl = "    pressed_keys, key_misses = set(), 0      # door keys already pressed this window, and approach misses"
new_decl = ("    pressed_keys, key_misses = set(), 0      # door keys already pressed this window, and approach misses\n"
            "    warped, warp_misses, warp_reported = 0, 0, None   # level exits entered, approach misses, last report")
if text.count(old_decl) == 1:
    text = text.replace(old_decl, new_decl, 1)
    print("warp counters declared")
else:
    print("decl anchor count:", text.count(old_decl))

ENDLESS.write_text(text, encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles")
