"""Delete the now-unused suspension helpers and their leftover state."""
import pathlib
import py_compile

RELAY = pathlib.Path(r"C:\_tools\gBox\.tmp\controller_relay.py")
lines = RELAY.read_text(encoding="utf-8").splitlines()
print("lines before:", len(lines))

out = []
skipping = False
for line in lines:
    stripped = line.strip()
    if stripped.startswith("def suspend_bots(") or stripped.startswith("def resume_bots("):
        skipping = True
        continue
    if skipping:
        # skip the body until the next top-level def or a blank-then-def boundary
        if line and not line.startswith((" ", "\t")) and not stripped.startswith("#"):
            skipping = False
        else:
            continue
    if stripped == "frozen = []":
        continue
    out.append(line)

# collapse any run of 3+ blank lines left behind
collapsed = []
for line in out:
    if not line.strip() and collapsed and not collapsed[-1].strip() and len(collapsed) >= 2 and not collapsed[-2].strip():
        continue
    collapsed.append(line)

RELAY.write_text("\n".join(collapsed) + "\n", encoding="utf-8")
py_compile.compile(str(RELAY), doraise=True)
print("lines after:", len(collapsed))
text = RELAY.read_text(encoding="utf-8")
print("suspend_bots refs:", text.count("suspend_bots"), "| resume_bots:", text.count("resume_bots"), "| frozen:", text.count("frozen"))
